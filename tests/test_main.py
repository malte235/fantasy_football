import csv
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import fantasy_football.main as main_module
from fantasy_football.challenges.challenges import Challenges
from fantasy_football.config import (
    AppConfig,
    ChallengeName,
    ConfigError,
    LeagueConfig,
    PayoutConfig,
    load_config,
)


def test_run_weekly_challenge_uses_current_espn_week_and_returns_json_data(caplog):
    home_team = SimpleNamespace(team_id=1, team_name="Team 1")
    away_team = SimpleNamespace(team_id=2, team_name="Team 2")
    box_score = SimpleNamespace(
        home_team=home_team,
        away_team=away_team,
        home_score=120,
        away_score=105,
        home_projected=110,
        away_projected=100,
        home_lineup=[],
        away_lineup=[],
    )
    league = SimpleNamespace(
        current_week=1,
        teams=[home_team, away_team],
        box_scores=lambda week, player_team_cache=None: [box_score],
    )

    config = AppConfig(
        league=LeagueConfig(id=561666376, season=2026),
        payout=PayoutConfig(amount_dkk=50),
        challenges={1: ChallengeName.HIGHEST_SCORING_TEAM},
    )
    with caplog.at_level(logging.INFO):
        week, result = Challenges(cast(Any, league)).execute(
            config.challenges, config.payout.amount_dkk
        )

    assert week == 1
    assert result.challenge == "Top Scorer"
    assert result.placements[0].payout_dkk == 50.0
    assert result.placements[1].payout_dkk == 0.0
    assert json.loads(json.dumps(asdict(result)))["placements"][0]["team"] == "Team 1"
    assert "ESPN reports current scoring week 1" in caplog.text
    assert "Selected challenge highest_scoring_team for week 1" in caplog.text
    assert "Challenge highest_scoring_team completed for week 1" in caplog.text


def test_run_weekly_challenge_fails_for_week_without_a_scheduled_challenge():
    league = SimpleNamespace(current_week=18)
    config = AppConfig(
        league=LeagueConfig(id=561666376, season=2026),
        payout=PayoutConfig(amount_dkk=50),
        challenges={1: ChallengeName.HIGHEST_SCORING_TEAM},
    )

    with pytest.raises(ValueError, match="no challenge is configured"):
        Challenges(cast(Any, league)).execute(
            config.challenges, config.payout.amount_dkk
        )


def test_run_weekly_challenge_uses_explicit_week_instead_of_current_espn_week():
    requested_box_score_weeks = []
    league = SimpleNamespace(
        current_week=1,
        teams=[],
        box_scores=lambda week, player_team_cache=None: (
            requested_box_score_weeks.append(week) or []
        ),
    )
    config = AppConfig(
        league=LeagueConfig(id=561666376, season=2026),
        payout=PayoutConfig(amount_dkk=50),
        challenges={2: ChallengeName.BLACKJACK},
    )

    week, result = Challenges(cast(Any, league)).execute(
        config.challenges,
        config.payout.amount_dkk,
        week_override=2,
    )

    assert week == 2
    assert result.challenge == "Blackjack"
    assert requested_box_score_weeks == [2]


def test_run_weekly_challenge_splits_payout_among_first_place_teams_and_rounds_to_ore():
    teams = [SimpleNamespace(team_id=i, team_name=f"Team {i}") for i in range(1, 5)]
    box_scores = [
        SimpleNamespace(
            home_team=teams[0],
            away_team=teams[1],
            home_score=100,
            away_score=100,
            home_projected=100,
            away_projected=100,
            home_lineup=[],
            away_lineup=[],
        ),
        SimpleNamespace(
            home_team=teams[2],
            away_team=teams[3],
            home_score=100,
            away_score=80,
            home_projected=100,
            away_projected=80,
            home_lineup=[],
            away_lineup=[],
        ),
    ]
    league = SimpleNamespace(
        current_week=1,
        teams=teams,
        box_scores=lambda week, player_team_cache=None: box_scores,
    )
    config = AppConfig(
        league=LeagueConfig(id=561666376, season=2026),
        payout=PayoutConfig(amount_dkk=50),
        challenges={1: ChallengeName.HIGHEST_SCORING_TEAM},
    )

    _, result = Challenges(cast(Any, league)).execute(
        config.challenges, config.payout.amount_dkk
    )

    payouts = {placement.team: placement.payout_dkk for placement in result.placements}
    assert payouts == {
        "Team 1": 16.67,
        "Team 2": 16.67,
        "Team 3": 16.67,
        "Team 4": 0.0,
    }


