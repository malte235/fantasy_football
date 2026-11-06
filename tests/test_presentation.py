import csv
from pathlib import Path

import pytest
from PIL import Image, ImageColor, ImageDraw

from fantasy_football.challenges.challenges import ChallengePlacement, ChallengeResult
from fantasy_football.presentation import (
    BACKGROUND,
    CONTENT_WIDTH,
    MARGIN,
    _centered_line_centers,
    _font,
    _format_payout,
    _placement_value_content,
    _placement_values,
    _read_description,
    _table_headers,
    _wrap_text,
    write_weekly_challenge_image,
)


def test_text_lines_are_centered_within_their_container():
    centers = _centered_line_centers(top=100, height=64, count=2, spacing=27)

    assert centers == [118.5, 145.5]
    assert sum(centers) / len(centers) == 132


def test_all_configured_challenge_headlines_fit_at_40px():
    description_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "raw"
        / "challenge_descriptions.csv"
    )
    with description_path.open(encoding="utf-8", newline="") as description_file:
        descriptions = csv.DictReader(description_file)
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        title_font = _font(40, bold=True)

        assert all(
            len(
                _wrap_text(
                    draw,
                    f"Challenge Week {row['Week']}: {row['Name']}",
                    title_font,
                    CONTENT_WIDTH - 48,
                )
            )
            == 1
            for row in descriptions
        )


def test_zero_payout_is_hidden_and_awarded_payout_includes_currency():
    assert _format_payout(0) == "-"
    assert _format_payout(50) == "50.00 DKK"


def test_player_names_and_values_render_under_their_associated_labels():
    placement = ChallengePlacement(
        place=1,
        team="Team 1",
        eligible=True,
        value_1=20,
        value_2=5,
        difference=15,
        players=("Bench TE", "Starting FLEX"),
        player_values=(20, 5),
        player_value_indices=(1, 2),
    )
    assert _placement_value_content(placement, placement.value_1, 1) == (
        "20.00 (Bench TE)"
    )
    assert _placement_value_content(placement, placement.value_2, 2) == (
        "5.00 (Starting FLEX)"
    )


def test_tied_players_keep_their_individual_values_before_their_names():
    placement = ChallengePlacement(
        place=1,
        team="Team 1",
        eligible=True,
        value_1=20,
        value_2=0,
        difference=20,
        players=("Player One", "Player Two"),
        player_values=(20, 19.5),
        player_value_indices=(1, 1),
    )
    assert _placement_value_content(placement, placement.value_1, 1) == (
        "20.00 (Player One), 19.50 (Player Two)"
    )


def test_head_to_head_opponent_is_shown_with_the_opponent_points():
    placement = ChallengePlacement(
        place=1,
        team="Team 1",
        eligible=True,
        value_1=110,
        value_2=100,
        difference=10,
        opponent_team="Team 2",
    )

    assert (
        _placement_values(
            ChallengeResult(
                challenge="Blow Out",
                value_1_label="winning team points",
                value_2_label="opponent points",
                operation="subtract",
                rank_order="descending",
                placements=(placement,),
            ),
            placement,
        )[1]
        == "Team 1"
    )
    assert _placement_value_content(placement, placement.value_2, 2) == (
        "100.00 (Team 2)"
    )


def test_unqualified_matchup_shows_points_but_no_score():
    placement = ChallengePlacement(
        place=3,
        team="Team 2",
        eligible=False,
        value_1=100,
        value_2=105,
        difference=None,
        opponent_team="Team 1",
    )
    result = ChallengeResult(
        challenge="Photo Finish",
        value_1_label="team points",
        value_2_label="opponent points",
        operation="subtract",
        rank_order="ascending",
        placements=(placement,),
    )

    values = _placement_values(result, placement)

    assert values[3:6] == ("-", "100.00", "105.00")
    assert _placement_value_content(placement, placement.value_2, 2) == (
        "105.00 (Team 1)"
    )


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
        value_1_label="starting D/ST points",
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
        "Starting D/ST Points",
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
        assert image.width == 1080
        assert image.height == 2340
        assert image.getpixel((image.width - MARGIN - 8, 176)) == ImageColor.getrgb(
            BACKGROUND
        )


def test_12_team_leaderboard_fits_fixed_phone_canvas(tmp_path: Path):
    description_file = tmp_path / "challenge_descriptions.csv"
    description_file.write_text(
        "Week,Name,Explanation,Exclusions\n"
        '8,Defense Wins Championships,"Team with the highest-scoring defense",\n',
        encoding="utf-8",
    )
    placements = tuple(
        ChallengePlacement(
            place=place,
            team=f"Fantasy Team {place}",
            eligible=True,
            value_1=20 - place,
            value_2=0,
            difference=20 - place,
            players=(f"Player {place}",),
            payout_dkk=50 if place == 1 else 0,
        )
        for place in range(1, 13)
    )
    result = ChallengeResult(
        challenge="Defense Wins Championships",
        value_1_label="starting D/ST points",
        value_2_label="baseline",
        operation="subtract",
        rank_order="descending",
        placements=placements,
    )

    image_path = write_weekly_challenge_image(
        result,
        season=2026,
        week=8,
        result_path=tmp_path / "results",
        description_path=description_file,
    )

    with Image.open(image_path) as image:
        assert image.size == (1080, 2340)


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
