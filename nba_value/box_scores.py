"""Daily box-score fetcher.

Pulls all games from a target date on Basketball Reference and returns
per-player box-score lines (PTS, AST, REB, STL, BLK, TOV, MIN, GmSc, …)
so the daily-value page can compute single-game surplus.

Game Score (Hollinger) is BBR's per-game catch-all box score metric:
    GmSc = PTS + 0.4*FG - 0.7*FGA - 0.4*(FTA-FT)
         + 0.7*ORB + 0.3*DRB + STL + 0.7*AST + 0.7*BLK - 0.4*PF - TOV

A starter-level Game Score is ~12-15; a star night is 25+. The daily
page uses GmSc as the single-game production index.
"""

from __future__ import annotations

import io
import re
from datetime import date, timedelta
from typing import Iterable

import pandas as pd

from .fetch import _get


_BBR_BASE = "https://www.basketball-reference.com"


def list_games_for_date(d: date) -> list[dict]:
    """Return a list of {boxscore_url, away, home} dicts for games played on `d`.
    Empty list if no NBA games that day.
    """
    url = f"{_BBR_BASE}/boxscores/?month={d.month}&day={d.day}&year={d.year}"
    html = _get(url).replace("<!--", "").replace("-->", "")
    # Boxscore links look like /boxscores/202605100MIA.html
    pattern = re.compile(r'href="(/boxscores/\d{9}[A-Z]{3}\.html)"')
    seen = set()
    games = []
    for m in pattern.finditer(html):
        href = m.group(1)
        if href in seen:
            continue
        seen.add(href)
        # The 3-letter code at the end of the URL is the HOME team.
        home_code = href[-8:-5]
        games.append({"url": _BBR_BASE + href, "home": home_code})
    return games


def fetch_boxscore(url: str) -> pd.DataFrame:
    """Fetch a single boxscore page and return a tidy per-player DataFrame.
    Columns: name, team, opp, minutes, fg, fga, three, threea, ft, fta,
             orb, drb, trb, ast, stl, blk, tov, pf, pts, gmsc, plus_minus.
    """
    html = _get(url).replace("<!--", "").replace("-->", "")
    # Box tables are id="box-XXX-game-basic"
    table_ids = re.findall(r'id="(box-[A-Z]{3}-game-basic)"', html)
    if len(table_ids) != 2:
        raise RuntimeError(f"Expected 2 team box tables at {url}, found {len(table_ids)}")
    frames = []
    teams = [tid.split("-")[1] for tid in table_ids]
    for team_code, tid in zip(teams, table_ids):
        df = pd.read_html(io.StringIO(html), attrs={"id": tid})[0]
        # Two-row header — flatten
        df.columns = [c[1] if isinstance(c, tuple) else c for c in df.columns]
        df = df.rename(columns={
            "Starters": "name", "MP": "minutes", "FG": "fg", "FGA": "fga",
            "3P": "three", "3PA": "threea", "FT": "ft", "FTA": "fta",
            "ORB": "orb", "DRB": "drb", "TRB": "trb", "AST": "ast",
            "STL": "stl", "BLK": "blk", "TOV": "tov", "PF": "pf",
            "PTS": "pts", "GmSc": "gmsc", "+/-": "plus_minus",
        })
        df = df[~df["name"].isin(["Reserves", "Team Totals", "Starters"])]
        df = df[~df["minutes"].astype(str).str.contains("Did Not", na=False)]
        df = df[~df["minutes"].astype(str).str.contains("Not With", na=False)]
        df = df[~df["minutes"].astype(str).str.contains("Player Suspended", na=False)]
        df["team"] = team_code
        df["opp"] = [t for t in teams if t != team_code][0]
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)

    # Parse "MM:SS" minutes -> float minutes
    def _parse_min(x: object) -> float:
        s = str(x)
        if ":" in s:
            mm, ss = s.split(":")
            try:
                return int(mm) + int(ss) / 60.0
            except ValueError:
                return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0
    out["minutes"] = out["minutes"].map(_parse_min)

    numeric_cols = [
        "fg", "fga", "three", "threea", "ft", "fta", "orb", "drb", "trb",
        "ast", "stl", "blk", "tov", "pf", "pts", "gmsc", "plus_minus",
    ]
    for c in numeric_cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    # Drop the few minutes==0 lines (inactive)
    out = out[out["minutes"] > 0].reset_index(drop=True)
    return out


def fetch_box_scores_for_date(d: date) -> pd.DataFrame:
    """Fetch every player box-score line from `d`. Returns empty DataFrame if no games."""
    games = list_games_for_date(d)
    if not games:
        return pd.DataFrame()
    frames = []
    for g in games:
        try:
            frames.append(fetch_boxscore(g["url"]))
        except Exception as e:  # noqa: BLE001
            print(f"  ! could not parse {g['url']}: {e}")
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["game_date"] = d.isoformat()
    return df


def find_most_recent_game_date(start: date, max_lookback_days: int = 14) -> tuple[date, pd.DataFrame]:
    """Walk backward from `start` until we find a date with at least one game.
    Returns (date_found, boxscore_dataframe).
    Raises RuntimeError if nothing found within the window.
    """
    for offset in range(max_lookback_days + 1):
        d = start - timedelta(days=offset)
        print(f"  checking {d.isoformat()}…")
        df = fetch_box_scores_for_date(d)
        if not df.empty:
            return d, df
    raise RuntimeError(
        f"No NBA games found between {start - timedelta(days=max_lookback_days)} and {start}"
    )


def fetch_daily_history(start: date, days_back: int) -> list[tuple[date, pd.DataFrame]]:
    """Walk backward `days_back` days from `start`, returning every date with
    at least one game. Use this to populate the calendar on the daily page.
    Rate-limited by `_get` (~1 req/sec), so 25 days ≈ 2 minutes.
    """
    results: list[tuple[date, pd.DataFrame]] = []
    for offset in range(days_back + 1):
        d = start - timedelta(days=offset)
        print(f"  fetching {d.isoformat()}…", end=" ", flush=True)
        df = fetch_box_scores_for_date(d)
        if df.empty:
            print("no games")
        else:
            print(f"{len(df)} player lines")
            results.append((d, df))
    return results
