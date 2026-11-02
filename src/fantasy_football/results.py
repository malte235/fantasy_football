import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Literal, cast

from fantasy_football.challenges.challenges import ChallengePlacement, ChallengeResult

CSVColumn = Literal[
    "season",
    "week",
    "challenge",
    "status",
    "team",
    "eligible",
    "value_1_label",
    "value_1",
    "value_2_label",
    "value_2",
    "operation",
    "difference",
    "rank_order",
    "place",
    "players",
    "details",
    "payout_dkk",
    "note",
]
CSVRow = dict[CSVColumn, str | int | float]

CSV_COLUMNS: tuple[CSVColumn, ...] = (
    "season",
    "week",
    "challenge",
    "status",
    "team",
    "eligible",
    "value_1_label",
    "value_1",
    "value_2_label",
    "value_2",
    "operation",
    "difference",
    "rank_order",
    "place",
    "players",
    "details",
    "payout_dkk",
    "note",
)


def _placement_row(
    season: int,
    week: int,
    result: ChallengeResult,
    placement: ChallengePlacement,
) -> CSVRow:
    return {
        "season": season,
        "week": week,
        "challenge": result.challenge,
        "status": "final" if result.is_final else "provisional",
        "team": placement.team,
        "eligible": str(placement.eligible).lower(),
        "value_1_label": result.value_1_label,
        "value_1": "" if placement.value_1 is None else placement.value_1,
        "value_2_label": result.value_2_label,
        "value_2": "" if placement.value_2 is None else placement.value_2,
        "operation": result.operation,
        "difference": "" if placement.difference is None else placement.difference,
        "rank_order": result.rank_order,
        "place": "" if placement.place is None else placement.place,
        "players": json.dumps(list(placement.players), ensure_ascii=False),
        "details": placement.details or "",
        "payout_dkk": f"{placement.payout_dkk:.2f}",
        "note": result.note or "",
    }


def write_weekly_results(
    result: ChallengeResult,
    season: int,
    week: int,
    result_path: Path,
) -> Path:
    """Insert or replace a week's rows in its season CSV and return its path."""
    result_path.mkdir(parents=True, exist_ok=True)
    output_file = result_path / f"challenge_rankings_weekly_{season}.csv"
    existing_rows: list[CSVRow] = []

    if output_file.exists():
        with output_file.open("r", newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            if (
                reader.fieldnames is not None
                and tuple(reader.fieldnames) != CSV_COLUMNS
            ):
                raise ValueError(
                    f"Existing results file {output_file} has an unexpected CSV "
                    "header; refusing to overwrite it."
                )
            for row in reader:
                try:
                    week_value = row["week"]
                    if week_value is None:
                        raise ValueError("empty week")
                    row_week = int(week_value)
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError(
                        f"Existing results file {output_file} contains a row "
                        "without a valid week."
                    ) from error
                if row_week != week:
                    if any(row.get(column) is None for column in CSV_COLUMNS):
                        raise ValueError(
                            f"Existing results file {output_file} contains a "
                            "malformed row."
                        )
                    existing_rows.append(
                        cast(
                            CSVRow,
                            {column: row[column] for column in CSV_COLUMNS},
                        )
                    )

    rows: list[CSVRow] = existing_rows + [
        _placement_row(season, week, result, placement)
        for placement in result.placements
    ]
    rows.sort(
        key=lambda row: (
            int(row["week"]),
            int(row["place"]) if row["place"] != "" else float("inf"),
            str(row["team"]),
        )
    )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            encoding="utf-8",
            dir=result_path,
            prefix=f".{output_file.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_path, output_file)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return output_file