def test_run_weekly_challenge_awards_no_payout_without_scored_results():
    teams = [
        SimpleNamespace(team_id=index, team_name=f"Team {index}")
        for index in range(1, 3)
    ]
    league = SimpleNamespace(
        current_week=17,
        teams=teams,
        box_scores=lambda week, player_team_cache=None: [],
    )
    config = AppConfig(
        league=LeagueConfig(id=561666376, season=2026),
        payout=PayoutConfig(amount_dkk=50),
        challenges={17: ChallengeName.HAIL_MARY},
    )

    _, result = Challenges(cast(Any, league)).execute(
        config.challenges, config.payout.amount_dkk
    )

    assert [
        (placement.place, placement.payout_dkk) for placement in result.placements
    ] == [
        (1, 0.0),
        (1, 0.0),
    ]


def test_run_weekly_challenge_pays_current_leader_for_provisional_results():
    home_team = SimpleNamespace(team_id=1, team_name="Team 1")
    away_team = SimpleNamespace(team_id=2, team_name="Team 2")
    kicker = SimpleNamespace(
        name="Kicker",
        slot_position="K",
        breakdown={"madeFieldGoalsFrom50Plus": 1},
    )
    box_score = SimpleNamespace(
        home_team=home_team,
        away_team=away_team,
        home_score=0,
        away_score=0,
        home_projected=0,
        away_projected=0,
        home_lineup=[kicker],
        away_lineup=[],
    )
    league = SimpleNamespace(
        current_week=15,
        teams=[home_team, away_team],
        box_scores=lambda week, player_team_cache=None: [box_score],
    )
    config = AppConfig(
        league=LeagueConfig(id=561666376, season=2026),
        payout=PayoutConfig(amount_dkk=50),
        challenges={15: ChallengeName.LEGATRON},
    )

    _, result = Challenges(cast(Any, league)).execute(
        config.challenges, config.payout.amount_dkk
    )

    assert result.is_final is False
    assert result.placements[0].team == "Team 1"
    assert result.placements[0].payout_dkk == 50.0


def test_cli_writes_the_result_to_the_configured_csv_path(
    tmp_path, monkeypatch, capsys
):
    home_team = SimpleNamespace(team_id=1, team_name="Team 1")
    away_team = SimpleNamespace(team_id=2, team_name="Team 2")
    box_score = SimpleNamespace(
        home_team=home_team,
        away_team=away_team,
        home_score=120,
        away_score=105,
        home_projected=110,
        away_projected=100,
        home_lineup=[],
        away_lineup=[],
    )
    league = SimpleNamespace(
        current_week=1,
        teams=[home_team, away_team],
        box_scores=lambda week, player_team_cache=None: [box_score],
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "league:\n  id: 12345\n  season: 2027\n"
        "payout:\n  amount_dkk: 50\n"
        "data:\n  result_path: weekly-results\n"
        "challenges:\n  1: highest_scoring_team\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["fantasy-football", "--config", str(config_path)])
    monkeypatch.setattr(main_module, "League", lambda *args, **kwargs: league)

    main_module.main()

    output_file = tmp_path / "weekly-results" / "challenge_rankings_weekly_2027.csv"
    image_file = (
        tmp_path / "weekly-results" / "images" / "weekly_challenge_2027_week_01.png"
    )
    assert output_file.exists()
    assert image_file.exists()
    assert capsys.readouterr().out.strip().splitlines() == [
        str(Path("weekly-results") / output_file.name),
        str(Path("weekly-results") / "images" / image_file.name),
    ]


def test_cli_runs_multiple_configured_weeks_in_one_process(
    tmp_path, monkeypatch, capsys
):
    home_team = SimpleNamespace(team_id=1, team_name="Team 1")
    away_team = SimpleNamespace(team_id=2, team_name="Team 2")
    box_scores = {
        week: SimpleNamespace(
            home_team=home_team,
            away_team=away_team,
            home_score=120 - week,
            away_score=105,
            home_projected=110,
            away_projected=100,
            home_lineup=[],
            away_lineup=[],
        )
        for week in (1, 2)
    }
    requested_box_score_weeks = []
    league = SimpleNamespace(
        current_week=2,
        teams=[home_team, away_team],
        box_scores=lambda week, player_team_cache=None: (
            requested_box_score_weeks.append(week) or [box_scores[week]]
        ),
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "league:\n  id: 12345\n  season: 2027\n"
        "payout:\n  amount_dkk: 50\n"
        "data:\n  result_path: weekly-results\n"
        "challenges:\n  1: highest_scoring_team\n  2: highest_scoring_team\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fantasy-football",
            "--config",
            str(config_path),
            "--weeks",
            "1",
            "2",
        ],
    )
    monkeypatch.setattr(main_module, "League", lambda *args, **kwargs: league)

    main_module.main()

    output_file = tmp_path / "weekly-results" / "challenge_rankings_weekly_2027.csv"
    with output_file.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert {row["week"] for row in rows} == {"1", "2"}
    assert requested_box_score_weeks == [1, 2]
    assert capsys.readouterr().out.strip().splitlines() == [
        str(Path("weekly-results") / output_file.name),
        str(Path("weekly-results") / "images" / "weekly_challenge_2027_week_01.png"),
        str(Path("weekly-results") / output_file.name),
        str(Path("weekly-results") / "images" / "weekly_challenge_2027_week_02.png"),
    ]


