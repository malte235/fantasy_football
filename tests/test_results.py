import csv
from types import SimpleNamespace
from typing import Any, cast

import pytest

from fantasy_football.challenges.challenges import Challenges
from fantasy_football.results import CSV_COLUMNS, write_weekly_results


def make_result(
    home_score: float,
    away_score: float,
    challenge: str = "highest_scoring_team",
):
    home = SimpleNamespace(team_id=1, team_name="Team 1")
    away = SimpleNamespace(team_id=2, team_name="Team 2")
    box_score = SimpleNamespace(
        home_team=home,
        away_team=away,
        home_score=home_score,
        away_score=away_score,
        home_projected=home_score,
        away_projected=away_score,
        home_lineup=[],
        away_lineup=[],
    )
    league = SimpleNamespace(
        teams=[home, away],
        box_scores=lambda week: [box_score],
    )
    return getattr(Challenges(cast(Any, league)), challenge)(1)


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def test_csv_is_created_with_calculation_and_eligibility_columns(tmp_path):
    result_path = tmp_path / "data" / "results"

    output_file = write_weekly_results(
        make_result(110, 100),
        season=2026,
        week=1,
        result_path=result_path,
    )

    assert output_file.name == "challenge_rankings_weekly_2026.csv"
    assert output_file.parent == result_path
    with output_file.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        assert tuple(reader.fieldnames or ()) == CSV_COLUMNS
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["team"] == "Team 1"
    assert rows[0]["eligible"] == "true"
    assert rows[0]["value_1_label"] == "team points"
    assert rows[0]["value_1"] == "110.0"
    assert rows[0]["value_2"] == "0.0"
    assert rows[0]["operation"] == "subtract"
    assert rows[0]["difference"] == "110.0"
    assert rows[0]["place"] == "1"
    assert rows[0]["payout_dkk"] == "0.00"
    assert rows[1]["eligible"] == "true"


def test_csv_replaces_a_week_and_keeps_other_weeks_in_order(tmp_path):
    result_path = tmp_path / "results"
    output_file = write_weekly_results(
        make_result(110, 100),
        season=2026,
        week=1,
        result_path=result_path,
    )
    write_weekly_results(
        make_result(90, 85),
        season=2026,
        week=2,
        result_path=result_path,
    )

    write_weekly_results(
        make_result(70, 65),
        season=2026,
        week=1,
        result_path=result_path,
    )
    rows = read_rows(output_file)

    assert [(row["week"], row["team"]) for row in rows] == [
        ("1", "Team 1"),
        ("1", "Team 2"),
        ("2", "Team 1"),
        ("2", "Team 2"),
    ]
    assert [row["value_1"] for row in rows[:2]] == ["70.0", "65.0"]
    assert [row["value_1"] for row in rows[2:]] == ["90.0", "85.0"]


def test_csv_distinguishes_ineligible_teams_from_zero_values(tmp_path):
    output_file = write_weekly_results(
        make_result(110, 100, "largest_margin_winners"),
        season=2026,
        week=1,
        result_path=tmp_path,
    )

    rows = read_rows(output_file)
    winner, loser = rows

    assert winner["eligible"] == "true"
    assert winner["value_1"] == "110.0"
    assert winner["value_2"] == "100.0"
    assert winner["difference"] == "10.0"
    assert loser["eligible"] == "false"
    assert loser["value_1"] == ""
    assert loser["value_2"] == ""
    assert loser["difference"] == ""
    assert loser["place"] == "2"


def test_csv_refuses_to_overwrite_an_unrecognized_header(tmp_path):
    output_file = tmp_path / "challenge_rankings_weekly_2026.csv"
    output_file.write_text("week,team\n1,Team 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected CSV header"):
        write_weekly_results(
            make_result(110, 100),
            season=2026,
            week=1,
            result_path=tmp_path,
        )

    assert output_file.read_text(encoding="utf-8") == "week,team\n1,Team 1\n"
