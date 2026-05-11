"""Feature engineering for the contract value model.

The model predicts `cap_pct` (a player's share of the league salary cap)
from on-court production, availability, and demographic features. Keeping
the target on the cap-percent scale (rather than raw dollars) means a
2018 deal and a 2026 deal are directly comparable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# Production / efficiency / hidden-value stats that get fed to the model.
# Order matters: it is the canonical schema the rest of the package assumes.
PRODUCTION_FEATURES: list[str] = [
    "bpm",            # Box Plus/Minus — free EPM proxy
    "dws",            # Defensive Win Shares — anchor for defenders
    "ts_pct",         # True Shooting %
    "usg_pct",        # Usage Rate
    "ast_pct",        # Assist %
    "stl_pct",        # Steal %  (per Silver / Bayer, weighted heavily by impact)
    "orb_pct",        # Offensive Rebound %
]

AVAILABILITY_FEATURES: list[str] = [
    "total_minutes",  # Volume of floor time — penalises load-managed stars
    "games_played",
]

DEMOGRAPHIC_FEATURES: list[str] = [
    "age",
    "age_sq",         # Lets the model bend an aging curve
]

POSITION_FEATURES: list[str] = [
    "pos_G",
    "pos_F",
    "pos_C",
]

ALL_FEATURES: list[str] = (
    PRODUCTION_FEATURES
    + AVAILABILITY_FEATURES
    + DEMOGRAPHIC_FEATURES
    + POSITION_FEATURES
)

TARGET: str = "cap_pct"


def add_engineered_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived columns the model expects: age_sq, position one-hots,
    and cap_pct if a salary + season_cap are present."""
    out = df.copy()

    if "age" in out.columns and "age_sq" not in out.columns:
        out["age_sq"] = out["age"] ** 2

    if "position" in out.columns:
        # Bucket the standard 5 positions into G / F / C. The model only
        # needs to know the "market" for shot-creators, wings, and bigs —
        # not whether someone is technically a SG vs SF.
        pos_map = {"PG": "G", "SG": "G", "SF": "F", "PF": "F", "C": "C"}
        bucket = out["position"].map(pos_map).fillna("F")
        for p in ("G", "F", "C"):
            out[f"pos_{p}"] = (bucket == p).astype(int)

    if "salary" in out.columns and "season_cap" in out.columns and TARGET not in out.columns:
        out[TARGET] = out["salary"] / out["season_cap"]

    return out


def build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Return X with exactly ALL_FEATURES columns, in order, ready for sklearn."""
    df = add_engineered_columns(df)
    missing = [c for c in ALL_FEATURES if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required feature columns: {missing}")
    return df[ALL_FEATURES].astype(float)


def dollarize(cap_pct: float | np.ndarray | pd.Series, season_cap: float) -> float | np.ndarray | pd.Series:
    """Convert a cap-percentage back into real dollars for the given season."""
    return cap_pct * season_cap
