"""Grade ATS picks against nflverse final scores."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .teams import display_abbr, pbp_abbr


def ats_result(home_score: float, away_score: float, spread_home: float, pick: str, home_team: str, away_team: str) -> str:
    """W / L / P / U for the card pick.

    Home covers when (home_score - away_score) + spread_home > 0.
    """
    if pd.isna(home_score) or pd.isna(away_score) or pd.isna(spread_home):
        return "U"
    cover = (float(home_score) - float(away_score)) + float(spread_home)
    pick_s = str(pick or "").strip().upper()
    if pick_s in {"", "PASS", "NAN", "NONE"}:
        return "P" if abs(cover) < 1e-9 else "U"
    home_d = display_abbr(home_team)
    away_d = display_abbr(away_team)
    home_p = pbp_abbr(home_team)
    away_p = pbp_abbr(away_team)
    picked_home = pick_s in {home_d.upper(), home_p.upper(), "HOME"}
    picked_away = pick_s in {away_d.upper(), away_p.upper(), "AWAY"}
    if abs(cover) < 1e-9:
        return "P"
    if picked_home:
        return "W" if cover > 0 else "L"
    if picked_away:
        return "W" if cover < 0 else "L"
    return "U"


def grade_picks(picks: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Join scores onto a card and add ATS grade columns."""
    g = games.copy()
    g["_gid"] = g["game_id"].astype(str)
    score_cols = [c for c in ("home_score", "away_score", "result", "spread_line") if c in g.columns]
    slim = g[["_gid"] + score_cols].drop_duplicates("_gid")

    out = picks.copy()
    out["_gid"] = out["game_id"].astype(str)
    if "home_score" in out.columns:
        out = out.drop(columns=["home_score"], errors="ignore")
    if "away_score" in out.columns:
        out = out.drop(columns=["away_score"], errors="ignore")
    out = out.merge(slim, on="_gid", how="left")

    results: list[str] = []
    actual_margins: list[float] = []
    cover_margins: list[float] = []
    for _, row in out.iterrows():
        hs, aws = row.get("home_score"), row.get("away_score")
        spread = row.get("spread_home")
        if pd.isna(hs) or pd.isna(aws):
            actual_margins.append(float("nan"))
            cover_margins.append(float("nan"))
            results.append("U")
            continue
        margin = float(hs) - float(aws)
        actual_margins.append(margin)
        if pd.isna(spread):
            cover_margins.append(float("nan"))
        else:
            cover_margins.append(margin + float(spread))
        results.append(
            ats_result(float(hs), float(aws), float(spread) if pd.notna(spread) else float("nan"),
                       str(row.get("pick") or ""), str(row.get("home_team")), str(row.get("away_team")))
        )
    out["actual_home_margin"] = actual_margins
    out["cover_margin"] = cover_margins
    out["ats_result"] = results
    out = out.drop(columns=["_gid"], errors="ignore")
    return out


def summarize(graded: pd.DataFrame) -> dict[str, float | int]:
    plays = graded[graded["play_flag"].astype(str).str.casefold() == "play"] if "play_flag" in graded.columns else graded
    def _wl(df: pd.DataFrame) -> tuple[int, int, int]:
        s = df["ats_result"].astype(str).str.upper()
        return int((s == "W").sum()), int((s == "L").sum()), int((s == "P").sum())

    w, l, p = _wl(graded)
    pw, pl, pp = _wl(plays) if not plays.empty else (0, 0, 0)
    decided = w + l
    pdecided = pw + pl
    return {
        "games": int(len(graded)),
        "wins": w,
        "losses": l,
        "pushes": p,
        "win_pct": (w / decided) if decided else float("nan"),
        "play_wins": pw,
        "play_losses": pl,
        "play_pushes": pp,
        "play_win_pct": (pw / pdecided) if pdecided else float("nan"),
    }


def write_grade_csv(
    graded: pd.DataFrame,
    season: int,
    week: int,
    *,
    output_dir: str | Path = "output",
) -> Path:
    d = Path(output_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{int(season)}_week{int(week)}_ats_picks_grade.csv"
    graded.to_csv(path, index=False)
    return path


def load_card_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)
