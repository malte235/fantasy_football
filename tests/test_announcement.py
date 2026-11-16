import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai.interactions import Interaction

from fantasy_football import announcement
from fantasy_football.config import ChallengeName
from fantasy_football.results import CSV_COLUMNS, CSVRow


def _write_data(result_path: Path, description_path: Path) -> None:
    def result_row(
        week: int,
        challenge: str,
        status: str,
        team: str,
        place: int,
        payout_dkk: str,
        value: str,
        player: str | None = None,
    ) -> CSVRow:
        value_label = (
            "best eligible starter points"
            if challenge == "Blackjack"
            else "team points"
        )
        return {
            "season": 2026,
            "week": week,
            "challenge": challenge,
            "status": status,
            "team": team,
            "opponent_team": "",
            "eligible": "true",
            "value_1_label": value_label,
            "value_1": value,
            "value_2_label": "baseline",
            "value_2": "0.0",
            "operation": "subtract",
            "difference": value,
            "rank_order": "descending",
            "place": place,
            "players": json.dumps(
                []
                if player is None
                else [
                    {
                        "name": player,
                        "value": float(value),
                        "value_label": value_label,
                    }
                ]
            ),
            "details": "",
            "payout_dkk": payout_dkk,
            "note": "",
        }

    result_path.mkdir(parents=True)
    with (result_path / "challenge_rankings_weekly_2026.csv").open(
        "w", newline="", encoding="utf-8"
    ) as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(
            [
                result_row(1, "Top Scorer", "final", "Team Alpha", 1, "16.67", "155"),
                result_row(1, "Top Scorer", "final", "Team Beta", 1, "16.67", "155"),
                result_row(1, "Top Scorer", "final", "Team Gamma", 1, "16.66", "155"),
                result_row(
                    2,
                    "Blackjack",
                    "final",
                    "Current Winner",
                    1,
                    "50.00",
                    "20.8",
                    "Jahmyr Gibbs",
                ),
                result_row(
                    2,
                    "Blackjack",
                    "final",
                    "Team Loser",
                    2,
                    "0.00",
                    "20.6",
                    "Amon-Ra St. Brown",
                ),
                result_row(
                    3, "Show me your TDs", "final", "Future Winner", 1, "50.00", "3"
                ),
                result_row(
                    1,
                    "Unfinished Challenge",
                    "provisional",
                    "Provisional Leader",
                    1,
                    "50.00",
                    "100",
                ),
            ]
        )
    description_path.write_text(
        "Week,Name,Explanation,Exclusions\n"
        '3,Show me your TDs,"Team with the most touchdowns",\n',
        encoding="utf-8",
    )


def test_announcement_uses_current_week_full_results_and_next_challenge(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "results"
    description_path = tmp_path / "challenge_descriptions.csv"
    _write_data(result_path, description_path)
    calls = {}

    class FakeClient:
        def __init__(self, *, api_key):
            calls["api_key"] = api_key
            self.interactions = SimpleNamespace(create=self._create)

        def _create(self, *, model, input):
            calls["model"] = model
            calls["input"] = input
            return Interaction.model_construct(
                status="completed", output_text="League message"
            )

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(announcement.genai, "Client", FakeClient)

    message = announcement.generate_league_announcement(
        model="gemini-test-model",
        announcement_prompt=(
            "Announce the current week's winner(s) and the next challenge. "
            "Do not recap older weeks."
        ),
        season=2026,
        current_week=2,
        challenges={
            1: ChallengeName.HIGHEST_SCORING_TEAM,
            2: ChallengeName.BLACKJACK,
            3: ChallengeName.SHOW_ME_YOUR_TDS,
        },
        result_path=result_path,
        description_path=description_path,
    )

    assert message == "League message"
    assert calls["api_key"] == "test-key"
    assert calls["model"] == "gemini-test-model"
    assert calls["input"].startswith(
        "Announce the current week's winner(s) and the next challenge. "
        "Do not recap older weeks.\n\n"
    )
    assert "Show me your TDs" in calls["input"]
    assert "most touchdowns" in calls["input"]
    assert "Future Winner" not in calls["input"]
    assert "Provisional Leader" not in calls["input"]
    assert "Current run week: 2" in calls["input"]
    current_result_text = (
        calls["input"]
        .split("Current week full results: ", 1)[1]
        .split("\nPrior challenge context:", 1)[0]
    )
    current_result = json.loads(current_result_text)
    assert current_result["week"] == 2
    assert current_result["challenge"] == "Blackjack"
    assert current_result["status"] == "final"
    assert current_result["first_place_teams"] == ["Current Winner"]
    assert len(current_result["results"]) == 2
    assert set(current_result["results"][0]) == set(CSV_COLUMNS)
    assert current_result["results"][0]["team"] == "Current Winner"
    assert current_result["results"][0]["players"] == [
        {
            "name": "Jahmyr Gibbs",
            "value": 20.8,
            "value_label": "best eligible starter points",
        }
    ]
    assert current_result["results"][1]["team"] == "Team Loser"
    assert current_result["results"][1]["value_1"] == "20.6"
    assert current_result["results"][1]["players"][0]["name"] == "Amon-Ra St. Brown"
    assert current_result["results"][0]["payout_dkk"] == "50.00"
    assert current_result["results"][1]["payout_dkk"] == "0.00"
    history_text = (
        calls["input"]
        .split("Prior challenge context: ", 1)[1]
        .split("\nNext challenge:", 1)[0]
    )
    history = json.loads(history_text)
    assert history == {
        "completed_challenges": [{"week": 1, "challenge": "Top Scorer"}],
        "wins": [
            {"team": "Team Alpha", "wins": "0.33"},
            {"team": "Team Beta", "wins": "0.33"},
            {"team": "Team Gamma", "wins": "0.33"},
        ],
    }


def test_announcement_skips_when_there_is_no_next_configured_challenge(
    tmp_path,
):
    assert (
        announcement.generate_league_announcement(
            model="gemini-test-model",
            announcement_prompt="Announce the next challenge.",
            season=2026,
            current_week=17,
            challenges={17: ChallengeName.HAIL_MARY},
            result_path=tmp_path,
        )
        is None
    )


def test_announcement_requires_api_key_when_a_next_challenge_exists(
    tmp_path, monkeypatch
):
    description_path = tmp_path / "challenge_descriptions.csv"
    description_path.write_text(
        "Week,Name,Explanation,Exclusions\n2,Blackjack,Closest to 21,\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "unused-fallback")

    with pytest.raises(RuntimeError, match="Set GEMINI_API_KEY"):
        announcement.generate_league_announcement(
            model="gemini-test-model",
            announcement_prompt="Announce the next challenge.",
            season=2026,
            current_week=1,
            challenges={2: ChallengeName.BLACKJACK},
            result_path=tmp_path,
            description_path=description_path,
        )


def test_announcement_is_saved_under_results_and_replaced_on_rerun(tmp_path):
    result_path = tmp_path / "results"

    output_file = announcement.write_league_announcement(
        "First message", season=2026, week=10, result_path=result_path
    )

    assert output_file == (
        result_path / "announcements" / "league_announcement_2026_week_10.txt"
    )
    assert output_file.read_text(encoding="utf-8") == "First message\n"

    announcement.write_league_announcement(
        "Updated message", season=2026, week=10, result_path=result_path
    )

    assert output_file.read_text(encoding="utf-8") == "Updated message\n"
