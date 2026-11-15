import csv
import json
import logging
import os
import tempfile
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import TypedDict

from google import genai
from google.genai.interactions import Interaction

from fantasy_football.config import ChallengeName
from fantasy_football.results import CSV_COLUMNS

logger = logging.getLogger(__name__)


class _ChallengeHistory(TypedDict):
    week: int
    challenge: str
    winners: list[str]


class _ChallengeSummary(TypedDict):
    week: int
    challenge: str


class _HistoryContext(TypedDict):
    completed_challenges: list[_ChallengeSummary]
    win_shares: dict[str, int | str]


class _CurrentWeekResult(TypedDict):
    week: int
    challenge: str
    status: str
    first_place_teams: list[str]
    results: list[dict[str, object]]


def _read_next_challenge(week: int, description_path: Path) -> dict[str, str]:
    with description_path.open(encoding="utf-8", newline="") as description_file:
        reader = csv.DictReader(description_file)
        required_columns = {"Week", "Name", "Explanation", "Exclusions"}
        if not required_columns.issubset(reader.fieldnames or ()):
            raise ValueError(
                f"Challenge descriptions file {description_path} must contain "
                f"columns {sorted(required_columns)}."
            )
        for row in reader:
            if row["Week"] == str(week):
                return {
                    "name": row["Name"],
                    "explanation": row["Explanation"],
                    "exclusions": row["Exclusions"] or "None",
                }
    raise ValueError(
        f"Challenge descriptions file {description_path} has no entry for week {week}."
    )


def _read_challenge_context(
    result_file: Path, current_week: int
) -> tuple[_HistoryContext, _CurrentWeekResult]:
    if not result_file.exists():
        raise FileNotFoundError(f"Weekly results file {result_file} does not exist.")

    required_columns = set(CSV_COLUMNS) - {"opponent_team"}
    grouped: dict[int, _ChallengeHistory] = {}
    current_result: _CurrentWeekResult | None = None
    with result_file.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not required_columns.issubset(reader.fieldnames or ()):
            raise ValueError(
                f"Results file {result_file} must contain columns "
                f"{sorted(required_columns)}."
            )
        for row in reader:
            try:
                week = int(row["week"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Results file {result_file} contains an invalid week."
                ) from error
            week_result: _CurrentWeekResult | None = None
            if week == current_week:
                if current_result is None:
                    current_result = _CurrentWeekResult(
                        week=week,
                        challenge=row["challenge"],
                        status=row["status"],
                        first_place_teams=[],
                        results=[],
                    )
                elif (
                    current_result["challenge"] != row["challenge"]
                    or current_result["status"] != row["status"]
                ):
                    raise ValueError(
                        f"Results file {result_file} contains inconsistent "
                        f"challenge data for week {current_week}."
                    )
                week_result = current_result
            elif week >= current_week or row["status"] != "final":
                continue

            if week < current_week:
                grouped.setdefault(
                    week,
                    _ChallengeHistory(
                        week=week, challenge=row["challenge"], winners=[]
                    ),
                )
            if week_result is not None:
                team_result: dict[str, object] = {
                    column: row.get(column, "") or "" for column in CSV_COLUMNS
                }
                player_data = row.get("players")
                if player_data:
                    try:
                        team_result["players"] = json.loads(player_data)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            f"Results file {result_file} contains invalid player "
                            "details."
                        ) from error
                else:
                    team_result["players"] = []
                week_result["results"].append(team_result)
            if row["place"] != "1":
                continue
            try:
                has_payout = Decimal(row["payout_dkk"]) > 0
            except (InvalidOperation, TypeError) as error:
                raise ValueError(
                    f"Results file {result_file} contains an invalid payout."
                ) from error
            if not has_payout:
                continue

            if week_result is not None:
                if row["team"] not in week_result["first_place_teams"]:
                    week_result["first_place_teams"].append(row["team"])
                continue

            challenge = grouped[week]
            if row["team"] not in challenge["winners"]:
                challenge["winners"].append(row["team"])

        if current_result is None:
            raise ValueError(
                f"Results file {result_file} has no entries for week {current_week}."
            )

    completed_challenges: list[_ChallengeSummary] = []
    team_shares: dict[str, Fraction] = {}
    for week in sorted(grouped):
        challenge = grouped[week]
        completed_challenges.append(
            {"week": challenge["week"], "challenge": challenge["challenge"]}
        )
        winners = challenge["winners"]
        if winners:
            share = Fraction(1, len(winners))
            for team in winners:
                team_shares[team] = team_shares.get(team, Fraction()) + share

    win_shares = {
        team: share.numerator
        if share.denominator == 1
        else f"{share.numerator}/{share.denominator}"
        for team, share in sorted(
            team_shares.items(), key=lambda item: (-item[1], item[0])
        )
    }
    return (
        {
            "completed_challenges": completed_challenges,
            "win_shares": win_shares,
        },
        current_result,
    )


def generate_league_announcement(
    model: str,
    announcement_prompt: str,
    season: int,
    current_week: int,
    challenges: Mapping[int, ChallengeName],
    result_path: Path,
    description_path: Path | None = None,
) -> str | None:
    """Create a shareable announcement using prior challenges as context."""
    next_weeks = sorted(week for week in challenges if week > current_week)
    if not next_weeks:
        logger.info(
            "No configured challenge follows week %s; skipping announcement.",
            current_week,
        )
        return None

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Set GEMINI_API_KEY in the environment to generate the league announcement."
        )
    if not announcement_prompt.strip():
        raise ValueError("The Gemini announcement prompt must not be blank.")

    next_week = next_weeks[0]
    if description_path is None:
        description_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "raw"
            / "challenge_descriptions.csv"
        )
    next_challenge = _read_next_challenge(next_week, description_path)
    result_file = result_path / f"challenge_rankings_weekly_{season}.csv"
    history, current_result = _read_challenge_context(result_file, current_week)

    prompt = (
        f"{announcement_prompt.strip()}\n\n"
        f"Season: {season}\n"
        f"Current run week: {current_week}\n"
        f"Current week full results: "
        f"{json.dumps(current_result, ensure_ascii=False)}\n"
        f"Prior challenge context: {json.dumps(history, ensure_ascii=False)}\n"
        f"Next challenge: {json.dumps(next_challenge, ensure_ascii=False)} "
        f"(week {next_week})"
    )
    client = genai.Client(api_key=api_key)
    interaction = client.interactions.create(model=model, input=prompt)
    if not isinstance(interaction, Interaction):
        raise TypeError("Gemini returned a streaming response unexpectedly.")
    output_text = interaction.output_text
    if not output_text:
        raise RuntimeError("Gemini returned an empty league announcement.")
    return output_text


def write_league_announcement(
    message: str,
    season: int,
    week: int,
    result_path: Path,
) -> Path:
    """Write an announcement to its season/week file and return the path."""
    announcement_path = result_path / "announcements"
    announcement_path.mkdir(parents=True, exist_ok=True)
    output_file = announcement_path / f"league_announcement_{season}_week_{week:02}.txt"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=announcement_path,
            prefix=f".{output_file.name}.",
            suffix=".tmp",
            delete=False,
        ) as announcement_file:
            temporary_path = Path(announcement_file.name)
            announcement_file.write(f"{message.rstrip()}\n")
        os.replace(temporary_path, output_file)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return output_file
