"""nfelo ratings and game-level model spreads.

Primary: scrape nfeloapp.com (power ratings table + week pages).
If the site is JS-only or the scrape fails, callers pass ``--nfelo-json``.

Also tries the public greerreNFL/nfelo GitHub CSVs (same model family) when
the site scrape does not yield ratings.

JSON schema (``--nfelo-json``)::

    {
      "ratings": [{"team": "SEA", "nfelo": 1751, "qb_adj": -7, "value": 10.1}],
      "games": [{
        "season": 2025, "week": 1, "home": "SEA", "away": "SF",
        "nfelo_home_margin": 3.5, "home_qb_adj": -7, "away_qb_adj": 14
      }]
    }
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .teams import nfelo_abbr, pbp_abbr, try_pbp_abbr

NFELOAPP_RATINGS = "https://www.nfeloapp.com/nfl-power-ratings"
NFELOAPP_GAMES = "https://www.nfeloapp.com/games"
NFELOAPP_WEEK = "https://www.nfeloapp.com/weeks/{season}/{week}/"
GITHUB_ELO = (
    "https://raw.githubusercontent.com/greerreNFL/nfelo/main/output_data/elo_snapshot.csv"
)
GITHUB_GAMES = (
    "https://raw.githubusercontent.com/greerreNFL/nfelo/main/output_data/nfelo_games.csv"
)

ELO_PER_POINT = 25.0
_USER_AGENT = (
    "nfl-ats/0.1 (+https://github.com/WyattCurtis327/nfl_predictions; "
    "research; contact via repo issues)"
)


class NfeloError(RuntimeError):
    """Raised when nfelo ratings cannot be loaded."""


@dataclass
class NfeloData:
    ratings: pd.DataFrame
    games: pd.DataFrame
    source: str = ""
    notes: list[str] = field(default_factory=list)

    def qb_adj(self, team: str) -> float:
        code = nfelo_abbr(team)
        if self.ratings.empty:
            return 0.0
        r = self.ratings[self.ratings["team"] == code]
        if r.empty:
            # ratings may store pbp or display codes
            alt = try_pbp_abbr(team)
            if alt:
                r = self.ratings[self.ratings["team"].map(lambda x: try_pbp_abbr(x) == alt)]
        if r.empty:
            return 0.0
        val = r.iloc[0].get("qb_adj", 0.0)
        try:
            return 0.0 if pd.isna(val) else float(val)
        except (TypeError, ValueError):
            return 0.0

    def value(self, team: str) -> float | None:
        code = nfelo_abbr(team)
        if self.ratings.empty:
            return None
        r = self.ratings[self.ratings["team"] == code]
        if r.empty:
            alt = try_pbp_abbr(team)
            if alt:
                r = self.ratings[self.ratings["team"].map(lambda x: try_pbp_abbr(x) == alt)]
        if r.empty:
            return None
        row = r.iloc[0]
        if "value" in row and pd.notna(row["value"]):
            return float(row["value"])
        if "nfelo" in row and pd.notna(row["nfelo"]):
            return (float(row["nfelo"]) - 1505.0) / ELO_PER_POINT
        return None

    def game_row(self, home: str, away: str, season: int | None = None, week: int | None = None) -> pd.Series | None:
        if self.games.empty:
            return None
        hp, ap = nfelo_abbr(home), nfelo_abbr(away)
        g = self.games.copy()
        home_ok = g["home"].map(lambda x: try_pbp_abbr(x) == pbp_abbr(home) if pd.notna(x) else False)
        away_ok = g["away"].map(lambda x: try_pbp_abbr(x) == pbp_abbr(away) if pd.notna(x) else False)
        g = g[home_ok & away_ok]
        if season is not None and "season" in g.columns:
            g = g[pd.to_numeric(g["season"], errors="coerce") == int(season)]
        if week is not None and "week" in g.columns:
            g = g[pd.to_numeric(g["week"], errors="coerce") == int(week)]
        if g.empty:
            return None
        return g.iloc[0]

    def home_margin(
        self,
        home: str,
        away: str,
        *,
        hfa: float,
        season: int | None = None,
        week: int | None = None,
    ) -> float:
        row = self.game_row(home, away, season=season, week=week)
        if row is not None:
            if pd.notna(row.get("nfelo_home_margin")):
                return float(row["nfelo_home_margin"])
            if pd.notna(row.get("nfelo_home_line")):
                return -float(row["nfelo_home_line"])
        hv = self.value(home)
        av = self.value(away)
        if hv is not None and av is not None:
            return float(hv) - float(av) + float(hfa)
        return float("nan")


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t == "table":
            self._table = []
        elif t == "tr" and self._table is not None:
            self._row = []
        elif t in {"td", "th"} and self._row is not None:
            self._cell = []
            self._in_cell = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"td", "th"} and self._in_cell:
            text = re.sub(r"\s+", " ", "".join(self._cell or [])).strip()
            if self._row is not None:
                self._row.append(text)
            self._cell = None
            self._in_cell = False
        elif t == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif t == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._cell is not None:
            self._cell.append(data)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _USER_AGENT, "Accept": "text/html,application/json"})
    return s


def _get(session: requests.Session, url: str, *, timeout: float = 30.0) -> requests.Response:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp


def _extract_next_data(html: str) -> dict[str, Any] | None:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
        html,
        flags=re.DOTALL,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _walk_json(obj: Any, found: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    found = found if found is not None else []
    if isinstance(obj, dict):
        keys = {str(k).lower() for k in obj}
        if "nfelo" in keys or ("qb_adj" in keys and "team" in keys) or "pts_vs_avg" in keys:
            found.append(obj)
        for v in obj.values():
            _walk_json(v, found)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json(item, found)
    return found


_ABBR_RE = re.compile(r"\b([A-Z]{2,3})\b")


def _team_from_cell(text: str) -> str | None:
    # "SeahawksSEA" / "RamsLAR" / "SEA"
    compact = re.sub(r"[\s\-]", "", text)
    for m in reversed(list(re.finditer(r"([A-Z]{2,3})$", compact))):
        tok = m.group(1)
        if try_pbp_abbr(tok):
            return nfelo_abbr(tok)
    for tok in reversed(_ABBR_RE.findall(text.upper())):
        if try_pbp_abbr(tok):
            return nfelo_abbr(tok)
    return None


def _parse_ratings_table(tables: list[list[list[str]]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for table in tables:
        if not table:
            continue
        header = [c.casefold() for c in table[0]]
        # body may have no header row; detect by looking for nfelo-ish numbers
        start = 1
        idx_team = next((i for i, h in enumerate(header) if "team" in h), 0)
        idx_nfelo = next((i for i, h in enumerate(header) if h.strip() in {"nfelo", "elo"}), None)
        idx_qb = next((i for i, h in enumerate(header) if "qb" in h), None)
        idx_val = next((i for i, h in enumerate(header) if "value" in h or "pts" in h), None)
        if idx_nfelo is None:
            # maybe first row is data
            start = 0
            idx_nfelo = 1
            idx_qb = 2
            idx_val = 3
        for rec in table[start:]:
            if not rec:
                continue
            team = _team_from_cell(rec[idx_team] if idx_team < len(rec) else rec[0])
            if team is None:
                continue

            def _num(i: int | None) -> float | None:
                if i is None or i >= len(rec):
                    return None
                raw = rec[i].replace(",", "").replace("+", "").replace("–", "-").replace("—", "-")
                raw = re.sub(r"[^0-9.\-]", "", raw)
                if raw in {"", "-", ".", "-."}:
                    return None
                try:
                    return float(raw)
                except ValueError:
                    return None

            nfelo = _num(idx_nfelo)
            qb = _num(idx_qb)
            val = _num(idx_val)
            if nfelo is None and val is None:
                continue
            rows.append({"team": team, "nfelo": nfelo, "qb_adj": qb if qb is not None else 0.0, "value": val})
    if not rows:
        return pd.DataFrame(columns=["team", "nfelo", "qb_adj", "value"])
    df = pd.DataFrame(rows).drop_duplicates("team", keep="first")
    if df["value"].isna().all() and df["nfelo"].notna().any():
        df["value"] = (pd.to_numeric(df["nfelo"], errors="coerce") - 1505.0) / ELO_PER_POINT
    return df


def _ratings_from_dicts(items: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for obj in items:
        team_tok = obj.get("team") or obj.get("abbr") or obj.get("team_abbr") or obj.get("teamAbbr")
        if team_tok is None and isinstance(obj.get("team_code"), str):
            team_tok = obj["team_code"]
        if team_tok is None:
            continue
        if not try_pbp_abbr(str(team_tok)):
            continue
        nfelo = obj.get("nfelo") or obj.get("elo") or obj.get("rating")
        qb = obj.get("qb_adj") or obj.get("qbAdj") or obj.get("qb_adjustment") or 0
        val = obj.get("value") or obj.get("pts_vs_avg") or obj.get("ptsVsAvg")
        try:
            rows.append(
                {
                    "team": nfelo_abbr(str(team_tok)),
                    "nfelo": None if nfelo is None else float(nfelo),
                    "qb_adj": 0.0 if qb is None else float(qb),
                    "value": None if val is None else float(val),
                }
            )
        except (TypeError, ValueError, KeyError):
            continue
    if not rows:
        return pd.DataFrame(columns=["team", "nfelo", "qb_adj", "value"])
    return pd.DataFrame(rows).drop_duplicates("team", keep="first")


def _games_from_dicts(items: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for obj in items:
        home = obj.get("home") or obj.get("home_team") or obj.get("team1")
        away = obj.get("away") or obj.get("away_team") or obj.get("team2")
        if home is None or away is None:
            gid = str(obj.get("game_id") or "")
            parts = gid.split("_")
            if len(parts) >= 4:
                away, home = parts[-2], parts[-1]
        if not home or not away or not try_pbp_abbr(str(home)) or not try_pbp_abbr(str(away)):
            continue
        margin = obj.get("nfelo_home_margin") or obj.get("home_margin")
        line = (
            obj.get("nfelo_home_line")
            or obj.get("nfelo_home_line_close")
            or obj.get("home_line")
            or obj.get("spread")
        )
        if margin is None and line is not None:
            try:
                margin = -float(line)
            except (TypeError, ValueError):
                margin = None
        try:
            rows.append(
                {
                    "season": obj.get("season"),
                    "week": obj.get("week"),
                    "home": nfelo_abbr(str(home)),
                    "away": nfelo_abbr(str(away)),
                    "nfelo_home_margin": None if margin is None else float(margin),
                    "nfelo_home_line": None if line is None else float(line),
                    "home_qb_adj": float(obj.get("home_qb_adj") or obj.get("home_538_qb_adj") or 0),
                    "away_qb_adj": float(obj.get("away_qb_adj") or obj.get("away_538_qb_adj") or 0),
                }
            )
        except (TypeError, ValueError, KeyError):
            continue
    cols = [
        "season",
        "week",
        "home",
        "away",
        "nfelo_home_margin",
        "nfelo_home_line",
        "home_qb_adj",
        "away_qb_adj",
    ]
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


def parse_nfelo_json(payload: dict[str, Any] | list[Any]) -> NfeloData:
    if isinstance(payload, list):
        ratings = _ratings_from_dicts([x for x in payload if isinstance(x, dict)])
        games = _games_from_dicts([x for x in payload if isinstance(x, dict)])
        return NfeloData(ratings=ratings, games=games, source="json")
    ratings_src = payload.get("ratings") or payload.get("teams") or payload.get("power_ratings") or []
    games_src = payload.get("games") or payload.get("matchups") or payload.get("predictions") or []
    if isinstance(ratings_src, dict):
        ratings_src = list(ratings_src.values()) if not {"team", "nfelo"} <= set(ratings_src) else [ratings_src]
    ratings = _ratings_from_dicts([x for x in ratings_src if isinstance(x, dict)])
    games = _games_from_dicts([x for x in games_src if isinstance(x, dict)])
    if ratings.empty and games.empty:
        walked = _walk_json(payload)
        ratings = _ratings_from_dicts(walked)
        games = _games_from_dicts(walked)
    return NfeloData(ratings=ratings, games=games, source="json")


def load_nfelo_json(path: str | Path) -> NfeloData:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    data = parse_nfelo_json(raw)
    data.source = f"json:{path}"
    if data.ratings.empty and data.games.empty:
        raise NfeloError(f"No nfelo ratings/games found in {path}")
    return data


def _scrape_nfeloapp(session: requests.Session, season: int, week: int) -> NfeloData:
    notes: list[str] = []
    ratings = pd.DataFrame(columns=["team", "nfelo", "qb_adj", "value"])
    games = pd.DataFrame(
        columns=[
            "season",
            "week",
            "home",
            "away",
            "nfelo_home_margin",
            "nfelo_home_line",
            "home_qb_adj",
            "away_qb_adj",
        ]
    )
    try:
        html = _get(session, NFELOAPP_RATINGS).text
        nxt = _extract_next_data(html)
        if nxt:
            walked = _walk_json(nxt)
            ratings = _ratings_from_dicts(walked)
            g2 = _games_from_dicts(walked)
            if not g2.empty:
                games = g2
        if ratings.empty:
            parser = _TableParser()
            parser.feed(html)
            ratings = _parse_ratings_table(parser.tables)
        if ratings.empty:
            notes.append("nfeloapp power-ratings page had no parseable table/JSON")
    except requests.RequestException as exc:
        notes.append(f"nfeloapp ratings fetch failed: {exc.__class__.__name__}")

    for url in (NFELOAPP_GAMES, NFELOAPP_WEEK.format(season=season, week=week)):
        try:
            html = _get(session, url).text
            nxt = _extract_next_data(html)
            if nxt:
                g2 = _games_from_dicts(_walk_json(nxt))
                if not g2.empty:
                    games = pd.concat([games, g2], ignore_index=True)
            parser = _TableParser()
            parser.feed(html)
            # Week pages may list spreads in tables; keep ratings-only if not structured.
        except requests.RequestException:
            notes.append(f"nfeloapp page fetch failed for {url.split('nfeloapp.com')[-1]}")
            continue

    if not games.empty:
        games = games.drop_duplicates(["home", "away", "season", "week"], keep="last")
    source = "nfeloapp.com"
    return NfeloData(ratings=ratings, games=games, source=source, notes=notes)


def _load_github_csv(session: requests.Session, url: str) -> pd.DataFrame:
    resp = _get(session, url, timeout=60.0)
    from io import StringIO

    return pd.read_csv(StringIO(resp.text))


def _from_github(session: requests.Session, season: int, week: int) -> NfeloData:
    notes: list[str] = []
    ratings = pd.DataFrame(columns=["team", "nfelo", "qb_adj", "value"])
    games = pd.DataFrame(
        columns=[
            "season",
            "week",
            "home",
            "away",
            "nfelo_home_margin",
            "nfelo_home_line",
            "home_qb_adj",
            "away_qb_adj",
        ]
    )
    try:
        snap = _load_github_csv(session, GITHUB_ELO)
        if not snap.empty:
            snap.columns = [str(c).strip() for c in snap.columns]
            team_col = "team" if "team" in snap.columns else snap.columns[0]
            rows = []
            for _, r in snap.iterrows():
                tok = r.get(team_col)
                if not try_pbp_abbr(str(tok) if pd.notna(tok) else ""):
                    continue
                nfelo = r.get("nfelo", r.get("elo"))
                qb = r.get("qb_adj", 0)
                val = r.get("pts_vs_avg", r.get("value"))
                rows.append(
                    {
                        "team": nfelo_abbr(str(tok)),
                        "nfelo": None if pd.isna(nfelo) else float(nfelo),
                        "qb_adj": 0.0 if pd.isna(qb) else float(qb),
                        "value": None if pd.isna(val) else float(val),
                    }
                )
            if rows:
                ratings = pd.DataFrame(rows).drop_duplicates("team", keep="first")
    except (requests.RequestException, pd.errors.ParserError, ValueError) as exc:
        notes.append(f"github elo_snapshot failed: {exc.__class__.__name__}")

    try:
        gdf = _load_github_csv(session, GITHUB_GAMES)
        if not gdf.empty and "game_id" in gdf.columns:
            rows = []
            for _, r in gdf.iterrows():
                gid = str(r.get("game_id") or "")
                parts = gid.split("_")
                if len(parts) < 4:
                    continue
                try:
                    gs, gw, away, home = int(parts[0]), int(parts[1]), parts[2], parts[3]
                except ValueError:
                    continue
                if gs != int(season) or gw != int(week):
                    continue
                if not try_pbp_abbr(home) or not try_pbp_abbr(away):
                    continue
                line = r.get("nfelo_home_line_close", r.get("nfelo_home_line_open"))
                margin = None if pd.isna(line) else -float(line)
                rows.append(
                    {
                        "season": gs,
                        "week": gw,
                        "home": nfelo_abbr(home),
                        "away": nfelo_abbr(away),
                        "nfelo_home_margin": margin,
                        "nfelo_home_line": None if pd.isna(line) else float(line),
                        "home_qb_adj": float(r.get("home_538_qb_adj") or 0),
                        "away_qb_adj": float(r.get("away_538_qb_adj") or 0),
                    }
                )
            if rows:
                games = pd.DataFrame(rows)
    except (requests.RequestException, pd.errors.ParserError, ValueError) as exc:
        notes.append(f"github nfelo_games failed: {exc.__class__.__name__}")

    return NfeloData(ratings=ratings, games=games, source="github:greerreNFL/nfelo", notes=notes)


def fetch_nfelo(
    season: int,
    week: int,
    *,
    json_path: str | Path | None = None,
    session: requests.Session | None = None,
) -> NfeloData:
    """Load nfelo ratings/games. Prefer ``json_path`` when provided."""
    if json_path:
        return load_nfelo_json(json_path)

    sess = session or _session()
    errors: list[str] = []
    try:
        data = _scrape_nfeloapp(sess, season, week)
        if not data.ratings.empty or not data.games.empty:
            if data.ratings.empty:
                # fill ratings from github if the games page worked but ratings didn't
                try:
                    gh = _from_github(sess, season, week)
                    if not gh.ratings.empty:
                        data.ratings = gh.ratings
                        data.notes.append("ratings filled from github elo_snapshot")
                except NfeloError:
                    pass
            return data
        errors.extend(data.notes or ["nfeloapp scrape returned empty"])
    except (requests.RequestException, ValueError) as exc:
        errors.append(f"nfeloapp scrape failed: {exc.__class__.__name__}")

    try:
        gh = _from_github(sess, season, week)
        if not gh.ratings.empty or not gh.games.empty:
            gh.notes.extend(errors)
            return gh
        errors.extend(gh.notes or ["github nfelo dump empty"])
    except (requests.RequestException, ValueError) as exc:
        errors.append(f"github nfelo dump failed: {exc.__class__.__name__}")

    hint = (
        "nfelo scrape failed (nfeloapp.com is often JS-rendered). "
        "Re-run with --nfelo-json pointing at ratings/games JSON "
        "(see samples/nfelo.example.json)."
    )
    raise NfeloError(hint + (" Details: " + "; ".join(errors) if errors else ""))
