"""Blend, overlay, edge, and Play / Lean classification.

``model_home = 0.60 * nfelo_home_margin + 0.40 * epa_home + overlay``
``edge = model_home - market_home_margin`` where ``market_home_margin = -spread_home``

Overlay (OUT / will-not-play only):
  QB 4.0, WR1 1.5, LT 1.5
  home out subtracts, away out adds
  stack cap ±6.0
  skip the QB 4.0 when that team's nfelo |QB adj| >= 50

Play if |edge| >= 1.5 else Lean.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .teams import display_abbr, pbp_abbr, try_pbp_abbr

NFELO_WEIGHT = 0.60
EPA_WEIGHT = 0.40
PLAY_EDGE = 1.5

OVERLAY_QB = 4.0
OVERLAY_WR1 = 1.5
OVERLAY_LT = 1.5
OVERLAY_CAP = 6.0
QB_ADJ_SKIP = 50.0

OVERLAY_DEFAULTS: dict[str, float] = {
    "QB": OVERLAY_QB,
    "WR1": OVERLAY_WR1,
    "WR": OVERLAY_WR1,
    "LT": OVERLAY_LT,
}


@dataclass(slots=True)
class OverlayLine:
    team_pbp: str
    spot: str
    player: str
    pts: float
    side: str  # "home" | "away"
    skipped: bool = False
    reason: str = ""


@dataclass(slots=True)
class OverlayResult:
    overlay: float
    applied: list[OverlayLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _spot_key(spot: str | None) -> str:
    s = str(spot or "").strip().upper()
    if s in {"QB"}:
        return "QB"
    if s in {"WR1", "WR", "X", "Z", "WR-1"}:
        return "WR1"
    if s in {"LT", "T", "OT", "LTACKLE", "LEFT TACKLE"}:
        return "LT"
    return s


def _signed_overlay(pts: float, side: str) -> float:
    mag = abs(float(pts))
    if str(side).strip().lower() == "home":
        return -mag
    return mag


def overlay_points(
    overlays: pd.DataFrame | None,
    *,
    season: int,
    week: int,
    home_team: str,
    away_team: str,
    home_qb_adj: float = 0.0,
    away_qb_adj: float = 0.0,
    cap: float = OVERLAY_CAP,
    qb_skip_threshold: float = QB_ADJ_SKIP,
) -> OverlayResult:
    """Signed overlay for one game. Home OUT subtracts; away OUT adds."""
    home_pbp = pbp_abbr(home_team)
    away_pbp = pbp_abbr(away_team)
    result = OverlayResult(overlay=0.0)
    if overlays is None or overlays.empty:
        return result

    df = overlays.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "season" in df.columns:
        df = df[pd.to_numeric(df["season"], errors="coerce") == int(season)]
    if "week" in df.columns:
        df = df[pd.to_numeric(df["week"], errors="coerce") == int(week)]
    if df.empty:
        return result

    raw = 0.0
    for _, row in df.iterrows():
        team_token = row.get("team_abbr", row.get("team", row.get("team_pbp")))
        team = try_pbp_abbr(team_token) if pd.notna(team_token) else None
        side = str(row.get("side") or "").strip().lower()
        if side not in {"home", "away"}:
            if team == home_pbp:
                side = "home"
            elif team == away_pbp:
                side = "away"
            else:
                continue
        if team is None:
            team = home_pbp if side == "home" else away_pbp
        if team not in {home_pbp, away_pbp}:
            continue
        # Prefer explicit side; keep team consistent with side.
        if side == "home":
            team = home_pbp
        else:
            team = away_pbp

        spot = _spot_key(row.get("spot"))
        if spot not in OVERLAY_DEFAULTS and pd.isna(row.get("pts")):
            result.notes.append(f"ignored unknown spot {row.get('spot')!r}")
            continue
        default_pts = OVERLAY_DEFAULTS.get(spot, 0.0)
        pts_val = row.get("pts")
        pts = default_pts if pts_val is None or (isinstance(pts_val, float) and pd.isna(pts_val)) else float(pts_val)
        player = str(row.get("player") or "").strip()

        skipped = False
        reason = ""
        qb_adj = home_qb_adj if side == "home" else away_qb_adj
        if spot == "QB" and abs(float(qb_adj)) >= float(qb_skip_threshold):
            skipped = True
            reason = f"skip QB overlay; |QB adj|={float(qb_adj):.0f}>={qb_skip_threshold:g}"
            result.notes.append(reason)

        line = OverlayLine(
            team_pbp=team,
            spot=spot,
            player=player,
            pts=float(pts),
            side=side,
            skipped=skipped,
            reason=reason,
        )
        result.applied.append(line)
        if not skipped:
            raw += _signed_overlay(pts, side)

    capped = max(-float(cap), min(float(cap), raw))
    if abs(raw) > float(cap) + 1e-12:
        result.notes.append(f"overlay stack capped {raw:.2f} → {capped:.2f}")
    result.overlay = capped
    return result


def blend_model(nfelo_home_margin: float, epa_home: float, overlay: float = 0.0) -> float:
    return (
        NFELO_WEIGHT * float(nfelo_home_margin)
        + EPA_WEIGHT * float(epa_home)
        + float(overlay)
    )


def market_home_margin(spread_home: float) -> float:
    return -float(spread_home)


def edge(model_home: float, market_home_margin_val: float) -> float:
    return float(model_home) - float(market_home_margin_val)


def classify_play(edge_val: float, threshold: float = PLAY_EDGE) -> str:
    return "Play" if abs(float(edge_val)) >= float(threshold) else "Lean"


def pick_side(edge_val: float, home_team: str, away_team: str) -> str:
    """ATS pick as display abbr. Positive edge → home; negative → away."""
    if float(edge_val) > 0:
        return display_abbr(home_team)
    if float(edge_val) < 0:
        return display_abbr(away_team)
    return "PASS"


def confidence(edge_val: float, threshold: float = PLAY_EDGE) -> str:
    mag = abs(float(edge_val))
    if mag >= 3.0:
        return "High"
    if mag >= float(threshold):
        return "Medium"
    return "Low"
