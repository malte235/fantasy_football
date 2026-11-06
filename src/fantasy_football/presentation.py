import csv
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from fantasy_football.challenges.challenges import ChallengePlacement, ChallengeResult

logger = logging.getLogger(__name__)

IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 2340
MARGIN = 48
CONTENT_WIDTH = IMAGE_WIDTH - 2 * MARGIN
BACKGROUND = "#F1F5F9"
NAVY = "#12304A"
HEADER_BLUE = "#163F67"
TEXT = "#1D344A"
MUTED = "#5E7388"
PAYOUT_BLUE = "#1F5F99"
BORDER = "#DCE5EE"
CARD_RADIUS = 12
BORDER_WIDTH = 1
COLUMN_HEADERS = (
    "Place",
    "Team",
    "Payout (DKK)",
    "Score",
    "value 1",
    "value 2",
    "Players",
)


@dataclass(frozen=True, slots=True)
class ChallengeDescription:
    name: str
    explanation: str
    excluded_positions: str


def _read_description(path: Path, week: int) -> ChallengeDescription:
    with path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        required_columns = {"Week", "Name", "Explanation", "Exclusions"}
        if reader.fieldnames is None or not required_columns.issubset(
            reader.fieldnames
        ):
            raise ValueError(
                f"Challenge descriptions file {path} must have these columns: "
                f"{', '.join(sorted(required_columns))}."
            )

        match: dict[str, str | None] | None = None
        for row in reader:
            week_value = (row.get("Week") or "").strip()
            try:
                row_week = int(week_value)
            except ValueError as error:
                raise ValueError(
                    f"Challenge descriptions file {path} contains an invalid "
                    f"week value {week_value!r}."
                ) from error
            if row_week == week:
                if match is not None:
                    raise ValueError(
                        f"Challenge descriptions file {path} contains multiple "
                        f"entries for week {week}."
                    )
                match = row

    if match is None:
        raise ValueError(
            f"Challenge descriptions file {path} has no entry for week {week}."
        )

    name = (match.get("Name") or "").strip()
    explanation = (match.get("Explanation") or "").strip()
    if not name or not explanation:
        raise ValueError(
            f"Challenge descriptions file {path} has an empty name or "
            f"description for week {week}."
        )
    exclusions = [
        position.strip()
        for position in (match.get("Exclusions") or "").split(",")
        if position.strip()
    ]
    return ChallengeDescription(
        name,
        explanation,
        ", ".join(exclusions) if exclusions else "-",
    )


