from pathlib import Path

import pytest
from PIL import Image

from fantasy_football.challenges.challenges import ChallengePlacement, ChallengeResult
from fantasy_football.presentation import (
    _centered_line_centers,
    _placement_values,
    _read_description,
    _table_headers,
    write_weekly_challenge_image,
)


def test_text_lines_are_centered_within_their_container():
    centers = _centered_line_centers(top=100, height=64, count=2, spacing=27)

    assert centers == [118.5, 145.5]
    assert sum(centers) / len(centers) == 132


def test_weekly_challenge_image_uses_description_and_writes_png(tmp_path: Path):
    description_file = tmp_path / "challenge_descriptions.csv"
    description_file.write_text(
        "Week,Name,Explanation,Exclusions\n"
        '2,Blackjack,"Closest starter score to 21",DST\n',
        encoding="utf-8",
    )
    assert _read_description(description_file, 2).excluded_positions == "DST"
    result = ChallengeResult(
        challenge="Blackjack",
        value_1_label="best eligible starter points",
        value_2_label="baseline",
        operation="subtract",
        rank_order="descending",
        placements=(
            ChallengePlacement(
                place=1,
                team="Team 1",
                eligible=True,
                value_1=20.8,
                value_2=0,
                difference=20.8,
                players=("Player One",),
                payout_dkk=50,
            ),
            ChallengePlacement(
                place=2,
                team="Team 2",
                eligible=False,
                value_1=None,
                value_2=None,
                difference=None,
            ),
        ),
    )
    assert _table_headers(result) == (
        "Place",
        "Team",
        "Payout (DKK)",
        "Score",
        "Best eligible starter points",
        "Baseline",
        "Players",
    )
    assert _placement_values(result, result.placements[0]) == (
        "1",
        "Team 1",
        "50.00",
        "20.80",
        "20.80",
        "0.00",
        "Player One",
    )

    image_path = write_weekly_challenge_image(
        result,
        season=2026,
        week=2,
        result_path=tmp_path / "results",
        description_path=description_file,
    )

    assert image_path.name == "weekly_challenge_2026_week_02.png"
    assert image_path.parent == tmp_path / "results" / "images"
    assert image_path.exists()
    with Image.open(image_path) as image:
        assert image.format == "PNG"
        assert image.width == 2000
        assert image.height == 705


def test_weekly_challenge_image_requires_matching_description(tmp_path: Path):
    description_file = tmp_path / "challenge_descriptions.csv"
    description_file.write_text(
        "Week,Name,Explanation,Exclusions\n1,Top Scorer,Highest score,\n",
        encoding="utf-8",
    )
    assert _read_description(description_file, 1).excluded_positions == "-"

    with pytest.raises(ValueError, match="has no entry for week 2"):
        write_weekly_challenge_image(
            ChallengeResult(
                challenge="Top Scorer",
                value_1_label="team points",
                value_2_label="baseline",
                operation="subtract",
                rank_order="descending",
                placements=(),
            ),
            season=2026,
            week=2,
            result_path=tmp_path / "results",
            description_path=description_file,
        )
