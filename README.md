# fantasy_football

## Weekly challenge

Run the challenge locally with `uv run fantasy-football`.

The league ID, season, and week-to-challenge assignment are in
[`config/config.yaml`](./config/config.yaml). The config is validated with
Pydantic when the program starts. For a private ESPN league, provide cookies
with the `FANTASY_ESPN_S2` and `FANTASY_SWID` environment variables. You can
point the CLI at another YAML file with
`uv run fantasy-football --config path/to/config.yaml`.
To run a specific past scoring week, use `uv run fantasy-football --week 5`.
The requested week must have an assignment in the `challenges` section.
The `data.result_path` setting controls where result CSV files are written; its
default is `data/results`, relative to the current working directory. Each
season is stored in `challenge_rankings_weekly_<season>.csv`. Running a week
again replaces that week's rows, while rows for other weeks remain intact and
the file is kept in week/rank order.
After writing the CSV, the CLI also creates a shareable PNG leaderboard at
`images/weekly_challenge_<season>_week_<week>.png` within the results directory.
It reads the week's name, description, and excluded positions from
`data/raw/challenge_descriptions.csv`; the image includes eligible teams, their
challenge scores and player names, and payouts.
The configured `payout.amount_dkk` is a positive integer and is split evenly
across all teams tied for first place. Each team's `payout_dkk` is rounded to
two decimal places using round-half-up; other placements receive `0.00` DKK.

The application logs pipeline progress to stderr at `INFO` level. It logs the
raw YAML before validation and the parsed, Pydantic-validated configuration
afterwards, followed by ESPN initialization, week/challenge selection,
challenge execution, and CSV/image writing. The CLI prints both output paths.
Do not put credentials or other secrets in the YAML config; use environment
variables instead.

The CLI entry point and config loading are in `src/fantasy_football/main.py`.
The `Challenges.execute()` method selects and runs the configured challenge,
applies the payout, and returns the complete challenge result.

Edit the numeric week keys in the `challenges` section to change assignments;
challenge names are validated against the supported challenge list. Update the
`league.season` value for each new NFL season.

Challenge CSV rows include team eligibility, both calculation inputs, the
operation and rank order, placement, player names, and payout. Teams without a
scored result share the place immediately after the lowest scored place (or
first place if no team has a score); their unavailable calculations remain
blank. Only scored first-place results receive a payout. Results can be
provisional when required ESPN values are unavailable. Weeks outside the
configured 1–17 challenge schedule fail with an explicit error rather than
running a different week's challenge.