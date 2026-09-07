"""Offline unit tests for EPA windows, overlay, edge / Play."""
from __future__ import annotations

import pandas as pd
import pytest

from nfl_predictions.epa import (
    HFA_HOME,
    HFA_NEUTRAL,
    epa_home_margin,
    select_window_game_ids,
    team_reg_history,
)
from nfl_predictions.model import (
    PLAY_EDGE,
    blend_model,
    classify_play,
    edge,
    market_home_margin,
    overlay_points,
    pick_side,
)
from nfl_predictions.teams import display_abbr, pbp_abbr


def _hist(n_prev: int, n_this: int, season: int = 2025) -> pd.DataFrame:
    rows = []
    # prior season games
    for w in range(1, n_prev + 1):
        rows.append(
            {
                "game_id": f"{season-1}_{w:02d}_LA_SF",
                "season": season - 1,
                "week": w,
                "game_type": "REG",
                "home_team": "LA",
                "away_team": "SF",
                "home_score": 20,
                "away_score": 17,
            }
        )
    for w in range(1, n_this + 1):
        rows.append(
            {
                "game_id": f"{season}_{w:02d}_LA_SEA",
                "season": season,
                "week": w,
                "game_type": "REG",
                "home_team": "LA",
                "away_team": "SEA",
                "home_score": 24,
                "away_score": 21,
            }
        )
    return pd.DataFrame(rows)


def test_rams_pbp_abbr_is_la_not_lar():
    assert pbp_abbr("LAR") == "LA"
    assert pbp_abbr("Los Angeles Rams") == "LA"
    assert display_abbr("LA") == "LAR"
    assert pbp_abbr("LV") == "LV"


def test_epa_window_n_lt_6_uses_last12():
    games = _hist(n_prev=10, n_this=3, season=2025)
    hist = team_reg_history(games, "LA", season=2025, week=4)
    primary, blend, label, n = select_window_game_ids(hist, season=2025)
    assert n == 3
    assert blend is None
    assert len(primary) == 12  # 10 prior + 3 this, clipped to 12? wait 13 total → last 12
    assert "last12" in label


def test_epa_window_n_ge_6_blends_last8_and_lastk():
    games = _hist(n_prev=5, n_this=8, season=2025)
    hist = team_reg_history(games, "LA", season=2025, week=9)
    primary, blend, label, n = select_window_game_ids(hist, season=2025)
    assert n == 8
    assert blend is not None
    assert len(primary) == 8
    assert len(blend) == 8  # k = min(17, 8) = 8
    assert "50%" in label


def test_hfa_and_epa_home_margin():
    assert epa_home_margin(0.1, -0.1, hfa=HFA_HOME, plays_per_game=65) == pytest.approx(0.2 * 65 + 2.25)
    assert epa_home_margin(0.0, 0.0, hfa=HFA_NEUTRAL) == 0.0


def test_blend_edge_play_threshold():
    model = blend_model(nfelo_home_margin=3.0, epa_home=4.0, overlay=0.0)
    assert model == pytest.approx(0.6 * 3.0 + 0.4 * 4.0)
    mkt = market_home_margin(-3.5)  # home -3.5 → +3.5
    assert mkt == 3.5
    e = edge(model, mkt)
    assert classify_play(1.49) == "Lean"
    assert classify_play(1.5) == "Play"
    assert classify_play(-1.5) == "Play"
    assert pick_side(1.0, "SEA", "NE") == "SEA"  # display
    assert pick_side(-1.0, "SEA", "NE") == "NE"


def test_overlay_home_qb_subtracts_away_adds_and_cap():
    ov = pd.DataFrame(
        [
            {"season": 2025, "week": 1, "team_abbr": "SEA", "spot": "QB", "player": "A", "pts": 4.0, "side": "home", "source": "x"},
            {"season": 2025, "week": 1, "team_abbr": "NE", "spot": "WR1", "player": "B", "pts": 1.5, "side": "away", "source": "x"},
            {"season": 2025, "week": 1, "team_abbr": "NE", "spot": "LT", "player": "C", "pts": 1.5, "side": "away", "source": "x"},
        ]
    )
    res = overlay_points(ov, season=2025, week=1, home_team="SEA", away_team="NE")
    # home QB -4, away WR1 +1.5, away LT +1.5 → -1.0
    assert res.overlay == pytest.approx(-1.0)


def test_overlay_skip_qb_when_qb_adj_ge_50():
    ov = pd.DataFrame(
        [
            {"season": 2025, "week": 1, "team_abbr": "SEA", "spot": "QB", "player": "Backup", "pts": 4.0, "side": "home", "source": "x"},
        ]
    )
    res = overlay_points(
        ov, season=2025, week=1, home_team="SEA", away_team="NE", home_qb_adj=55.0
    )
    assert res.overlay == 0.0
    assert any(line.skipped for line in res.applied)


def test_overlay_stack_cap_6():
    ov = pd.DataFrame(
        [
            {"season": 2025, "week": 1, "team_abbr": "SEA", "spot": "QB", "player": "A", "pts": 4.0, "side": "away", "source": "x"},
            {"season": 2025, "week": 1, "team_abbr": "SEA", "spot": "WR1", "player": "B", "pts": 1.5, "side": "away", "source": "x"},
            {"season": 2025, "week": 1, "team_abbr": "SEA", "spot": "LT", "player": "C", "pts": 1.5, "side": "away", "source": "x"},
        ]
    )
    # all away → +7 → capped +6
    res = overlay_points(ov, season=2025, week=1, home_team="NE", away_team="SEA")
    assert res.overlay == pytest.approx(6.0)
