"""Download and cache nflverse play-by-play + schedule parquets.

Files:
  https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet
  https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet

Cache root: ``./.cache/nflverse/`` (cwd-relative).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import requests

PBP_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/pbp/"
    "play_by_play_{season}.parquet"
)
GAMES_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet"
)

DEFAULT_CACHE = Path(".cache") / "nflverse"
_USER_AGENT = "nfl-ats/0.1 (+https://github.com/WyattCurtis327/nfl-ats)"

# PBP columns used by EPA windows (keeps tests / memory light if callers subset).
PBP_COLUMNS = [
    "game_id",
    "season",
    "week",
    "season_type",
    "posteam",
    "defteam",
    "home_team",
    "away_team",
    "play_type",
    "qb_kneel",
    "qb_spike",
    "epa",
]


class NflverseError(RuntimeError):
    """Raised when an nflverse download or read fails."""


def cache_dir(root: str | Path | None = None) -> Path:
    path = Path(root) if root is not None else DEFAULT_CACHE
    path.mkdir(parents=True, exist_ok=True)
    return path


def current_nfl_season(today: date | None = None) -> int:
    """NFL season year: Aug–Dec (and later playoffs) belong to ``today.year``."""
    d = today or date.today()
    return d.year if d.month >= 8 else d.year - 1


def _download(url: str, dest: Path, *, timeout: float = 120.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with requests.get(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/octet-stream"},
            timeout=timeout,
            stream=True,
        ) as resp:
            if not resp.ok:
                raise NflverseError(f"nflverse download failed HTTP {resp.status_code} for {url}")
            with tmp.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
        tmp.replace(dest)
    except requests.RequestException as exc:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise NflverseError(f"nflverse download failed for {url}") from exc
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def download_games(
    *,
    cache: str | Path | None = None,
    force: bool = False,
) -> Path:
    dest = cache_dir(cache) / "games.parquet"
    if dest.exists() and not force:
        return dest
    _download(GAMES_URL, dest)
    return dest


def download_pbp(
    season: int,
    *,
    cache: str | Path | None = None,
    force: bool = False,
) -> Path:
    dest = cache_dir(cache) / f"play_by_play_{int(season)}.parquet"
    if dest.exists() and not force:
        return dest
    _download(PBP_URL.format(season=int(season)), dest)
    return dest


def load_games(
    *,
    cache: str | Path | None = None,
    force: bool = False,
    path: str | Path | None = None,
) -> pd.DataFrame:
    file_path = Path(path) if path is not None else download_games(cache=cache, force=force)
    df = pd.read_parquet(file_path)
    return df


def load_pbp(
    season: int,
    *,
    cache: str | Path | None = None,
    force: bool = False,
    path: str | Path | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    file_path = (
        Path(path) if path is not None else download_pbp(season, cache=cache, force=force)
    )
    try:
        df = pd.read_parquet(file_path, columns=columns)
    except (KeyError, ValueError, TypeError, OSError):
        df = pd.read_parquet(file_path)
        if columns:
            keep = [c for c in columns if c in df.columns]
            df = df[keep]
    return df


def load_pbp_seasons(
    seasons: list[int],
    *,
    cache: str | Path | None = None,
    force: bool = False,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    frames = [
        load_pbp(s, cache=cache, force=force, columns=columns or PBP_COLUMNS)
        for s in seasons
    ]
    if not frames:
        return pd.DataFrame(columns=columns or PBP_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def is_completed(row: pd.Series) -> bool:
    return pd.notna(row.get("home_score")) and pd.notna(row.get("away_score"))


def completed_mask(games: pd.DataFrame) -> pd.Series:
    return games["home_score"].notna() & games["away_score"].notna()


def regular_season(games: pd.DataFrame) -> pd.DataFrame:
    if "game_type" in games.columns:
        return games[games["game_type"].astype(str).str.upper() == "REG"].copy()
    if "season_type" in games.columns:
        return games[games["season_type"].astype(str).str.upper() == "REG"].copy()
    return games.copy()


def week_slate(games: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    g = regular_season(games)
    return g[(g["season"].astype(int) == int(season)) & (g["week"].astype(int) == int(week))].copy()


def infer_week(games: pd.DataFrame, season: int, today: date | None = None) -> int:
    """Smallest REG week in ``season`` that still has an unplayed game, else max week."""
    d = today or date.today()
    g = regular_season(games)
    g = g[g["season"].astype(int) == int(season)]
    if g.empty:
        return 1
    unplayed = g[~completed_mask(g)]
    if not unplayed.empty:
        return int(unplayed["week"].min())
    # If gameday is available, prefer the week containing today.
    if "gameday" in g.columns:
        gd = pd.to_datetime(g["gameday"], errors="coerce")
        around = g[gd.dt.date >= d]
        if not around.empty:
            return int(around["week"].min())
    return int(g["week"].max())
