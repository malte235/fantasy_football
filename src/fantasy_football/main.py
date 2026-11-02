import argparse
import logging
import os
from pathlib import Path

from espn_api.football import League  # type: ignore[import-not-found]

from fantasy_football.challenges.challenges import Challenges
from fantasy_football.config import ConfigError, load_config
from fantasy_football.presentation import write_weekly_challenge_image
from fantasy_football.results import write_weekly_results

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    default_config = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
    parser = argparse.ArgumentParser(description="Run this week's fantasy challenge.")
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help=f"Path to YAML config (default: {default_config})",
    )
    parser.add_argument(
        "--week",
        type=int,
        help="Scoring week to run instead of ESPN's current scoring week.",
    )
    args = parser.parse_args()
    logger.info("Starting weekly fantasy challenge run.")
    logger.info("Loading application config from %s.", args.config)
    try:
        config = load_config(args.config)
    except ConfigError as error:
        logger.error("Configuration loading failed: %s", error)
        parser.error(str(error))
    logger.info(
        "Creating ESPN league client for league %s, season %s.",
        config.league.id,
        config.league.season,
    )
    league = League(
        config.league.id,
        config.league.season,
        espn_s2=os.environ.get("FANTASY_ESPN_S2") or None,
        swid=os.environ.get("FANTASY_SWID") or None,
    )
    logger.info("ESPN league client initialized.")
    week, result = Challenges(league).execute(
        config.challenges,
        config.payout.amount_dkk,
        args.week,
    )
    output_file = write_weekly_results(
        result,
        config.league.season,
        week,
        config.data.result_path,
    )
    logger.info("Updated weekly challenge CSV at %s.", output_file)
    image_file = write_weekly_challenge_image(
        result,
        config.league.season,
        week,
        config.data.result_path,
    )
    print(output_file)
    print(image_file)
    logger.info("Weekly fantasy challenge run completed.")


if __name__ == "__main__":
    main()
