"""EPA windows and home-margin conversion.

PBP filter: play_type in {pass, run}, qb_kneel==0, qb_spike==0, epa not null.

Window (n = completed REG games this season for the team, before the slate week):
  n < 6  → last 12 REG games (may cross seasons)
  n >= 6 → 50% last-8 + 50% last-k this season, k = min(17, n)

``epa_home = (home_net_epa - away_net_epa) * plays_per_game + HFA``
HFA = 2.25 at home, 0 on international/neutral sites.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .teams import pbp_abbr, try_pbp_abbr

PLAYS_PER_GAME = 65.0
HFA_HOME = 2.25
HFA_NEUTRAL = 0.0

# Stadium / city tokens that mark NFL International Series (neutral HFA).
_INTERNATIONAL_HINTS = (
    "london",
    "wembley",
    "tottenham",
    "twickenham",
    "munich",
    "allianz arena",
    "frankfurt",
    "deutsche bank",
    "berlin",
    "olympiastadion",
    "mexico",
    "azteca",
    "sao paulo",
    "são paulo",
    "corinthians",
    "dublin",
    "croke",
    "madrid",
    "bernabeu",
    "bernabéu",
    "melbourne",
    "australia",
)


def filter_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    """Keep EPA-eligible offensive plays."""
    df = pbp
    if df.empty:
        return df.copy()
    if "play_type" not in df.columns or "epa" not in df.columns:
        return df.iloc[0:0].copy()
    play_type = df["play_type"].astype(str).str.lower()
    type_ok = play_type.isin(["pass", "run"])
    kneel = pd.to_numeric(df.get("qb_kneel", 0), errors="coerce").fillna(0)
    spike = pd.to_numeric(df.get("qb_spike", 0), errors="coerce").fillna(0)
    epa_ok = df["epa"].notna() if "epa" in df.columns else False
    out = df.loc[type_ok & (kneel == 0) & (spike == 0) & epa_ok].copy()
    if "season_type" in out.columns:
        out = out[out["season_type"].astype(str).str.upper() == "REG"]
    return out


def is_neutral_site(row: pd.Series) -> bool:
    loc = str(row.get("location") or "").strip().casefold()
    if loc == "neutral":
        return True
    blob = " ".join(
        str(row.get(c) or "")
        for c in ("stadium", "stadium_id", "site", "city", "location")
    ).casefold()
    return any(h in blob for h in _INTERNATIONAL_HINTS)


def home_field_advantage(row: pd.Series) -> float:
    return HFA_NEUTRAL if is_neutral_site(row) else HFA_HOME


def _as_int(value: object, default: int = 0) -> int:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def team_reg_history(
    games: pd.DataFrame,
    team: str,
    *,
    season: int,
    week: int,
) -> pd.DataFrame:
    """Completed REG games for ``team`` strictly before (season, week), oldest first."""
    team_pbp = pbp_abbr(team)
    g = games.copy()
    if "game_type" in g.columns:
        g = g[g["game_type"].astype(str).str.upper() == "REG"]
    elif "season_type" in g.columns:
        g = g[g["season_type"].astype(str).str.upper() == "REG"]
    g = g[g["home_score"].notna() & g["away_score"].notna()]
    def _code(x: object) -> str:
        if pd.isna(x):
            return ""
        got = try_pbp_abbr(str(x))
        return got or ""

    home = g["home_team"].map(_code)
    away = g["away_team"].map(_code)
    g = g[(home == team_pbp) | (away == team_pbp)].copy()
    g["_season"] = pd.to_numeric(g["season"], errors="coerce").fillna(0).astype(int)
    g["_week"] = pd.to_numeric(g["week"], errors="coerce").fillna(0).astype(int)
    before = (g["_season"] < int(season)) | (
        (g["_season"] == int(season)) & (g["_week"] < int(week))
    )
    g = g.loc[before]
    return g.sort_values(["_season", "_week", "game_id"], kind="mergesort").reset_index(drop=True)


def this_season_n(history: pd.DataFrame, season: int) -> int:
    if history.empty:
        return 0
    col = "_season" if "_season" in history.columns else "season"
    return int((pd.to_numeric(history[col], errors="coerce") == int(season)).sum())


def select_window_game_ids(
    history: pd.DataFrame,
    *,
    season: int,
    n: int | None = None,
) -> tuple[list[str], list[str] | None, str, int]:
    """Return (primary_ids, blend_ids_or_None, label, n).

    When n < 6, only ``primary_ids`` (last 12) is used.
    When n >= 6, ``primary_ids`` is last-8 and ``blend_ids`` is last-k this season.
    """
    n_this = this_season_n(history, season) if n is None else int(n)
    if history.empty:
        return [], None, "last12 (n=0 this season)", n_this
    ids = history["game_id"].astype(str).tolist()
    if n_this < 6:
        primary = ids[-12:]
        return primary, None, f"last12 (n={n_this} this season)", n_this
    k = min(17, n_this)
    last8 = ids[-8:]
    this_season = history[pd.to_numeric(history.get("_season", history["season"]), errors="coerce") == int(season)]
    lastk = this_season["game_id"].astype(str).tolist()[-k:]
    label = f"50% last8 + 50% last{k} this season (n={n_this})"
    return last8, lastk, label, n_this


def net_epa(pbp: pd.DataFrame, team: str, game_ids: list[str] | None = None) -> float:
    """Offensive EPA/play minus defensive EPA/play (defense from offense's EPA)."""
    team_pbp = pbp_abbr(team)
    plays = filter_pbp(pbp)
    if game_ids is not None:
        plays = plays[plays["game_id"].astype(str).isin([str(g) for g in game_ids])]
    if plays.empty:
        return 0.0
    def _code(x: object) -> str:
        if pd.isna(x) or not str(x).strip():
            return ""
        return try_pbp_abbr(str(x)) or ""

    posteam = plays["posteam"].map(_code)
    defteam = plays["defteam"].map(_code)
    off = plays.loc[posteam == team_pbp, "epa"]
    de = plays.loc[defteam == team_pbp, "epa"]
    off_m = float(off.mean()) if len(off) else 0.0
    de_m = float(de.mean()) if len(de) else 0.0
    if pd.isna(off_m):
        off_m = 0.0
    if pd.isna(de_m):
        de_m = 0.0
    return off_m - de_m


def windowed_net_epa(
    pbp: pd.DataFrame,
    games: pd.DataFrame,
    team: str,
    *,
    season: int,
    week: int,
) -> tuple[float, str, int]:
    history = team_reg_history(games, team, season=season, week=week)
    last8_or_12, lastk, label, n = select_window_game_ids(history, season=season)
    if not last8_or_12:
        return 0.0, label, n
    if lastk is None:
        return net_epa(pbp, team, last8_or_12), label, n
    a = net_epa(pbp, team, last8_or_12)
    b = net_epa(pbp, team, lastk)
    return 0.5 * a + 0.5 * b, label, n


def epa_home_margin(
    home_net: float,
    away_net: float,
    *,
    hfa: float = HFA_HOME,
    plays_per_game: float = PLAYS_PER_GAME,
) -> float:
    return (float(home_net) - float(away_net)) * float(plays_per_game) + float(hfa)


@dataclass(frozen=True, slots=True)
class EpaMatchup:
    home_net: float
    away_net: float
    epa_home: float
    hfa: float
    window_home: str
    window_away: str
    n_home: int
    n_away: int
    plays_per_game: float = PLAYS_PER_GAME


def matchup_epa(
    pbp: pd.DataFrame,
    games: pd.DataFrame,
    home_team: str,
    away_team: str,
    *,
    season: int,
    week: int,
    hfa: float,
    plays_per_game: float = PLAYS_PER_GAME,
) -> EpaMatchup:
    home_net, wh, nh = windowed_net_epa(pbp, games, home_team, season=season, week=week)
    away_net, wa, na = windowed_net_epa(pbp, games, away_team, season=season, week=week)
    margin = epa_home_margin(home_net, away_net, hfa=hfa, plays_per_game=plays_per_game)
    return EpaMatchup(
        home_net=home_net,
        away_net=away_net,
        epa_home=margin,
        hfa=hfa,
        window_home=wh,
        window_away=wa,
        n_home=nh,
        n_away=na,
        plays_per_game=plays_per_game,
    )
