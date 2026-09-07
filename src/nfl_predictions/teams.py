"""NFL team abbreviation mapping.

nflverse play-by-play uses ``LA`` for the Rams (not ``LAR``). Display and
nfelo commonly use ``LAR``. Raiders are ``LV`` in pbp/display and ``OAK`` on
nfeloapp / nfelo github dumps.
"""

from __future__ import annotations

from dataclasses import dataclass

# Historical / feed aliases that should resolve to a canonical pbp code.
_ALIASES: dict[str, str] = {
    "ARI": "ARI",
    "ARZ": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BLT": "BAL",
    "BUF": "BUF",
    "CAR": "CAR",
    "CHI": "CHI",
    "CIN": "CIN",
    "CLE": "CLE",
    "CLV": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GB": "GB",
    "GNB": "GB",
    "HOU": "HOU",
    "HST": "HOU",
    "IND": "IND",
    "JAC": "JAX",
    "JAX": "JAX",
    "KC": "KC",
    "KAN": "KC",
    "LA": "LA",
    "LAR": "LA",
    "RAM": "LA",
    "STL": "LA",
    "SL": "LA",
    "LAC": "LAC",
    "SD": "LAC",
    "SDG": "LAC",
    "LV": "LV",
    "LVR": "LV",
    "OAK": "LV",
    "RAI": "LV",
    "MIA": "MIA",
    "MIN": "MIN",
    "NE": "NE",
    "NEP": "NE",
    "NWE": "NE",
    "NO": "NO",
    "NOR": "NO",
    "NOS": "NO",
    "NYG": "NYG",
    "NYJ": "NYJ",
    "PHI": "PHI",
    "PIT": "PIT",
    "SEA": "SEA",
    "SF": "SF",
    "SFO": "SF",
    "TB": "TB",
    "TAM": "TB",
    "TEN": "TEN",
    "OTI": "TEN",
    "WAS": "WAS",
    "WSH": "WAS",
    "WFT": "WAS",
}


@dataclass(frozen=True, slots=True)
class Team:
    pbp: str
    display: str
    nfelo: str
    name: str
    odds_names: tuple[str, ...]


TEAMS: tuple[Team, ...] = (
    Team("ARI", "ARI", "ARI", "Arizona Cardinals", ("Arizona Cardinals",)),
    Team("ATL", "ATL", "ATL", "Atlanta Falcons", ("Atlanta Falcons",)),
    Team("BAL", "BAL", "BAL", "Baltimore Ravens", ("Baltimore Ravens",)),
    Team("BUF", "BUF", "BUF", "Buffalo Bills", ("Buffalo Bills",)),
    Team("CAR", "CAR", "CAR", "Carolina Panthers", ("Carolina Panthers",)),
    Team("CHI", "CHI", "CHI", "Chicago Bears", ("Chicago Bears",)),
    Team("CIN", "CIN", "CIN", "Cincinnati Bengals", ("Cincinnati Bengals",)),
    Team("CLE", "CLE", "CLE", "Cleveland Browns", ("Cleveland Browns",)),
    Team("DAL", "DAL", "DAL", "Dallas Cowboys", ("Dallas Cowboys",)),
    Team("DEN", "DEN", "DEN", "Denver Broncos", ("Denver Broncos",)),
    Team("DET", "DET", "DET", "Detroit Lions", ("Detroit Lions",)),
    Team("GB", "GB", "GB", "Green Bay Packers", ("Green Bay Packers",)),
    Team("HOU", "HOU", "HOU", "Houston Texans", ("Houston Texans",)),
    Team("IND", "IND", "IND", "Indianapolis Colts", ("Indianapolis Colts",)),
    Team("JAX", "JAX", "JAX", "Jacksonville Jaguars", ("Jacksonville Jaguars",)),
    Team("KC", "KC", "KC", "Kansas City Chiefs", ("Kansas City Chiefs",)),
    Team(
        "LA",
        "LAR",
        "LAR",
        "Los Angeles Rams",
        ("Los Angeles Rams", "LA Rams", "St. Louis Rams"),
    ),
    Team(
        "LAC",
        "LAC",
        "LAC",
        "Los Angeles Chargers",
        ("Los Angeles Chargers", "LA Chargers", "San Diego Chargers"),
    ),
    Team(
        "LV",
        "LV",
        "OAK",
        "Las Vegas Raiders",
        ("Las Vegas Raiders", "Oakland Raiders", "LA Raiders"),
    ),
    Team("MIA", "MIA", "MIA", "Miami Dolphins", ("Miami Dolphins",)),
    Team("MIN", "MIN", "MIN", "Minnesota Vikings", ("Minnesota Vikings",)),
    Team("NE", "NE", "NE", "New England Patriots", ("New England Patriots",)),
    Team("NO", "NO", "NO", "New Orleans Saints", ("New Orleans Saints",)),
    Team("NYG", "NYG", "NYG", "New York Giants", ("New York Giants",)),
    Team("NYJ", "NYJ", "NYJ", "New York Jets", ("New York Jets",)),
    Team("PHI", "PHI", "PHI", "Philadelphia Eagles", ("Philadelphia Eagles",)),
    Team("PIT", "PIT", "PIT", "Pittsburgh Steelers", ("Pittsburgh Steelers",)),
    Team("SEA", "SEA", "SEA", "Seattle Seahawks", ("Seattle Seahawks",)),
    Team("SF", "SF", "SF", "San Francisco 49ers", ("San Francisco 49ers",)),
    Team("TB", "TB", "TB", "Tampa Bay Buccaneers", ("Tampa Bay Buccaneers",)),
    Team("TEN", "TEN", "TEN", "Tennessee Titans", ("Tennessee Titans",)),
    Team(
        "WAS",
        "WAS",
        "WAS",
        "Washington Commanders",
        ("Washington Commanders", "Washington Football Team", "Washington Redskins"),
    ),
)

