"""The Odds API — US book median NFL spreads.

Auth is ``THE_ODDS_API_KEY`` (fallback ``ODDS_API_KEY``). The key is never
logged or printed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from .teams import odds_name_to_pbp, try_pbp_abbr

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
SPORT_KEY = "americanfootball_nfl"
REGION = "us"
MARKET = "spreads"

_USER_AGENT = "nfl-ats/0.1 (+https://github.com/WyattCurtis327/nfl_predictions)"


class OddsApiError(RuntimeError):
    """Raised when The Odds API cannot be used (missing key or HTTP failure)."""


def resolve_api_key(api_key: str | None = None) -> str:
    key = (
        (api_key or "").strip()
        or os.environ.get("THE_ODDS_API_KEY", "").strip()
        or os.environ.get("ODDS_API_KEY", "").strip()
    )
    if not key:
        raise OddsApiError(
            "Set THE_ODDS_API_KEY (or ODDS_API_KEY) in the environment. "
            "See .env.example."
        )
    return key


def median_home_spread(points: list[float]) -> float:
    """Median of US book home-team spread points. NaN if empty."""
    vals = [float(p) for p in points if p is not None and not pd.isna(p)]
    if not vals:
        return float("nan")
    return float(np.median(np.asarray(vals, dtype=float)))


def parse_spread_events(events: list[dict[str, Any]]) -> pd.DataFrame:
    """Parse Odds API event JSON into one row per game with US-median home spread."""
    rows: list[dict[str, Any]] = []
    for event in events or []:
        home_name = event.get("home_team")
        away_name = event.get("away_team")
        try:
            home_pbp = odds_name_to_pbp(home_name)
            away_pbp = odds_name_to_pbp(away_name)
        except KeyError:
            home_pbp = try_pbp_abbr(home_name)
            away_pbp = try_pbp_abbr(away_name)
            if home_pbp is None or away_pbp is None:
                continue
        home_points: list[float] = []
        n_books = 0
        for book in event.get("bookmakers") or []:
            for market in book.get("markets") or []:
                if str(market.get("key", "")).lower() != MARKET:
                    continue
                n_books += 1
                for outcome in market.get("outcomes") or []:
                    if outcome.get("name") == home_name and outcome.get("point") is not None:
                        try:
                            home_points.append(float(outcome["point"]))
                        except (TypeError, ValueError):
                            pass
        spread_home = median_home_spread(home_points)
        rows.append(
            {
                "odds_event_id": event.get("id"),
                "commence_time": event.get("commence_time"),
                "home_name": home_name,
                "away_name": away_name,
                "home_team": home_pbp,
                "away_team": away_pbp,
                "spread_home": spread_home,
                "market_home_margin": (float("nan") if pd.isna(spread_home) else -spread_home),
                "n_us_books": int(n_books),
                "n_home_points": len(home_points),
            }
        )
    cols = [
        "odds_event_id",
        "commence_time",
        "home_name",
        "away_name",
        "home_team",
        "away_team",
        "spread_home",
        "market_home_margin",
        "n_us_books",
        "n_home_points",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols)


def load_odds_json(path: str | Path) -> pd.DataFrame:
    """Load a saved Odds API response (list of events, or ``{\"data\": [...]}``)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        events = raw.get("data") or raw.get("events") or raw.get("odds") or []
    else:
        events = raw
    if not isinstance(events, list):
        raise OddsApiError("Odds JSON must be a list of events or an object with data/events.")
    return parse_spread_events(events)


def fetch_us_spreads(api_key: str | None = None, *, timeout: float = 30.0) -> pd.DataFrame:
    """GET current NFL spreads from US books and return median home spread per game."""
    key = resolve_api_key(api_key)
    try:
        resp = requests.get(
            ODDS_URL,
            params={
                "apiKey": key,
                "regions": REGION,
                "markets": MARKET,
                "oddsFormat": "american",
                "dateFormat": "iso",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OddsApiError("The Odds API request failed.") from exc
    if resp.status_code == 401:
        raise OddsApiError("The Odds API rejected the key (HTTP 401).")
    if resp.status_code == 429:
        raise OddsApiError("The Odds API rate limit was hit (HTTP 429).")
    if not resp.ok:
        raise OddsApiError(f"The Odds API returned HTTP {resp.status_code}.")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise OddsApiError("The Odds API returned non-JSON.") from exc
    if not isinstance(payload, list):
        raise OddsApiError("The Odds API returned an unexpected payload.")
    return parse_spread_events(payload)
