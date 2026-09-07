"""``nfl-ats`` CLI: card | refresh | grade."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from . import __version__
from .card import build_week_card, merge_unplayed, output_stem, write_card_csvs
from .epa import PLAYS_PER_GAME, filter_pbp
from .grade import grade_picks, summarize, write_grade_csv
from .nfelo import NfeloError, fetch_nfelo
from .nflverse_data import (
    current_nfl_season,
    infer_week,
    load_games,
    load_pbp_seasons,
    week_slate,
)
from .odds_api import OddsApiError, fetch_us_spreads, load_odds_json


def _load_overlays(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"overlays CSV not found: {p}")
    return pd.read_csv(p)


def _load_inputs(
    args: argparse.Namespace,
    *,
    need_odds: bool,
):
    games = load_games(cache=args.cache_dir, force=args.force_download)
    season = int(args.season)
    week = int(args.week) if args.week is not None else infer_week(games, season)
    args.week = week
    slate = week_slate(games, season, week)
    if slate.empty:
        raise SystemExit(f"No REG games for season={season} week={week} in nflverse schedules.")

    pbp_seasons = [season, season - 1]
    pbp = load_pbp_seasons(pbp_seasons, cache=args.cache_dir, force=args.force_download)
    pbp = filter_pbp(pbp)

    if getattr(args, "odds_json", None):
        odds = load_odds_json(args.odds_json)
    elif need_odds:
        odds = fetch_us_spreads()
    else:
        odds = pd.DataFrame()

    nfelo = fetch_nfelo(season, week, json_path=args.nfelo_json)
    overlays = _load_overlays(getattr(args, "overlays", None))
    return games, slate, pbp, nfelo, overlays, odds, season, week


def cmd_card(args: argparse.Namespace) -> int:
    games, slate, pbp, nfelo, overlays, odds, season, week = _load_inputs(args, need_odds=True)
    frame = build_week_card(
        slate,
        all_games=games,
        pbp=pbp,
        odds=odds,
        nfelo=nfelo,
        overlays=overlays,
        season=season,
        week=week,
        plays_per_game=PLAYS_PER_GAME,
    )
    written = write_card_csvs(
        frame, season, week, output_dir=args.output_dir, snapshot="tue", update_live=True
    )
    print(f"Wrote {len(frame)} games → {written['live']}")
    print(f"Tuesday snapshot → {written['tue']}")
    plays = frame[frame["play_flag"] == "Play"]
    print(f"Plays (|edge|>=1.5): {len(plays)} / {len(frame)}")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    games, slate, pbp, nfelo, overlays, odds, season, week = _load_inputs(args, need_odds=True)
    fresh = build_week_card(
        slate,
        all_games=games,
        pbp=pbp,
        odds=odds,
        nfelo=nfelo,
        overlays=overlays,
        season=season,
        week=week,
        plays_per_game=PLAYS_PER_GAME,
    )
    stem = output_stem(season, week, args.output_dir)
    live_path = Path(str(stem) + ".csv")
    previous = pd.read_csv(live_path) if live_path.exists() else pd.DataFrame()
    merged = merge_unplayed(previous, fresh, games)
    written = write_card_csvs(
        merged, season, week, output_dir=args.output_dir, snapshot="fri", update_live=True
    )
    n_prev = 0 if previous.empty else len(previous)
    print(f"Refresh (unplayed only). Previous {n_prev} rows → {len(merged)} rows.")
    print(f"Live → {written['live']}")
    print(f"Friday snapshot → {written['fri']}")
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    games = load_games(cache=args.cache_dir, force=args.force_download)
    season = int(args.season)
    week = int(args.week) if args.week is not None else infer_week(games, season)
    stem = output_stem(season, week, args.output_dir)
    src = Path(args.input) if args.input else Path(str(stem) + ".csv")
    if not src.exists():
        tue = Path(str(stem) + "_tue.csv")
        fri = Path(str(stem) + "_fri.csv")
        if tue.exists():
            src = tue
        elif fri.exists():
            src = fri
        else:
            raise SystemExit(f"No card CSV found at {src}. Run `nfl-ats card` first.")
    picks = pd.read_csv(src)
    graded = grade_picks(picks, games)
    path = write_grade_csv(graded, season, week, output_dir=args.output_dir)
    stats = summarize(graded)
    print(f"Graded {src.name} → {path}")
    wp = stats["win_pct"]
    pwp = stats["play_win_pct"]
    wp_s = "n/a" if pd.isna(wp) else f"{wp:.3f}"
    pwp_s = "n/a" if pd.isna(pwp) else f"{pwp:.3f}"
    print(
        f"All: {stats['wins']}-{stats['losses']}-{stats['pushes']} ({wp_s})  "
        f"Plays: {stats['play_wins']}-{stats['play_losses']}-{stats['play_pushes']} ({pwp_s})"
    )
    return 0


def _add_shared(p: argparse.ArgumentParser) -> None:
    p.add_argument("--season", type=int, default=None, help="NFL season year (default: current).")
    p.add_argument("--week", type=int, default=None, help="Regular-season week (default: inferred).")
    p.add_argument("--output-dir", default="output", help="CSV output directory (default: ./output).")
    p.add_argument(
        "--cache-dir",
        default=".cache/nflverse",
        help="nflverse parquet cache (default: ./.cache/nflverse).",
    )
    p.add_argument("--force-download", action="store_true", help="Re-download nflverse parquets.")
    p.add_argument(
        "--nfelo-json",
        default=None,
        help="Offline nfelo ratings/games JSON if nfeloapp.com scrape fails.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nfl-ats",
        description="Portable NFL ATS week card: Tuesday card, Friday refresh, grade.",
    )
    parser.add_argument("--version", action="version", version=f"nfl-ats {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    card = sub.add_parser("card", help="Build the Tuesday week card CSVs.")
    _add_shared(card)
    card.add_argument(
        "--overlays",
        default=None,
        help="Optional OUT overlay CSV (see samples/overlays.example.csv).",
    )
    card.add_argument(
        "--odds-json",
        default=None,
        help="Optional saved The Odds API JSON (offline / tests).",
    )
    card.set_defaults(func=cmd_card)

    refresh = sub.add_parser("refresh", help="Friday refresh of unplayed games only.")
    _add_shared(refresh)
    refresh.add_argument("--overlays", default=None, help="Optional OUT overlay CSV.")
    refresh.add_argument("--odds-json", default=None, help="Optional saved Odds API JSON.")
    refresh.set_defaults(func=cmd_refresh)

    grade = sub.add_parser("grade", help="Grade a card against nflverse final scores.")
    _add_shared(grade)
    grade.add_argument("--input", default=None, help="Card CSV to grade (default: live picks file).")
    grade.set_defaults(func=cmd_grade)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "season", None) is None:
        args.season = current_nfl_season(date.today())
    try:
        return int(args.func(args))
    except (OddsApiError, NfeloError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
