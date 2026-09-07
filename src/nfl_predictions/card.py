"""Build and write the ATS week card."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .epa import PLAYS_PER_GAME, home_field_advantage, matchup_epa
from .model import (
    OverlayResult,
    blend_model,
    classify_play,
    confidence,
    edge as model_edge,
    overlay_points,
    pick_side,
)
from .nfelo import NfeloData
from .teams import display_abbr, pbp_abbr, try_pbp_abbr

CARD_COLUMNS = [
    "season",
    "week",
    "game_id",
    "kickoff",
    "away_team",
    "home_team",
    "teams",
    "spread_home",
    "market_home_margin",
    "epa_home",
    "nfelo_home_margin",
    "overlay",
    "model_home",
    "edge",
    "play_flag",
    "pick",
    "confidence",
    "notes",
    "window",
    "sources",
    "hfa",
    "location",
    "n_home",
    "n_away",
]


def _kickoff(row: pd.Series) -> str:
    day = row.get("gameday") or row.get("gametime") or ""
    tm = row.get("gametime") or ""
    day_s = str(day)[:10] if pd.notna(day) else ""
    tm_s = str(tm) if pd.notna(tm) and str(tm) not in {"nan", "None"} else ""
    if day_s and tm_s and tm_s not in day_s:
        return f"{day_s} {tm_s}".strip()
    return day_s or tm_s


def _lookup_odds(odds: pd.DataFrame, home_pbp: str, away_pbp: str) -> pd.Series | None:
    if odds is None or odds.empty:
        return None
    h = odds["home_team"].map(lambda x: try_pbp_abbr(x) if pd.notna(x) else None)
    a = odds["away_team"].map(lambda x: try_pbp_abbr(x) if pd.notna(x) else None)
    hit = odds[(h == home_pbp) & (a == away_pbp)]
    if hit.empty:
        return None
    return hit.iloc[0]


def _r(value: Any, ndigits: int = 3) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return float("nan")
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return float("nan")


def build_week_card(
    slate: pd.DataFrame,
    *,
    all_games: pd.DataFrame,
    pbp: pd.DataFrame,
    odds: pd.DataFrame,
    nfelo: NfeloData,
    overlays: pd.DataFrame | None = None,
    season: int,
    week: int,
    plays_per_game: float = PLAYS_PER_GAME,
) -> pd.DataFrame:
    """Score every game on the slate. Network-free given the frames."""
    rows: list[dict[str, Any]] = []
    for _, game in slate.iterrows():
        home_raw = game.get("home_team")
        away_raw = game.get("away_team")
        if pd.isna(home_raw) or pd.isna(away_raw):
            continue
        home_pbp = pbp_abbr(home_raw)
        away_pbp = pbp_abbr(away_raw)
        home_d = display_abbr(home_raw)
        away_d = display_abbr(away_raw)
        hfa = home_field_advantage(game)
        epa = matchup_epa(
            pbp,
            all_games,
            home_pbp,
            away_pbp,
            season=season,
            week=week,
            hfa=hfa,
            plays_per_game=plays_per_game,
        )
        home_qb = nfelo.qb_adj(home_pbp)
        away_qb = nfelo.qb_adj(away_pbp)
        g_row = nfelo.game_row(home_pbp, away_pbp, season=season, week=week)
        if g_row is not None:
            if pd.notna(g_row.get("home_qb_adj")):
                home_qb = float(g_row["home_qb_adj"])
            if pd.notna(g_row.get("away_qb_adj")):
                away_qb = float(g_row["away_qb_adj"])
        ov: OverlayResult = overlay_points(
            overlays,
            season=season,
            week=week,
            home_team=home_pbp,
            away_team=away_pbp,
            home_qb_adj=home_qb,
            away_qb_adj=away_qb,
        )
        nfelo_m = nfelo.home_margin(
            home_pbp, away_pbp, hfa=hfa, season=season, week=week
        )
        odds_row = _lookup_odds(odds, home_pbp, away_pbp)
        spread_home = float("nan")
        mkt = float("nan")
        n_books = None
        if odds_row is not None:
            spread_home = float(odds_row["spread_home"]) if pd.notna(odds_row.get("spread_home")) else float("nan")
            mkt = (
                float(odds_row["market_home_margin"])
                if pd.notna(odds_row.get("market_home_margin"))
                else (-spread_home if pd.notna(spread_home) else float("nan"))
            )
            n_books = odds_row.get("n_us_books")

        notes: list[str] = []
        if pd.isna(spread_home):
            notes.append("missing US median market line")
        if pd.isna(nfelo_m):
            notes.append("missing nfelo margin")
            nfelo_m = 0.0
        notes.extend(ov.notes)
        for line in ov.applied:
            tag = f"{line.side} {line.spot}"
            if line.player:
                tag += f" {line.player}"
            tag += " OUT"
            if line.skipped:
                tag += " (skipped)"
            notes.append(tag)

        model = blend_model(nfelo_m, epa.epa_home, ov.overlay)
        if pd.isna(mkt):
            edg = float("nan")
            flag = "Lean"
            pick = "PASS"
            conf = "Low"
        else:
            edg = model_edge(model, mkt)
            flag = classify_play(edg)
            pick = pick_side(edg, home_pbp, away_pbp)
            conf = confidence(edg)

        window = f"home: {epa.window_home}; away: {epa.window_away}"
        src_bits = [
            "odds: The Odds API US median",
            "epa: nflverse pbp",
            f"nfelo: {nfelo.source or 'nfeloapp.com'}",
        ]
        if n_books is not None and pd.notna(n_books):
            src_bits[0] += f" ({int(n_books)} books)"
        loc = game.get("location") if "location" in game.index else ""
        rows.append(
            {
                "season": int(season),
                "week": int(week),
                "game_id": game.get("game_id") or f"{season}_{week:02d}_{away_d}_{home_d}",
                "kickoff": _kickoff(game),
                "away_team": away_d,
                "home_team": home_d,
                "teams": f"{away_d} @ {home_d}",
                "spread_home": _r(spread_home, 2),
                "market_home_margin": _r(mkt, 2),
                "epa_home": _r(epa.epa_home, 3),
                "nfelo_home_margin": _r(nfelo_m, 3),
                "overlay": _r(ov.overlay, 2),
                "model_home": _r(model, 3),
                "edge": _r(edg, 3),
                "play_flag": flag,
                "pick": pick,
                "confidence": conf,
                "notes": "; ".join(notes),
                "window": window,
                "sources": "; ".join(src_bits),
                "hfa": hfa,
                "location": loc if pd.notna(loc) else "",
                "n_home": epa.n_home,
                "n_away": epa.n_away,
            }
        )
    out = pd.DataFrame(rows, columns=CARD_COLUMNS)
    if not out.empty:
        out = out.sort_values(["kickoff", "game_id"], kind="mergesort").reset_index(drop=True)
    return out


def output_stem(season: int, week: int, output_dir: str | Path = "output") -> Path:
    d = Path(output_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{int(season)}_week{int(week)}_ats_picks"


def write_card_csvs(
    frame: pd.DataFrame,
    season: int,
    week: int,
    *,
    output_dir: str | Path = "output",
    snapshot: str | None = "tue",
    update_live: bool = True,
) -> dict[str, Path]:
    """Write live ``*_ats_picks.csv`` and optional ``_tue`` / ``_fri`` snapshot."""
    stem = output_stem(season, week, output_dir)
    written: dict[str, Path] = {}
    live = Path(str(stem) + ".csv")
    if update_live:
        frame.to_csv(live, index=False)
        written["live"] = live
    if snapshot:
        snap = Path(str(stem) + f"_{snapshot}.csv")
        frame.to_csv(snap, index=False)
        written[snapshot] = snap
    return written


def merge_unplayed(
    previous: pd.DataFrame,
    refreshed: pd.DataFrame,
    games: pd.DataFrame,
) -> pd.DataFrame:
    """Keep previous rows for completed games; replace unplayed with ``refreshed``."""
    completed_ids: set[str] = set()
    if games is not None and not games.empty:
        done = games[games["home_score"].notna() & games["away_score"].notna()]
        completed_ids = set(done["game_id"].astype(str))

    if previous is None or previous.empty:
        return refreshed.copy()
    if refreshed is None or refreshed.empty:
        return previous.copy()

    prev = previous.copy()
    new = refreshed.copy()
    keep_mask = prev["game_id"].astype(str).isin(completed_ids)
    kept = prev.loc[keep_mask]
    replace_ids = set(prev["game_id"].astype(str)) - set(kept["game_id"].astype(str))
    incoming = new[
        new["game_id"].astype(str).isin(replace_ids)
        | ~new["game_id"].astype(str).isin(set(prev["game_id"].astype(str)))
    ]
    out = pd.concat([kept, incoming], ignore_index=True)
    # Preserve slate order from refreshed where possible.
    order = {gid: i for i, gid in enumerate(new["game_id"].astype(str))}
    out["_ord"] = out["game_id"].astype(str).map(lambda g: order.get(g, 10_000))
    out = out.sort_values(["_ord", "kickoff"], kind="mergesort").drop(columns=["_ord"])
    return out.reset_index(drop=True)
