"""End-to-end demo: train a market-rate model on historical signings,
apply it to a current roster, and rank surplus value.

    python run.py              # synthetic demo (no network)
    python run.py --fetch 2025 # live Basketball Reference data (season_end_year)
"""

from __future__ import annotations

import argparse

import pandas as pd

from nba_value.demo import current_season_cap, make_current_roster, make_training_signings
from nba_value.features import add_engineered_columns
from nba_value.model import train_market_rate_model
from nba_value.surplus import compute_surplus, rank_by_surplus


def _fmt_money(x: float) -> str:
    return f"${x/1_000_000:>6.2f}M"


def _fmt_pct(x: float) -> str:
    return f"{x*100:>5.1f}%"


def print_coefficients(coefs: pd.Series) -> None:
    print("\n=== Learned market coefficients (per 1 standard deviation of feature) ===")
    print("Positive = market pays more for this stat; negative = market discounts it.\n")
    for name, value in coefs.items():
        bar = "█" * max(1, int(abs(value) * 400))
        sign = "+" if value >= 0 else "-"
        print(f"  {name:<14} {sign} {abs(value)*100:>5.2f} cap-% / sd  {bar}")


def print_ranking(title: str, df: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    print(
        f"  {'Player':<32} {'Age':>3} {'Pos':>3} {'BPM':>6} "
        f"{'Min':>5} {'Paid':>6} {'Worth':>6} {'Surplus':>8} {'$Δ':>9}"
    )
    for _, r in df.iterrows():
        print(
            f"  {r['name']:<32} "
            f"{int(r['age']):>3} {r['position']:>3} "
            f"{r['bpm']:>6.1f} {int(r['total_minutes']):>5} "
            f"{_fmt_pct(r['actual_cap_pct'])} "
            f"{_fmt_pct(r['expected_cap_pct'])} "
            f"{_fmt_pct(r['surplus_cap_pct'])} "
            f"{_fmt_money(r['surplus_dollars'])}"
        )


def run_demo() -> None:
    print("Generating synthetic training set (5 seasons of signings)…")
    training = make_training_signings()
    print(f"  trained on {len(training):,} signings across "
          f"{training['season'].nunique()} seasons")

    print("\nFitting market-rate Ridge regression on (prior-season stats) -> cap_pct…")
    model = train_market_rate_model(training)
    print(f"  in-sample R² = {model.in_sample_r2:.3f}   "
          f"in-sample MAE = {model.in_sample_mae*100:.2f} cap-%   "
          f"5-fold CV MAE = {model.cv_mae*100:.2f} cap-%")

    print_coefficients(model.coefficients)

    print("\nGenerating current-season roster (mix of rookie deals, fair deals, max, overpays)…")
    roster = make_current_roster()
    cap = current_season_cap()
    print(f"  {len(roster)} players on a ${cap/1_000_000:.1f}M cap")

    scored = compute_surplus(roster, model, current_season_cap=cap)
    bargains, overpays = rank_by_surplus(scored, top_n=15)

    print_ranking("Top 15 surplus-value contracts (biggest bargains)", bargains)
    print_ranking("Bottom 15 surplus-value contracts (worst overpays)", overpays)

    print("\nWhat to read here:")
    print("  • 'Paid'    = the player's actual share of the cap this season.")
    print("  • 'Worth'   = what the trained market function says they should earn.")
    print("  • 'Surplus' = Worth − Paid. Positive = team profit; negative = team loss.")
    print("  • '$Δ'      = the same delta in dollars, against this year's cap.")


def run_fetch(season_end_year: int) -> None:
    from nba_value.fetch import fetch_advanced_stats, fetch_contracts

    print(f"Fetching advanced stats for season ending {season_end_year}…")
    stats = fetch_advanced_stats(season_end_year)
    print(f"  got {len(stats)} player rows")

    print("Fetching contracts…")
    contracts = fetch_contracts()
    print(f"  got {len(contracts)} contract rows")

    merged = stats.merge(contracts, on="name", how="inner")
    print(f"  matched {len(merged)} players with both stats and a contract")

    # Use the current-year cap published by the NBA.
    # 2024-25: $140.588M ; 2025-26: $154.647M
    season_cap_map = {2025: 140_588_000, 2026: 154_647_000}
    cap = season_cap_map.get(season_end_year)
    if cap is None:
        raise SystemExit(
            f"Add the salary cap for season ending {season_end_year} to season_cap_map in run.py"
        )
    merged["season_cap"] = cap
    merged = add_engineered_columns(merged)
    # The training pass needs reasonably-stable signal — drop players with
    # tiny samples that BPM/usage become unstable on.
    trainable = merged[merged["total_minutes"] >= 500].copy()

    print(f"\nTraining on {len(trainable)} players (≥500 min) — proof-of-concept "
          "(in production you'd train on multiple prior seasons of signings).")
    model = train_market_rate_model(trainable)
    print(f"  in-sample R² = {model.in_sample_r2:.3f}   "
          f"5-fold CV MAE = {model.cv_mae*100:.2f} cap-%")

    print_coefficients(model.coefficients)
    scored = compute_surplus(merged, model, current_season_cap=cap)
    bargains, overpays = rank_by_surplus(scored, top_n=15)
    print_ranking("Top 15 surplus-value contracts", bargains)
    print_ranking("Bottom 15 surplus-value contracts", overpays)


def main() -> None:
    parser = argparse.ArgumentParser(description="NBA contract surplus-value model")
    parser.add_argument(
        "--fetch", type=int, metavar="SEASON_END_YEAR",
        help="Pull live data from Basketball Reference instead of running the synthetic demo",
    )
    args = parser.parse_args()
    if args.fetch:
        run_fetch(args.fetch)
    else:
        run_demo()


if __name__ == "__main__":
    main()