def test_cli_previous_week_uses_week_before_espn_current_week(
    tmp_path, monkeypatch, capsys
):
    requested_box_score_weeks = []
    league = SimpleNamespace(
        current_week=9,
        teams=[],
        box_scores=lambda week, player_team_cache=None: (
            requested_box_score_weeks.append(week) or []
        ),
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "league:\n  id: 12345\n  season: 2027\n"
        "payout:\n  amount_dkk: 50\n"
        "data:\n  result_path: weekly-results\n"
        "challenges:\n  8: blackjack\n  9: blackjack\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["fantasy-football", "--config", str(config_path), "--previous-week"],
    )
    monkeypatch.setattr(main_module, "League", lambda *args, **kwargs: league)

    main_module.main()

    output_file = tmp_path / "weekly-results" / "challenge_rankings_weekly_2027.csv"
    image_file = (
        tmp_path / "weekly-results" / "images" / "weekly_challenge_2027_week_08.png"
    )
    assert requested_box_score_weeks == [8]
    assert output_file.exists()
    assert image_file.exists()
    assert capsys.readouterr().out.strip().splitlines() == [
        str(Path("weekly-results") / output_file.name),
        str(Path("weekly-results") / "images" / "weekly_challenge_2027_week_08.png"),
    ]


def test_run_weekly_challenge_rejects_explicit_week_without_assignment():
    league = SimpleNamespace(current_week=1)
    config = AppConfig(
        league=LeagueConfig(id=561666376, season=2026),
        payout=PayoutConfig(amount_dkk=50),
        challenges={1: ChallengeName.HIGHEST_SCORING_TEAM},
    )

    with pytest.raises(ValueError, match="no challenge is configured"):
        Challenges(cast(Any, league)).execute(
            config.challenges,
            config.payout.amount_dkk,
            week_override=18,
        )


def test_load_config_parses_and_logs_config_before_and_after_validation(
    tmp_path, caplog
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "league:\n  id: 12345\n  season: 2027\n"
        "payout:\n  amount_dkk: 50\n"
        "data:\n  result_path: output/results\n"
        "challenges:\n  1: blackjack\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.INFO, logger="fantasy_football.config"):
        config = load_config(config_path)

    assert config.league.id == 12345
    assert config.league.season == 2027
    assert config.payout.amount_dkk == 50
    assert config.data.result_path == Path("output/results")
    assert config.challenges == {1: ChallengeName.BLACKJACK}
    assert f"Raw config file contents from {config_path}" in caplog.text
    assert "Pydantic validated config" in caplog.text
    assert '"id": 12345' in caplog.text


def test_load_config_rejects_unknown_challenge_methods(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "league:\n  id: 12345\n  season: 2027\n"
        "payout:\n  amount_dkk: 50\n"
        "challenges:\n  1: not_a_challenge\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Input should be"):
        load_config(config_path)


def test_load_config_rejects_fractional_payout_amount(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "league:\n  id: 12345\n  season: 2027\n"
        "payout:\n  amount_dkk: 50.5\n"
        "challenges:\n  1: blackjack\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="valid integer"):
        load_config(config_path)


@pytest.mark.parametrize("week", [0, 18])
def test_load_config_rejects_challenge_weeks_outside_supported_schedule(tmp_path, week):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"league:\n  id: 12345\n  season: 2027\n"
        f"payout:\n  amount_dkk: 50\n"
        f"challenges:\n  {week}: blackjack\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="Challenge weeks must be between 1 and 17"):
        load_config(config_path)
