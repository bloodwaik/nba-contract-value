"""Live-data path: scrape Basketball Reference for advanced stats and contracts.

Why Basketball Reference: it's the only free source with both per-season
advanced stats (BPM, DWS, TS%, USG%, AST%, STL%, ORB%, etc.) and a
contracts page in a stable HTML-table format. EPM is paywalled at
Dunks & Threes — BPM is the best free substitute.

This module returns DataFrames with the same schema `nba_value.features`
and `nba_value.model` expect. It is intentionally minimal — no caching,
no retries — because users should slot it into their own ETL.

Usage:
    from nba_value.fetch import fetch_advanced_stats, fetch_contracts

    stats = fetch_advanced_stats(season_end_year=2025)
    contracts = fetch_contracts()
    roster = stats.merge(contracts, on="name", how="inner")
"""

from __future__ import annotations

import io
import time

import pandas as pd
import requests

_HEADERS = {
    # BBR blocks default urllib UA. Be a polite browser-shaped client.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


_BASE_DELAY = 6.0  # BBR's public guidance is "be polite"; faster than this gets 429'd in bursts


def _get(url: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries + 1):
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        if resp.status_code == 429:
            wait = 60 * (2 ** attempt)  # 60s, 120s, 240s
            print(f"  ! 429 from BBR — backing off {wait}s (attempt {attempt + 1}/{max_retries + 1})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        time.sleep(_BASE_DELAY)
        return resp.text
    raise RuntimeError(f"BBR kept returning 429 for {url} after {max_retries + 1} attempts")


def fetch_advanced_stats(season_end_year: int, playoffs: bool = False) -> pd.DataFrame:
    """Pull per-player advanced stats for a season.
    `season_end_year=2025` returns the 2024-25 season.
    Set `playoffs=True` to pull the postseason advanced table instead.
    """
    if playoffs:
        url = f"https://www.basketball-reference.com/playoffs/NBA_{season_end_year}_advanced.html"
    else:
        url = f"https://www.basketball-reference.com/leagues/NBA_{season_end_year}_advanced.html"
    html = _get(url)
    # Some BBR tables are inside HTML comments to defeat naive scrapers.
    html = html.replace("<!--", "").replace("-->", "")
    # Regular-season page uses id="advanced"; playoff page uses id="advanced_stats".
    table_id = "advanced_stats" if playoffs else "advanced"
    tables = pd.read_html(io.StringIO(html), attrs={"id": table_id})
    df = tables[0]
    df = df[df["Player"] != "Player"]  # drop repeated header rows
    df = df.rename(columns={
        "Player": "name",
        "Age": "age",
        "Pos": "position",
        "Tm": "team",
        "Team": "team",
        "G": "games_played",
        "MP": "total_minutes",
        "TS%": "ts_pct",
        "USG%": "usg_pct",
        "AST%": "ast_pct",
        "STL%": "stl_pct",
        "ORB%": "orb_pct",
        "BPM": "bpm",
        "DWS": "dws",
        "VORP": "vorp",
    })
    if "team" not in df.columns:
        df["team"] = ""
    keep = [
        "name", "age", "position", "team", "games_played", "total_minutes",
        "ts_pct", "usg_pct", "ast_pct", "stl_pct", "orb_pct",
        "bpm", "dws", "vorp",
    ]
    df = df[keep].copy()
    for c in keep:
        if c in ("name", "position", "team"):
            continue
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Players traded mid-season appear multiple times; keep the "TOT" row
    # (BBR sorts it first). Drop the dupes.
    df = df.drop_duplicates(subset=["name"], keep="first")
    return df.dropna(subset=["bpm", "total_minutes"]).reset_index(drop=True)


def combine_regular_and_playoffs(reg: pd.DataFrame, playoffs: pd.DataFrame) -> pd.DataFrame:
    """Merge regular-season and playoff advanced rows into a single per-player
    line of "value created this year." Rate stats (BPM, TS%, USG%, AST%, STL%,
    ORB%, DWS, VORP) are minute-weighted; games_played and total_minutes are
    summed. Players who didn't make the playoffs keep their regular-season line.
    """
    rate_cols = ["bpm", "ts_pct", "usg_pct", "ast_pct", "stl_pct", "orb_pct", "dws", "vorp"]
    sum_cols = ["games_played", "total_minutes"]
    meta_cols = ["age", "position", "team"]

    p = playoffs.set_index("name")
    r = reg.set_index("name")
    rows = []
    for name, rr in r.iterrows():
        if name in p.index:
            pp = p.loc[name]
            if isinstance(pp, pd.DataFrame):  # rare duplicate name collision
                pp = pp.iloc[0]
            reg_min = max(rr["total_minutes"], 1)
            pl_min = max(pp["total_minutes"], 1)
            tot_min = reg_min + pl_min
            row = {"name": name}
            for c in meta_cols:
                row[c] = rr[c]
            for c in rate_cols:
                if pd.isna(rr.get(c)) and pd.isna(pp.get(c)):
                    row[c] = float("nan")
                else:
                    rv = rr.get(c, 0.0) or 0.0
                    pv = pp.get(c, 0.0) or 0.0
                    row[c] = (rv * reg_min + pv * pl_min) / tot_min
            for c in sum_cols:
                row[c] = (rr.get(c, 0) or 0) + (pp.get(c, 0) or 0)
            rows.append(row)
        else:
            rows.append({"name": name, **{c: rr.get(c) for c in meta_cols + rate_cols + sum_cols}})
    return pd.DataFrame(rows)


def fetch_contracts() -> pd.DataFrame:
    """Pull the active-contracts table from BBR.
    Returns name + team + this season's salary.
    """
    url = "https://www.basketball-reference.com/contracts/players.html"
    html = _get(url).replace("<!--", "").replace("-->", "")
    tables = pd.read_html(io.StringIO(html), attrs={"id": "player-contracts"})
    df = tables[0]
    df.columns = [c[1] if isinstance(c, tuple) else c for c in df.columns]
    df = df.rename(columns={"Player": "name", "Tm": "contract_team", "Team": "contract_team"})
    season_cols = [c for c in df.columns if c.startswith("20") and "-" in c]
    if not season_cols:
        raise RuntimeError("Could not find a season salary column on the BBR contracts page")
    current_col = season_cols[0]
    keep_cols = ["name", current_col]
    if "contract_team" in df.columns:
        keep_cols.insert(1, "contract_team")
    df = df[keep_cols].rename(columns={current_col: "salary"})
    df["salary"] = (
        df["salary"].astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
    )
    df["salary"] = pd.to_numeric(df["salary"], errors="coerce")
    return df.dropna(subset=["salary"]).reset_index(drop=True)
