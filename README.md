# nfl-ats — portable NFL ATS week card

A small Python package that builds a Tuesday NFL against-the-spread card, refreshes unplayed games on Friday, and grades picks against nflverse scores. Market lines come **only** from [The Odds API](https://the-odds-api.com/) US-book **median** spreads.

Anyone with `THE_ODDS_API_KEY` can run it. No Databricks, no DuckDB warehouse, no contest lock lines.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env        # then put your Odds API key in .env
```

```bash
# Tuesday card → ./output/{season}_week{N}_ats_picks.csv and _tue.csv
nfl-ats card --season 2025 --week 1 --overlays samples/overlays.example.csv

# Friday refresh of unplayed games only → updates live file + _fri.csv
nfl-ats refresh --season 2025 --week 1 --overlays samples/overlays.example.csv

# Grade vs nflverse final scores → _grade.csv
nfl-ats grade --season 2025 --week 1
```

Offline tests (no network, no API key):

```bash
pytest
```

`--season` / `--week` default to the current NFL season and the next unplayed REG week from the nflverse schedule.


## nflverse cache (box / weekly jobs)

Parquets are **not** in git (see `.gitignore` → `.cache/`). Prefetch locally:

```bash
make fetch-nflverse
# or: ./scripts/fetch_nflverse.sh
```

Default path (repo root cwd): `./.cache/nflverse/`  
On the Bot VM / Analytics weekly path: `/workspace/nfl-ats/.cache/nflverse/`

Downloads `games.parquet` plus `play_by_play_{1999..2025}.parquet` from [nflverse-data releases](https://github.com/nflverse/nflverse-data/releases). Override with `NFLVERSE_START_SEASON` / `NFLVERSE_END_SEASON` / `NFLVERSE_CACHE` / `FORCE=1`.

CLI auto-downloads missing seasons into `--cache-dir` (default `.cache/nflverse`) when you run `nfl-ats card|refresh|grade`.

## Environment

| Variable | Required | Purpose |
| --- | --- | --- |
| `THE_ODDS_API_KEY` | yes (live card/refresh) | The Odds API key. **Never printed.** |
| `ODDS_API_KEY` | fallback | Used only if `THE_ODDS_API_KEY` is unset. |

See `.env.example`. The CLI loads `.env` via python-dotenv.

## Model

```
epa_home   = (home_net_epa - away_net_epa) * 65 + HFA
HFA        = 2.25 at home, 0 on international / neutral sites
model_home = 0.60 * nfelo_home_margin + 0.40 * epa_home + overlay
edge       = model_home - market_home_margin
market_home_margin = -spread_home     # home -3.5 → market margin +3.5
Play if |edge| >= 1.5 else Lean
```

**EPA window** (n = completed REG games this season for that team, before the slate week):

- `n < 6` → last 12 REG games (may cross seasons)
- `n >= 6` → 50% last-8 + 50% last-k this season, `k = min(17, n)`

PBP filter: `play_type` in `{pass, run}`, `qb_kneel == 0`, `qb_spike == 0`, `epa` not null. nflverse pbp uses **`LA` for the Rams** (display `LAR` is fine).

**Overlay** (OUT / will-not-play only, optional CSV):

- QB 4.0, WR1 1.5, LT 1.5
- Home OUT subtracts from `model_home`; away OUT adds
- Stack cap ±6.0
- Skip the QB 4.0 when that team's nfelo `|QB adj| >= 50` (already priced in)

## Data sources

| Source | What | How |
| --- | --- | --- |
| The Odds API | US book median home spreads | `GET .../v4/sports/americanfootball_nfl/odds?regions=us&markets=spreads` |
| nflverse | PBP + schedule | GitHub releases `play_by_play_{season}.parquet` and `games.parquet`, cached under `./.cache/nflverse/` |
| nfelo | Power ratings + model spreads | Scrape [nfeloapp.com](https://www.nfeloapp.com/nfl-power-ratings); GitHub `greerreNFL/nfelo` CSVs as a backup |

### nfelo scrape failure

nfeloapp.com is a Next.js app. The scraper reads the power-ratings HTML table and `__NEXT_DATA__` when present. If that fails (JS-only shell, layout change, network), pass a local dump:

```bash
nfl-ats card --season 2025 --week 1 --nfelo-json samples/nfelo.example.json
```

Schema (ratings and/or games):

```json
{
  "ratings": [{"team": "SEA", "nfelo": 1751, "qb_adj": -7, "value": 10.1}],
  "games": [{
    "season": 2025, "week": 1, "home": "SEA", "away": "SF",
    "nfelo_home_margin": 3.5, "home_qb_adj": -7, "away_qb_adj": 14
  }]
}
```

If `games` is omitted, home margin is `home_value - away_value + HFA` (value is nfelo points vs average; elo is converted at 25 elo ≈ 1 point).

`--odds-json` is available for a saved Odds API response (offline / tests).

## Overlays CSV

`--overlays samples/overlays.example.csv`

| column | notes |
| --- | --- |
| season, week | slate filter |
| team_abbr | any common abbr (`KC`, `LAR`, `LA`, `LV`, `OAK`) |
| spot | `QB` / `WR1` / `LT` |
| player | name, for notes |
| pts | optional; defaults by spot |
| source | free text |
| side | `home` or `away` (inferred from team if omitted) |

Only rows you treat as **OUT / will-not-play** should be in the file.

## Outputs (`./output/`)

| file | command |
| --- | --- |
| `{season}_week{N}_ats_picks.csv` | live card (written by `card`, updated by `refresh`) |
| `{season}_week{N}_ats_picks_tue.csv` | Tuesday snapshot |
| `{season}_week{N}_ats_picks_fri.csv` | Friday snapshot |
| `{season}_week{N}_ats_picks_grade.csv` | graded card |

Columns include `kickoff`, `teams`, `spread_home`, `market_home_margin`, `epa_home`, `nfelo_home_margin`, `overlay`, `model_home`, `edge`, `play_flag`, `pick`, `confidence`, `notes`, `window`, `sources`.

`refresh` leaves completed games as they were and rewrites only unplayed rows.

## Install / develop

```bash
pip install -e ".[dev]"
pytest
nfl-ats --help
```

Requires Python 3.11+. Runtime deps: pandas, numpy, requests, pyarrow, python-dotenv.

## License

MIT. nflverse data is CC-BY-4.0 from [nflverse/nflverse-data](https://github.com/nflverse/nflverse-data). Market lines remain subject to The Odds API terms. nfelo ratings belong to [nfelo](https://www.nfeloapp.com/).
