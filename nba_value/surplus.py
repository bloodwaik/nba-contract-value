"""Apply a trained market-rate model to a current roster and rank surplus value."""

from __future__ import annotations

import pandas as pd

from .features import TARGET, dollarize
from .model import TrainedModel


def compute_surplus(
    roster: pd.DataFrame,
    model: TrainedModel,
    current_season_cap: float,
) -> pd.DataFrame:
    """For each player on `roster`, predict expected_cap_pct and compare to actual.

    Returns the roster with these added columns:
      - expected_cap_pct : what the market should pay them given their stats
      - actual_cap_pct   : their real share of this season's cap
      - surplus_cap_pct  : expected - actual (positive = team profit)
      - expected_salary  : expected_cap_pct * season_cap, in dollars
      - surplus_dollars  : the same delta, in dollars
    """
    df = roster.copy()

    if "actual_cap_pct" not in df.columns:
        if {"salary", "season_cap"}.issubset(df.columns):
            df["actual_cap_pct"] = df["salary"] / df["season_cap"]
        elif TARGET in df.columns:
            df["actual_cap_pct"] = df[TARGET]
        else:
            raise ValueError("Roster needs salary + season_cap (or actual_cap_pct).")

    df["expected_cap_pct"] = model.predict(df)
    df["surplus_cap_pct"] = df["expected_cap_pct"] - df["actual_cap_pct"]
    df["expected_salary"] = dollarize(df["expected_cap_pct"], current_season_cap)
    df["surplus_dollars"] = dollarize(df["surplus_cap_pct"], current_season_cap)

    return df


def rank_by_surplus(df: pd.DataFrame, top_n: int = 15) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (best_bargains, worst_overpays) — the heads and tails of the league."""
    cols = [
        c for c in (
            "name", "age", "position", "bpm", "total_minutes",
            "actual_cap_pct", "expected_cap_pct", "surplus_cap_pct",
            "expected_salary", "surplus_dollars",
        ) if c in df.columns
    ]
    sorted_df = df.sort_values("surplus_cap_pct", ascending=False)
    return sorted_df.head(top_n)[cols], sorted_df.tail(top_n)[cols].iloc[::-1]
