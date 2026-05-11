# NBA Contract Surplus-Value Model

A Python implementation of the algorithm described in the project brief:
isolate **surplus value** — the gap between what an NBA player produces
on the floor and what their contract costs against the cap.

## The algorithm in one paragraph

For every contract that's been signed in the last several seasons,
record (a) the player's prior-season stats and (b) the share of the
salary cap their new deal consumed (`cap_pct = salary / season_cap`).
Fit a regression: `cap_pct ~ stats + age + position`. The model now
encodes what the open market actually pays for a unit of production.
Apply it to current rosters: `expected_cap_pct − actual_cap_pct =
surplus`. Multiply by this year's cap to dollarise.

## Layout

```
nba_value/
  features.py   Canonical feature schema + cap_pct/age engineering
  model.py      Ridge regression on standardised features, with CV
  surplus.py    Apply trained model to a roster, rank bargains vs overpays
  demo.py       Synthetic but realistic training/roster data
  fetch.py      Live Basketball Reference scrapers (real-data path)
run.py          CLI: `python run.py` runs end-to-end
```

## Features the model uses

| Bucket            | Stats                                                      | Why |
|-------------------|------------------------------------------------------------|-----|
| Impact            | `bpm`, `dws`                                               | BPM is the free EPM substitute; DWS anchors defenders |
| Efficiency/volume | `ts_pct`, `usg_pct`, `ast_pct`                             | High TS% × high USG% is the most expensive thing in the league |
| Hidden value      | `stl_pct`, `orb_pct`                                       | Steals are weighted ~9× points in some impact models |
| Availability      | `total_minutes`, `games_played`                            | Penalises load-managed stars |
| Demographics      | `age`, `age_sq`, `pos_G`/`pos_F`/`pos_C`                   | Aging curve + positional market |

Target: `cap_pct` (salary divided by that season's salary cap). Keeping
the target on a cap-share scale means a $30M deal in 2018 and a $30M
deal in 2026 are directly comparable.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the synthetic demo

```bash
python run.py
```

Output: learned coefficients (per standard deviation of each feature),
top-15 bargains, and bottom-15 overpays. The synthetic dataset is
seeded with a known true market function plus realistic noise — the
regression should clearly recover BPM, TS%, STL% as the highest-paying
inputs, and surface rookie-deal stars + max-deal overpays at the
extremes of the surplus distribution.

## Run on live data

```bash
python run.py --fetch 2025
```

This scrapes Basketball Reference's `advanced.html` and `contracts/players.html`
for the 2024-25 season. BBR rate-limits at ~1 req/sec; the fetcher honours
that. EPM is paywalled at Dunks & Threes, so BPM is used as the free
substitute — if you have an EPM source, drop it into `features.py` and
the rest of the pipeline is unchanged.

## The website

`site/` is a static visualization layer (HTML + Tailwind-style custom CSS + JS
modules + Chart.js + DataTables). It reads JSON produced by
`build_site_data.py`.

```bash
# 1. Regenerate the data (regular-season, playoffs, last night's box scores)
python build_site_data.py

# 2. Serve the site
cd site && python3 -m http.server 8765
# then open http://localhost:8765
```

Pages:
- **Overview** — hero stats, biggest bargain & overpay of the season
- **Regular Season** — full 2025-26 RS rankings, filters, surplus histogram
- **Playoffs** — RS + playoff-blended rankings (minute-weighted)
- **Daily** — last night's box scores, single-game $ earned vs paid
- **Algorithm** — five-step recipe, learned coefficients, model caveats

## Extending the model

- **Aging curve**: currently a quadratic. Replace with a non-parametric
  spline if you have enough signings to support it.
- **Injury penalty**: add a `games_missed_last_3yrs` feature for risk
  aversion. The brief asked whether to do this — it's a one-line addition
  in `features.py`.
- **Position market**: the position dummies treat the market as
  positionally uniform within G/F/C. Interact `position × bpm` if you
  believe a +3 BPM centre earns less than a +3 BPM guard.
- **Train on signings only**: the demo trains on prior-season → cap_pct
  for *all* players. The cleanest version trains only on the
  free-agent/extension *moments* — that's the live market signal. The
  pipeline already supports this; you just feed a different DataFrame
  into `train_market_rate_model`.
