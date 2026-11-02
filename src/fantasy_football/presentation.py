import csv
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from fantasy_football.challenges.challenges import ChallengePlacement, ChallengeResult

logger = logging.getLogger(__name__)

IMAGE_WIDTH = 2000
MARGIN = 72
CONTENT_WIDTH = IMAGE_WIDTH - 2 * MARGIN
BACKGROUND = "#F1F5F9"
NAVY = "#12304A"
HEADER_BLUE = "#163F67"
TEXT = "#1D344A"
MUTED = "#5E7388"
PAYOUT_BLUE = "#1F5F99"
ROW_WHITE = "#FFFFFF"
ROW_BLUE = "#F6F9FC"
BORDER = "#DCE5EE"
COLUMN_HEADERS = (
    "Place",
    "Team",
    "Payout (DKK)",
    "Score",
    "value 1",
    "value 2",
    "Players",
)
COLUMN_WIDTHS = (140, 320, 190, 150, 300, 270, 476)


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


def _table_headers(result: ChallengeResult) -> tuple[str, ...]:
    return (
        COLUMN_HEADERS[0],
        COLUMN_HEADERS[1],
        COLUMN_HEADERS[2],
        COLUMN_HEADERS[3],
        result.value_1_label.capitalize(),
        result.value_2_label.capitalize(),
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


def _draw_medal(
    draw: ImageDraw.ImageDraw,
    center_x: int,
    center_y: int,
    place: int,
) -> None:
    medal_colors = {1: "#E8B84A", 2: "#C5CCD3", 3: "#C98A5B"}
    color = medal_colors[place]
    draw.polygon(
        [
            (center_x - 14, center_y + 7),
            (center_x - 8, center_y + 23),
            (center_x, center_y + 16),
            (center_x + 8, center_y + 23),
            (center_x + 14, center_y + 7),
        ],
        fill=NAVY,
    )
    draw.ellipse(
        (center_x - 19, center_y - 19, center_x + 19, center_y + 19),
        fill=color,
        outline="#FFFFFF",
        width=3,
    )
    font = _font(20, bold=True)
    draw.text(
        (center_x, center_y),
        str(place),
        fill=NAVY,
        font=font,
        anchor="mm",
    )


def _render_image(
    result: ChallengeResult,
    week: int,
    description: ChallengeDescription,
) -> Image.Image:
    title_font = _font(48, bold=True)
    description_font = _font(23)
    section_font = _font(17, bold=True)
    table_header_font = _font(17, bold=True)
    cell_font = _font(18)
    bold_cell_font = _font(18, bold=True)
    payout_font = _font(18, bold=True)

    measurement_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title = f"Weekly Challenge - Week {week}: {description.name}"
    title_lines = _wrap_text(measurement_draw, title, title_font, CONTENT_WIDTH - 48)
    title_height = len(title_lines) * 58
    header_height = max(190, 62 + title_height + 40)
    description_lines = _wrap_text(
        measurement_draw,
        description.explanation,
        description_font,
        CONTENT_WIDTH - 72,
    )
    description_card_top = header_height + 34
    description_card_height = 74 + len(description_lines) * 34 + 72
    description_card_bottom = description_card_top + description_card_height

    image = Image.new(
        "RGB",
        (IMAGE_WIDTH, description_card_bottom + 10),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, IMAGE_WIDTH, header_height), fill=NAVY)
    for line, title_y in zip(
        title_lines,
        _centered_line_centers(0, header_height, len(title_lines), 58),
        strict=True,
    ):
        draw.text(
            (MARGIN + 34, title_y),
            line,
            fill="#FFFFFF",
            font=title_font,
            anchor="lm",
        )

    draw.rounded_rectangle(
        (
            MARGIN,
            description_card_top,
            IMAGE_WIDTH - MARGIN,
            description_card_bottom,
        ),
        radius=18,
        fill="#FFFFFF",
        outline=BORDER,
        width=2,
    )
    card_x = MARGIN + 36
    text_y = description_card_top + 24
    draw.text(
        (card_x, text_y),
        "CHALLENGE DESCRIPTION",
        fill=MUTED,
        font=section_font,
    )
    text_y += 31
    for line in description_lines:
        draw.text((card_x, text_y), line, fill=TEXT, font=description_font)
        text_y += 34
    text_y += 10
    draw.text(
        (card_x, text_y),
        "EXCLUDED POSITIONS",
        fill=MUTED,
        font=section_font,
    )
    text_y += 26
    draw.text(
        (card_x, text_y),
        description.excluded_positions,
        fill=TEXT,
        font=description_font,
    )

    table_top = description_card_bottom + 34
    header_height = 64
    row_data: list[tuple[ChallengePlacement, list[list[str]]]] = []
    placements = list(result.placements)
    for placement in placements:
        wrapped_values = [
            _wrap_text(draw, value, cell_font, column_width - 28)
            for value, column_width in zip(
                _placement_values(result, placement),
                COLUMN_WIDTHS,
                strict=True,
            )
        ]
        row_data.append((placement, wrapped_values))

    table_bottom = (
        table_top
        + header_height
        + sum(
            max(64, max(len(lines) for lines in row) * 27 + 22) for _, row in row_data
        )
    )
    if not row_data:
        table_bottom += 86
    image_height = table_bottom + 75
    canvas = Image.new("RGB", (IMAGE_WIDTH, image_height), BACKGROUND)
    canvas.paste(image.crop((0, 0, IMAGE_WIDTH, description_card_bottom + 10)), (0, 0))
    draw = ImageDraw.Draw(canvas)

    draw.rounded_rectangle(
        (MARGIN, table_top, IMAGE_WIDTH - MARGIN, table_top + header_height),
        radius=12,
        fill=HEADER_BLUE,
    )
    column_x = MARGIN
    for column_index, (header, column_width) in enumerate(
        zip(_table_headers(result), COLUMN_WIDTHS, strict=True)
    ):
        header_lines = _wrap_text(draw, header, table_header_font, column_width - 24)
        line_height = 23
        for line, header_y in zip(
            header_lines,
            _centered_line_centers(
                table_top,
                header_height,
                len(header_lines),
                line_height,
            ),
            strict=True,
        ):
            if column_index == 0:
                draw.text(
                    (column_x + column_width // 2, header_y),
                    line,
                    fill="#FFFFFF",
                    font=table_header_font,
                    anchor="mm",
                )
            else:
                draw.text(
                    (column_x + 14, header_y),
                    line,
                    fill="#FFFFFF",
                    font=table_header_font,
                    anchor="lm",
                )
        column_x += column_width

    row_top = table_top + header_height
    medal_backgrounds = {1: "#FFF5D6", 2: "#F0F2F4", 3: "#F8EDE5"}
    for row_index, (placement, row) in enumerate(row_data):
        row_height = max(64, max(len(lines) for lines in row) * 27 + 22)
        medal_place = placement.place if placement.difference is not None else None
        row_background = medal_backgrounds.get(
            medal_place,
            ROW_WHITE if row_index % 2 == 0 else ROW_BLUE,
        )
        draw.rectangle(
            (MARGIN, row_top, IMAGE_WIDTH - MARGIN, row_top + row_height),
            fill=row_background,
        )
        column_x = MARGIN
        for column_index, (lines, column_width) in enumerate(
            zip(row, COLUMN_WIDTHS, strict=True)
        ):
            if (
                column_index == 0
                and medal_place is not None
                and medal_place in medal_backgrounds
            ):
                _draw_medal(
                    draw,
                    column_x + column_width // 2,
                    row_top + row_height // 2,
                    medal_place,
                )
            else:
                font = bold_cell_font if column_index in {0, 1, 3} else cell_font
                if column_index == 2:
                    font = payout_font
                fill = (
                    PAYOUT_BLUE if column_index == 2 and placement.payout_dkk else TEXT
                )
                line_height = 27
                for line, text_y in zip(
                    lines,
                    _centered_line_centers(
                        row_top,
                        row_height,
                        len(lines),
                        line_height,
                    ),
                    strict=True,
                ):
                    if column_index == 0:
                        draw.text(
                            (column_x + column_width // 2, text_y),
                            line,
                            fill=fill,
                            font=font,
                            anchor="mm",
                        )
                    else:
                        draw.text(
                            (column_x + 14, text_y),
                            line,
                            fill=fill,
                            font=font,
                            anchor="lm",
                        )
            column_x += column_width
        draw.line(
            (MARGIN, row_top + row_height, IMAGE_WIDTH - MARGIN, row_top + row_height),
            fill=BORDER,
            width=1,
        )
        row_top += row_height

    if not row_data:
        draw.rounded_rectangle(
            (MARGIN, row_top, IMAGE_WIDTH - MARGIN, row_top + 86),
            radius=12,
            fill="#FFFFFF",
        )
        draw.text(
            (IMAGE_WIDTH // 2, row_top + 43),
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