def _font(
    size: int,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_files = (
        (
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        )
        if bold
        else (
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
    )
    for font_file in font_files:
        if Path(font_file).exists():
            return ImageFont.truetype(font_file, size=size)
    return ImageFont.load_default(size=size)


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    words = text.split()
    if not words:
        return ["-"]
    lines: list[str] = []
    current_line = ""
    for word in words:
        candidate = f"{current_line} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current_line = candidate
        elif current_line:
            lines.append(current_line)
            current_line = word
        else:
            lines.append(word)
    if current_line:
        lines.append(current_line)
    return lines


def _centered_line_centers(
    top: int, height: int, count: int, spacing: int
) -> list[float]:
    first_center = top + height / 2 - (count - 1) * spacing / 2
    return [first_center + index * spacing for index in range(count)]


def _format_score(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _format_payout(value: float) -> str:
    return "-" if value == 0 else f"{value:.2f} DKK"


def _capitalize_words_preserving_case(label: str) -> str:
    return " ".join(word[0].upper() + word[1:] for word in label.split())


def _table_headers(result: ChallengeResult) -> tuple[str, ...]:
    return (
        COLUMN_HEADERS[0],
        COLUMN_HEADERS[1],
        COLUMN_HEADERS[2],
        COLUMN_HEADERS[3],
        _capitalize_words_preserving_case(result.value_1_label),
        _capitalize_words_preserving_case(result.value_2_label),
        COLUMN_HEADERS[6],
    )


def _placement_values(
    result: ChallengeResult,
    placement: ChallengePlacement,
) -> tuple[str, ...]:
    return (
        str(placement.place) if placement.place is not None else "-",
        placement.team,
        f"{placement.payout_dkk:.2f}",
        _format_score(placement.difference),
        _format_score(placement.value_1),
        _format_score(placement.value_2),
        ", ".join(placement.players) or "-",
    )


def _placement_value_content(
    placement: ChallengePlacement,
    value: float | None,
    value_index: int,
) -> str:
    player_values = (
        placement.player_values
        if placement.player_values is not None
        else (placement.value_1,) * len(placement.players)
    )
    player_value_indices = (
        placement.player_value_indices
        if placement.player_value_indices is not None
        else (1,) * len(placement.players)
    )
    player_entries = [
        f"{_format_score(player_value)} ({name})" if player_value is not None else name
        for name, player_value, player_index in zip(
            placement.players,
            player_values,
            player_value_indices,
            strict=True,
        )
        if player_index == value_index
    ]
    content = ", ".join(player_entries) if player_entries else _format_score(value)
    if value_index == 2 and placement.opponent_team is not None:
        content = f"{content} ({placement.opponent_team})"
    return content


def _draw_medal(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    center_y: int,
    place: int | None,
) -> None:
    medal_colors = {1: "#E8B84A", 2: "#C5CCD3", 3: "#C98A5B"}
    medal_color = medal_colors.get(place) if place is not None else None
    color = medal_color or HEADER_BLUE
    draw.ellipse(
        (center_x - 29, center_y - 29, center_x + 29, center_y + 29),
        fill=color,
        outline="#FFFFFF",
        width=4,
    )
    font = _font(28, bold=True)
    draw.text(
        (center_x, center_y),
        str(place) if place is not None else "-",
        fill=NAVY if medal_color is not None else "#FFFFFF",
        font=font,
        anchor="mm",
    )


def _render_image(
    result: ChallengeResult,
    week: int,
    description: ChallengeDescription,
) -> Image.Image:
    title_font = _font(40, bold=True)
    section_font = _font(16, bold=True)
    team_font = _font(34, bold=True)
    metric_label_font = _font(14)
    metric_font = _font(27, bold=True)
    detail_font = _font(23)
    description_font = detail_font
    measurement_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title = f"Challenge Week {week}: {description.name}"
    title_lines = _wrap_text(measurement_draw, title, title_font, CONTENT_WIDTH - 48)
    title_height = len(title_lines) * 48
    header_height = max(138, 35 + title_height + 20)
    description_lines = _wrap_text(
        measurement_draw,
        description.explanation,
        description_font,
        CONTENT_WIDTH - 72,
    )
    exclusions_lines = _wrap_text(
        measurement_draw,
        description.excluded_positions,
        description_font,
        CONTENT_WIDTH - 72,
    )
    description_top = header_height + 18
    description_text_top = description_top + 19
    description_line_spacing = 29
    exclusions_label_top = (
        description_text_top + len(description_lines) * description_line_spacing + 8
    )
    exclusions_text_top = exclusions_label_top + 17
    description_bottom = (
        exclusions_text_top + len(exclusions_lines) * description_line_spacing
    )

    inner_width = CONTENT_WIDTH - 48
    team_width = inner_width - 2 * 178 - 64
    placement_headers = _table_headers(result)
    detail_labels = (placement_headers[4], placement_headers[5])
    value_column_offset = int(
        max(
            measurement_draw.textlength(f"{label}:", font=detail_font)
            for label in detail_labels
        )
        + 16.5
    )
    value_column_width = inner_width - value_column_offset
    card_data: list[
        tuple[ChallengePlacement, list[str], list[str], list[str], int]
    ] = []
    for placement in result.placements:
        values = _placement_values(result, placement)
        team_lines = _wrap_text(measurement_draw, values[1], team_font, team_width)
        detail_1_lines = _wrap_text(
            measurement_draw,
            _placement_value_content(placement, placement.value_1, 1),
            detail_font,
            value_column_width,
        )
        detail_2_lines = _wrap_text(
            measurement_draw,
            _placement_value_content(placement, placement.value_2, 2),
            detail_font,
            value_column_width,
        )
        detail_line_count = len(detail_1_lines) + len(detail_2_lines)
        card_data.append(
            (placement, team_lines, detail_1_lines, detail_2_lines, detail_line_count)
        )

    card_gap = 7
    cards_top = description_bottom + 18
    bottom_margin = 32
    card_height = min(
        166,
        (
            IMAGE_HEIGHT
            - bottom_margin
            - cards_top
            - max(0, len(card_data) - 1) * card_gap
        )
        // max(1, len(card_data)),
    )
    canvas = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, IMAGE_WIDTH, header_height), fill=NAVY)
    for line, title_y in zip(
        title_lines,
        _centered_line_centers(0, header_height, len(title_lines), 48),
        strict=True,
    ):
        draw.text(
            (IMAGE_WIDTH // 2, title_y),
            line,
            fill="#FFFFFF",
            font=title_font,
            anchor="mm",
        )

    text_x = MARGIN + 24
    draw.text(
        (text_x, description_top),
        "CHALLENGE DESCRIPTION",
        fill=MUTED,
        font=section_font,
    )
    for line_index, line in enumerate(description_lines):
        draw.text(
            (text_x, description_text_top + line_index * description_line_spacing),
            line,
            fill=TEXT,
            font=description_font,
        )
    draw.text(
        (text_x, exclusions_label_top),
        "EXCLUDED POSITIONS",
        fill=MUTED,
        font=section_font,
    )
    for line_index, line in enumerate(exclusions_lines):
        draw.text(
            (text_x, exclusions_text_top + line_index * description_line_spacing),
            line,
            fill=TEXT,
            font=description_font,
        )

    for row_index, (
        placement,
        team_lines,
        detail_1_lines,
        detail_2_lines,
        detail_line_count,
    ) in enumerate(card_data):
        card_top = cards_top + row_index * (card_height + card_gap)
        card_left = MARGIN
        card_right = IMAGE_WIDTH - MARGIN
        draw.rounded_rectangle(
            (card_left, card_top, card_right, card_top + card_height),
            radius=CARD_RADIUS,
            fill="#FFFFFF",
            outline=BORDER,
            width=BORDER_WIDTH,
        )
        inner_left = card_left + 24
        inner_right = card_right - 24
        content_height = 64 + 10 + detail_line_count * 28 + 10
        content_top = card_top + (card_height - content_height) / 2
        headline_y = content_top + 32
        _draw_medal(
            draw,
            inner_left + 29,
            round(headline_y),
            placement.place,
        )
        team_x = inner_left + 75
        for line, line_y in zip(
            team_lines,
            _centered_line_centers(
                round(headline_y) - len(team_lines) * 13,
                26 * len(team_lines),
                len(team_lines),
                26,
            ),
            strict=True,
        ):
            draw.text((team_x, line_y), line, fill=TEXT, font=team_font, anchor="lm")

        metric_specs = (
            ("SCORE", _format_score(placement.difference), TEXT, inner_right - 344),
            (
                "PAYOUT",
                _format_payout(placement.payout_dkk),
                PAYOUT_BLUE,
                inner_right,
            ),
        )
        for label, value, color, metric_left in metric_specs:
            is_payout = label == "PAYOUT"
            draw.text(
                (metric_left, headline_y - 32),
                label,
                fill=MUTED,
                font=metric_label_font,
                anchor="ra" if is_payout else "la",
            )
            draw.text(
                (metric_left, headline_y),
                value,
                fill=color,
                font=metric_font,
                anchor="rm" if is_payout else "lm",
            )

        detail_top = content_top + 64 + 10
        for label, lines in zip(detail_labels, (detail_1_lines, detail_2_lines)):
            draw.text(
                (inner_left, detail_top),
                f"{label}:",
                fill=TEXT,
                font=detail_font,
            )
            for line_index, line in enumerate(lines):
                draw.text(
                    (
                        inner_left + value_column_offset,
                        detail_top + line_index * 28,
                    ),
                    line,
                    fill=TEXT,
                    font=detail_font,
                )
            detail_top += max(1, len(lines)) * 28 + 5

    if not card_data:
        draw.rounded_rectangle(
            (
                MARGIN,
                cards_top,
                IMAGE_WIDTH - MARGIN,
                cards_top + 72,
            ),
            radius=12,
            fill="#FFFFFF",
        )
        draw.text(
            (IMAGE_WIDTH // 2, cards_top + 36),
            "No eligible teams to rank yet",
            fill=MUTED,
            font=description_font,
            anchor="mm",
        )
    return canvas


def write_weekly_challenge_image(
    result: ChallengeResult,
    season: int,
    week: int,
    result_path: Path,
    description_path: Path | None = None,
) -> Path:
    """Render the weekly challenge and return the generated PNG path."""
    if description_path is None:
        description_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "raw"
            / "challenge_descriptions.csv"
        )
    description = _read_description(description_path, week)
    image = _render_image(result, week, description)

    image_path = result_path / "images"
    image_path.mkdir(parents=True, exist_ok=True)
    output_file = image_path / f"weekly_challenge_{season}_week_{week:02}.png"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=image_path,
            prefix=f".{output_file.name}.",
            suffix=".tmp",
            delete=False,
        ) as image_file:
            temporary_path = Path(image_file.name)
        image.save(temporary_path, format="PNG")
        os.replace(temporary_path, output_file)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    logger.info("Generated weekly challenge image at %s.", output_file)
    return output_file
