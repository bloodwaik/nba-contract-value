"""Synthetic but realistic demo data so the pipeline runs end-to-end without
network access. All stats are drawn from distributions calibrated to public
NBA averages; "names" are archetypes, not real players. The point is to
demonstrate the algorithm — see `fetch.py` for the live-data path.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# Salary caps by season (in millions of dollars), from publicly-reported figures.
SEASON_CAPS_M: dict[str, float] = {
    "2019-20": 109.140,
    "2020-21": 109.140,
    "2021-22": 112.414,
    "2022-23": 123.655,
    "2023-24": 136.021,
    "2024-25": 140.588,
    "2025-26": 154.647,
}

_TRAINING_SEASONS = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24"]
_CURRENT_SEASON = "2025-26"

POSITIONS = ["PG", "SG", "SF", "PF", "C"]


def _draw_player_stats(rng: np.random.Generator, n: int) -> pd.DataFrame:
    """Draw `n` players with correlated, realistic per-season stats."""
    age = rng.integers(19, 39, size=n).astype(float)

    # Underlying latent "skill" drives BPM, TS%, USG%, minutes.
    # Most players cluster around replacement level; stars are a long tail.
    skill = rng.normal(0, 1, size=n)
    skill += rng.choice([0, 0, 0, 2.5], size=n, p=[0.55, 0.25, 0.15, 0.05])  # star tail

    bpm = -2.0 + 2.8 * skill + rng.normal(0, 1.0, size=n)
    bpm = np.clip(bpm, -8, 12)

    ts_pct = 0.54 + 0.025 * skill + rng.normal(0, 0.03, size=n)
    ts_pct = np.clip(ts_pct, 0.40, 0.70)

    usg_pct = 18 + 4 * skill + rng.normal(0, 3, size=n)
    usg_pct = np.clip(usg_pct, 8, 38)

    # Role splits — guards distribute, bigs rebound, wings somewhere between.
    position = rng.choice(POSITIONS, size=n, p=[0.22, 0.22, 0.22, 0.18, 0.16])
    is_g = np.isin(position, ["PG", "SG"])
    is_c = position == "C"

    ast_pct = np.where(is_g, 22, np.where(is_c, 8, 12)) + 5 * skill + rng.normal(0, 4, size=n)
    ast_pct = np.clip(ast_pct, 2, 45)

    stl_pct = 1.4 + 0.4 * skill + rng.normal(0, 0.4, size=n)
    stl_pct = np.clip(stl_pct, 0.3, 4.0)

    orb_pct = np.where(is_c, 9, np.where(is_g, 2.5, 5)) + rng.normal(0, 1.5, size=n)
    orb_pct = np.clip(orb_pct, 0.5, 16)

    dws = np.clip(1.5 + 0.9 * skill + rng.normal(0, 0.8, size=n), 0, 7)

    # Availability — better players generally play more, but injuries scatter it.
    games_played = np.clip(rng.normal(58 + 6 * skill, 12, size=n), 5, 82).round()
    minutes_per_game = np.clip(rng.normal(24 + 4 * skill, 4, size=n), 8, 38)
    total_minutes = (games_played * minutes_per_game).round()

    return pd.DataFrame({
        "age": age,
        "position": position,
        "bpm": bpm,
        "dws": dws,
        "ts_pct": ts_pct,
        "usg_pct": usg_pct,
        "ast_pct": ast_pct,
        "stl_pct": stl_pct,
        "orb_pct": orb_pct,
        "games_played": games_played,
        "total_minutes": total_minutes,
    })


def _true_market_cap_pct(df: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    """The 'true' market function the regression should recover.

    Built to roughly match league-observed dynamics:
      - BPM dominates (~7% of cap per BPM point in the linear region)
      - Defence (DWS) gets paid, but less than offence
      - Volume matters (high USG + high TS% = expensive)
      - Steals weighted heavily relative to box-score footprint
      - Aging curve peaks ~27, declines after 30
      - Centres earn slightly less per BPM (positional market discount)
    """
    age = df["age"].to_numpy()
    age_effect = -0.005 * (age - 27) ** 2 + 0.015  # peak near 27

    base = (
        0.02                                  # league-min intercept
        + 0.015 * df["bpm"].to_numpy()        # impact
        + 0.005 * df["dws"].to_numpy()        # defence
        + 0.20  * (df["ts_pct"].to_numpy() - 0.54)
        + 0.002 * (df["usg_pct"].to_numpy() - 18)
        + 0.0008 * (df["ast_pct"].to_numpy() - 12)
        + 0.012 * (df["stl_pct"].to_numpy() - 1.4)
        + 0.001 * (df["orb_pct"].to_numpy() - 4)
        + 0.000015 * (df["total_minutes"].to_numpy() - 1400)
        + age_effect
    )
    base += np.where(df["position"].to_numpy() == "C", -0.01, 0)

    # Real signings are noisy: GMs reach, players take discounts to win, etc.
    noise = rng.normal(0, 0.025, size=len(df))
    return np.clip(base + noise, 0.012, 0.35)


def make_training_signings(n_per_season: int = 100, seed: int = 7) -> pd.DataFrame:
    """Generate a multi-season training set of (prior-season stats) -> cap_pct."""
    rng = np.random.default_rng(seed)
    frames = []
    for season in _TRAINING_SEASONS:
        df = _draw_player_stats(rng, n_per_season)
        df["season"] = season
        df["season_cap"] = SEASON_CAPS_M[season] * 1_000_000
        df["cap_pct"] = _true_market_cap_pct(df, rng)
        df["salary"] = df["cap_pct"] * df["season_cap"]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def make_current_roster(n: int = 120, seed: int = 11) -> pd.DataFrame:
    """Generate a current-roster snapshot with realistic mispricings.

    Mispricings come from two structural sources we *want* the model to find:
      - Rookie-scale contracts: high-skill players locked in cheap (huge surplus)
      - Overpaid veterans: declining production on long max deals (negative surplus)
    Plus garden-variety noise around market.
    """
    rng = np.random.default_rng(seed)
    df = _draw_player_stats(rng, n)
    df["season"] = _CURRENT_SEASON
    df["season_cap"] = SEASON_CAPS_M[_CURRENT_SEASON] * 1_000_000

    true_market = _true_market_cap_pct(df, rng)

    # Contract structure: rookie deal, mid-deal, max, vet-min, etc.
    contract_type = rng.choice(
        ["rookie", "vet_min", "fair_deal", "overpay", "max"],
        size=n,
        p=[0.18, 0.10, 0.45, 0.15, 0.12],
    )

    actual_cap_pct = np.where(
        contract_type == "rookie",
        np.clip(0.02 + 0.005 * rng.normal(0, 1, n), 0.012, 0.06),
        np.where(
            contract_type == "vet_min",
            np.clip(0.015 + 0.003 * rng.normal(0, 1, n), 0.012, 0.025),
            np.where(
                contract_type == "fair_deal",
                np.clip(true_market + rng.normal(0, 0.015, n), 0.012, 0.35),
                np.where(
                    contract_type == "overpay",
                    np.clip(true_market + rng.uniform(0.04, 0.10, n), 0.012, 0.35),
                    # max — only meaningful if the player is actually good
                    np.clip(np.maximum(true_market, 0.25) + rng.normal(0, 0.02, n), 0.20, 0.35),
                ),
            ),
        ),
    )

    df["contract_type"] = contract_type
    df["cap_pct"] = actual_cap_pct
    df["salary"] = df["cap_pct"] * df["season_cap"]

    # Give players archetype names so the output is interpretable
    df.insert(0, "name", [_archetype_name(row, i) for i, row in df.iterrows()])
    return df


def _archetype_name(row: pd.Series, i: int) -> str:
    age = row["age"]
    pos = row["position"]
    bpm = row["bpm"]
    role = "Star" if bpm >= 4 else "Starter" if bpm >= 0.5 else "Rotation" if bpm >= -2 else "Bench"
    bucket = "Young" if age < 25 else "Prime" if age < 31 else "Vet"
    return f"{bucket} {pos} {role} #{i:03d}"


def current_season_cap() -> float:
    return SEASON_CAPS_M[_CURRENT_SEASON] * 1_000_000
