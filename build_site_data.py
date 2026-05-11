"""Generate all JSON files the website needs.

Produces under `site/data/`:
  - regular_season.json   regular-season-only rankings (model trained on RS)
  - playoffs.json         playoff-only rankings (same model, applied to playoff stats)
  - daily/YYYY-MM-DD.json one per recent date with NBA games
  - daily/index.json      list of available dates + game/player counts
  - daily.json            alias for the most recent day (compat)
  - meta.json             model coefficients + R² + cap + dates
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from nba_value.box_scores import fetch_daily_history
from nba_value.features import ALL_FEATURES, add_engineered_columns
from nba_value.fetch import (
    fetch_advanced_stats,
    fetch_contracts,
)
from nba_value.model import train_market_rate_model
from nba_value.surplus import compute_surplus


SEASON_END_YEAR = 2026
SALARY_CAP = 154_647_000  # NBA 2025-26 cap
REGULAR_SEASON_GAMES = 82
MIN_MINUTES_RS = 500       # ranking threshold for regular-season (full 82-game sample)
MIN_MINUTES_PLAYOFFS = 100  # playoffs have far fewer games — relax the floor
DAILY_HISTORY_DAYS = 28     # how many days of daily box scores to pre-generate

OUT_DIR = Path(__file__).parent / "site" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)
DAILY_DIR = OUT_DIR / "daily"
DAILY_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cached(name: str, fetcher, force: bool = False):
    """Load `name`.pkl from cache, else call `fetcher()`, save, return.
    Set force=True to refetch. Reruns skip BBR steps 1-3 if cache exists.
    Delete .cache/<name>.pkl to refetch a single source."""
    cache_path = CACHE_DIR / f"{name}.pkl"
    if cache_path.exists() and not force:
        print(f"      [cache] loading {cache_path.relative_to(Path.cwd())}")
        return pd.read_pickle(cache_path)
    df = fetcher()
    df.to_pickle(cache_path)
    print(f"      [cache] saved {cache_path.relative_to(Path.cwd())}")
    return df


def _safe(v):
    """JSON-safe scalar (handles NaN, numpy types)."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (np.floating,)):
        if math.isnan(float(v)) or math.isinf(float(v)):
            return None
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def _rows_to_records(df: pd.DataFrame) -> list[dict]:
    return [{k: _safe(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


def _merge_for_ranking(stats: pd.DataFrame, contracts: pd.DataFrame, cap: float) -> pd.DataFrame:
    merged = stats.merge(contracts, on="name", how="inner").drop_duplicates(subset=["name"])
    if "contract_team" in merged.columns:
        merged["team"] = merged["team"].fillna("").replace("", pd.NA).fillna(merged["contract_team"])
        merged = merged.drop(columns=["contract_team"])
    merged["season_cap"] = cap
    merged = add_engineered_columns(merged)
    needed = [c for c in ALL_FEATURES if c in merged.columns] + ["cap_pct"]
    return merged.dropna(subset=needed)


def train_rs_market_model(reg: pd.DataFrame, contracts: pd.DataFrame, cap: float):
    """Fit the market-rate model on regular-season data only.
    The 82-game sample is the most stable signal of where the market prices production.
    """
    merged = _merge_for_ranking(reg, contracts, cap)
    trainable = merged[merged["total_minutes"] >= MIN_MINUTES_RS].copy()
    model = train_market_rate_model(trainable)
    return model, trainable


def score_and_rank(stats: pd.DataFrame, contracts: pd.DataFrame, cap: float, model, min_minutes: int):
    """Apply an already-trained model to a stats DataFrame and rank by surplus."""
    merged = _merge_for_ranking(stats, contracts, cap)
    eligible = merged[merged["total_minutes"] >= min_minutes].copy()
    scored = compute_surplus(eligible, model, current_season_cap=cap)
    scored = scored.sort_values("surplus_cap_pct", ascending=False).reset_index(drop=True)
    scored.insert(0, "rank", scored.index + 1)

    keep = [
        "rank", "name", "team", "age", "position",
        "games_played", "total_minutes",
        "bpm", "dws", "vorp", "ts_pct", "usg_pct", "ast_pct", "stl_pct", "orb_pct",
        "salary", "actual_cap_pct", "expected_cap_pct", "surplus_cap_pct",
        "expected_salary", "surplus_dollars",
    ]
    return scored[[c for c in keep if c in scored.columns]].copy()


def model_meta(model, n_players: int) -> dict:
    return {
        "n_players": int(n_players),
        "model_r2": float(model.in_sample_r2),
        "model_cv_mae_cap_pct": float(model.cv_mae),
        "coefficients": [
            {"feature": name, "coef_per_sd": float(val)}
            for name, val in model.coefficients.items()
        ],
    }


def build_daily(box: pd.DataFrame, contracts: pd.DataFrame, cap: float, game_date: date) -> dict:
    """For each player who played on `game_date`, compute single-game surplus
    from Game Score (GmSc) and their pro-rated per-game salary.
    """
    merged = box.merge(contracts[["name", "salary"]], on="name", how="left")
    merged["salary"] = merged["salary"].fillna(SALARY_CAP * 0.012)  # default to vet-min
    merged["per_game_salary"] = merged["salary"] / REGULAR_SEASON_GAMES

    # Calibrate $/GmSc from this night's distribution among meaningful minutes.
    qual = merged[merged["minutes"] >= 20]
    if len(qual) < 4:
        qual = merged
    median_gmsc = max(float(qual["gmsc"].median()), 1.0)
    median_per_game_salary = float(qual["per_game_salary"].median())
    dollars_per_gmsc = median_per_game_salary / median_gmsc

    merged["value_dollars"] = merged["gmsc"].clip(lower=0) * dollars_per_gmsc
    merged["surplus_dollars"] = merged["value_dollars"] - merged["per_game_salary"]
    merged = merged.sort_values("surplus_dollars", ascending=False).reset_index(drop=True)
    merged.insert(0, "rank", merged.index + 1)

    # Per-game UI fields
    keep = [
        "rank", "name", "team", "opp",
        "minutes", "pts", "ast", "trb", "stl", "blk", "tov",
        "fg", "fga", "three", "threea", "ft", "fta",
        "gmsc", "plus_minus",
        "salary", "per_game_salary", "value_dollars", "surplus_dollars",
    ]
    out_rows = _rows_to_records(merged[[c for c in keep if c in merged.columns]])

    # Group games for the page header
    games = (
        merged.assign(matchup=lambda d: d.apply(
            lambda r: " @ ".join(sorted([str(r["team"]), str(r["opp"])])), axis=1))
        .groupby("matchup")
        .agg(
            home=("team", "first"),
            away=("opp", "first"),
            players=("name", "size"),
            top_gmsc=("gmsc", "max"),
        )
        .reset_index()
    )
    return {
        "game_date": game_date.isoformat(),
        "dollars_per_gmsc": dollars_per_gmsc,
        "median_gmsc": median_gmsc,
        "median_per_game_salary": median_per_game_salary,
        "games": _rows_to_records(games),
        "players": out_rows,
    }


def main() -> None:
    print(f"=== Building site data | cap=${SALARY_CAP/1e6:.1f}M | season={SEASON_END_YEAR-1}-{str(SEASON_END_YEAR)[-2:]} ===")

    print("\n[1/4] Regular-season advanced stats…")
    reg = _cached("reg_advanced_2026", lambda: fetch_advanced_stats(SEASON_END_YEAR, playoffs=False))
    print(f"      {len(reg)} players")

    print("\n[2/4] Playoff advanced stats…")
    try:
        playoffs = _cached("playoff_advanced_2026",
                           lambda: fetch_advanced_stats(SEASON_END_YEAR, playoffs=True))
        print(f"      {len(playoffs)} playoff players")
    except Exception as e:
        print(f"      no playoff data yet: {e}")
        playoffs = reg.iloc[0:0].copy()

    print("\n[3/4] Contracts…")
    contracts = _cached("contracts_2026",
                        lambda: fetch_contracts().drop_duplicates(subset=["name"], keep="first"))
    print(f"      {len(contracts)} contract rows")

    # Train the market-rate model on regular-season data only.
    # The 82-game sample is the most stable read on what the market pays.
    print("\n      training market-rate model on regular-season data…")
    model, _ = train_rs_market_model(reg, contracts, SALARY_CAP)
    rs_df = score_and_rank(reg, contracts, SALARY_CAP, model, MIN_MINUTES_RS)
    rs_meta = model_meta(model, len(rs_df))
    rs_path = OUT_DIR / "regular_season.json"
    rs_path.write_text(json.dumps({
        "season": f"{SEASON_END_YEAR-1}-{str(SEASON_END_YEAR)[-2:]}",
        "cap": SALARY_CAP,
        "meta": rs_meta,
        "players": _rows_to_records(rs_df),
    }, indent=None))
    print(f"      wrote {rs_path.relative_to(Path.cwd())} ({len(rs_df)} players, RS only)")

    # Playoffs-only ranking: same model, applied to each player's playoff stat line.
    # Answers: "If their playoff form represented their true level, what should the market pay?"
    if not playoffs.empty:
        po_df = score_and_rank(playoffs, contracts, SALARY_CAP, model, MIN_MINUTES_PLAYOFFS)
        po_meta = model_meta(model, len(po_df))
        po_path = OUT_DIR / "playoffs.json"
        po_path.write_text(json.dumps({
            "season": f"{SEASON_END_YEAR-1}-{str(SEASON_END_YEAR)[-2:]}",
            "cap": SALARY_CAP,
            "meta": po_meta,
            "players": _rows_to_records(po_df),
        }, indent=None))
        print(f"      wrote {po_path.relative_to(Path.cwd())} ({len(po_df)} players, playoffs only, ≥{MIN_MINUTES_PLAYOFFS} min)")
    else:
        po_meta = rs_meta

    print(f"\n[4/4] Fetching last {DAILY_HISTORY_DAYS} days of box scores for the calendar…")
    print(f"      (skipping dates already on disk; delete site/data/daily/*.json to refetch)")
    from datetime import timedelta as _td
    from nba_value.box_scores import fetch_box_scores_for_date

    start = date.today()
    daily_index: list[dict] = []
    for offset in range(DAILY_HISTORY_DAYS + 1):
        d = start - _td(days=offset)
        day_path = DAILY_DIR / f"{d.isoformat()}.json"
        if day_path.exists():
            existing = json.loads(day_path.read_text())
            daily_index.append({
                "date": d.isoformat(),
                "games": len(existing["games"]),
                "players": len(existing["players"]),
                "top_player": existing["players"][0]["name"] if existing["players"] else None,
                "top_surplus_dollars": existing["players"][0]["surplus_dollars"] if existing["players"] else None,
            })
            print(f"      {d.isoformat()}: cached ({len(existing['games'])} games)")
            continue

        print(f"      {d.isoformat()}: fetching…", end=" ", flush=True)
        try:
            box = fetch_box_scores_for_date(d)
        except Exception as e:  # noqa: BLE001
            print(f"\n      ! fatal: {e}")
            print(f"      ! stopping early. Already-fetched dates are saved; re-run to resume.")
            break
        if box.empty:
            print("no games")
            continue
        daily = build_daily(box, contracts, SALARY_CAP, d)
        day_path.write_text(json.dumps(daily, indent=None))
        daily_index.append({
            "date": d.isoformat(),
            "games": len(daily["games"]),
            "players": len(daily["players"]),
            "top_player": daily["players"][0]["name"] if daily["players"] else None,
            "top_surplus_dollars": daily["players"][0]["surplus_dollars"] if daily["players"] else None,
        })
        print(f"{len(daily['games'])} games · {len(daily['players'])} players · saved")

    if not daily_index:
        raise RuntimeError("No NBA games found in the lookback window")
    daily_index.sort(key=lambda r: r["date"], reverse=True)

    index_path = DAILY_DIR / "index.json"
    index_path.write_text(json.dumps({
        "dates": daily_index,
        "default": daily_index[0]["date"],
    }, indent=None))
    print(f"      wrote {len(daily_index)} per-day files and {index_path.relative_to(Path.cwd())}")

    # Backwards-compatible: keep data/daily.json pointing at the most recent day.
    most_recent = daily_index[0]["date"]
    legacy_path = OUT_DIR / "daily.json"
    legacy_path.write_text((DAILY_DIR / f"{most_recent}.json").read_text())
    print(f"      wrote {legacy_path.relative_to(Path.cwd())} (alias for {most_recent})")
    game_date = date.fromisoformat(most_recent)

    meta_path = OUT_DIR / "meta.json"
    meta_path.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "season": f"{SEASON_END_YEAR-1}-{str(SEASON_END_YEAR)[-2:]}",
        "cap": SALARY_CAP,
        "regular_season_games": REGULAR_SEASON_GAMES,
        "min_minutes_rs": MIN_MINUTES_RS,
        "min_minutes_playoffs": MIN_MINUTES_PLAYOFFS,
        "data_source": "Basketball Reference (basketball-reference.com)",
        "model": rs_meta,
        "playoffs_model": po_meta if not playoffs.empty else None,
        "daily_date": game_date.isoformat(),
    }, indent=None))
    print(f"      wrote {meta_path.relative_to(Path.cwd())}")
    print("\nDone.")


if __name__ == "__main__":
    main()