_BY_PBP: dict[str, Team] = {t.pbp: t for t in TEAMS}
_BY_DISPLAY: dict[str, Team] = {t.display: t for t in TEAMS}
_BY_NFELO: dict[str, Team] = {t.nfelo: t for t in TEAMS}
_BY_ODDS: dict[str, Team] = {}
for _t in TEAMS:
    _BY_ODDS[_t.name.casefold()] = _t
    for _n in _t.odds_names:
        _BY_ODDS[_n.casefold()] = _t


def _norm(code: str | None) -> str:
    return (code or "").strip().upper()


def team_from_any(token: str | None) -> Team | None:
    """Resolve a team from abbr, full name, or odds-api name."""
    if token is None:
        return None
    raw = str(token).strip()
    if not raw:
        return None
    folded = raw.casefold()
    if folded in _BY_ODDS:
        return _BY_ODDS[folded]
    code = _norm(raw)
    pbp = _ALIASES.get(code)
    if pbp and pbp in _BY_PBP:
        return _BY_PBP[pbp]
    if code in _BY_DISPLAY:
        return _BY_DISPLAY[code]
    if code in _BY_NFELO:
        return _BY_NFELO[code]
    return None


def pbp_abbr(token: str | None) -> str:
    """Abbreviation used in nflverse play-by-play (Rams = LA, not LAR)."""
    team = team_from_any(token)
    if team is None:
        raise KeyError(f"Unknown NFL team: {token!r}")
    return team.pbp


def display_abbr(token: str | None) -> str:
    """Abbreviation for card display (Rams = LAR)."""
    team = team_from_any(token)
    if team is None:
        raise KeyError(f"Unknown NFL team: {token!r}")
    return team.display


def nfelo_abbr(token: str | None) -> str:
    """Abbreviation used by nfeloapp / nfelo dumps (Rams = LAR, Raiders = OAK)."""
    team = team_from_any(token)
    if team is None:
        raise KeyError(f"Unknown NFL team: {token!r}")
    return team.nfelo


def odds_name_to_pbp(name: str | None) -> str:
    team = team_from_any(name)
    if team is None:
        raise KeyError(f"Unknown Odds API team name: {name!r}")
    return team.pbp


def try_pbp_abbr(token: str | None) -> str | None:
    team = team_from_any(token)
    return None if team is None else team.pbp
