import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)


class ChallengeName(StrEnum):
    HIGHEST_SCORING_TEAM = "highest_scoring_team"
    BLACKJACK = "blackjack"
    SHOW_ME_YOUR_TDS = "show_me_your_tds"
    WAIVER_WIZARD = "waiver_wizard"
    LARGEST_MARGIN_WINNERS = "largest_margin_winners"
    OVER_ACHIEVER = "over_achiever"
    CONSOLATION_PRIZE = "consolation_prize"
    DEFENSE_WINS_CHAMPIONSHIPS = "defense_wins_championships"
    PHOTO_FINISH = "photo_finish"
    LEDERHOSEN_BOWL = "lederhosen_bowl"
    ART_OF_THE_DEAL = "art_of_the_deal"
    BIGGEST_LOSER = "biggest_loser"
    BULLS_EYE = "bulls_eye"
    GONE_BUT_NOT_FORGOTTEN = "gone_but_not_forgotten"
    LEGATRON = "legatron"
    SWEET_SIXTEEN = "sweet_sixteen"
    HAIL_MARY = "hail_mary"


class ConfigError(ValueError):
    """Raised when the application YAML config cannot be loaded or validated."""


class LeagueConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    season: int = Field(gt=0)


class PayoutConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_dkk: int = Field(gt=0, strict=True)


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_path: Path = Path("data/results")


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    league: LeagueConfig
    payout: PayoutConfig
    data: DataConfig = Field(default_factory=DataConfig)
    challenges: dict[int, ChallengeName] = Field(min_length=1)

    @field_validator("challenges")
    @classmethod
    def validate_challenge_weeks(
        cls, challenges: dict[int, ChallengeName]
    ) -> dict[int, ChallengeName]:
        invalid_weeks = sorted(week for week in challenges if not 1 <= week <= 17)
        if invalid_weeks:
            raise ValueError(
                f"Challenge weeks must be between 1 and 17; got {invalid_weeks}."
            )
        return challenges


def load_config(path: Path) -> AppConfig:
    """Load YAML from path and validate it against the application schema."""
    try:
        raw_config = path.read_text(encoding="utf-8")
    except OSError as error:
        logger.exception("Unable to read config file %s.", path)
        raise ConfigError(f"Unable to read config file {path}: {error}") from error

    logger.info("Raw config file contents from %s:\n%s", path, raw_config)
    try:
        data: Any = yaml.safe_load(raw_config)
    except yaml.YAMLError as error:
        logger.exception("Unable to parse YAML config file %s.", path)
        raise ConfigError(f"Invalid YAML in config file {path}: {error}") from error

    try:
        config = AppConfig.model_validate(data)
    except ValidationError as error:
        logger.exception("Pydantic validation failed for config file %s.", path)
        raise ConfigError(f"Invalid config file {path}:\n{error}") from error

    logger.info(
        "Pydantic validated config from %s:\n%s",
        path,
        config.model_dump_json(indent=2),
    )
    return config
