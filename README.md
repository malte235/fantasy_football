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
To run several configured weeks in one process, list them with
`uv run fantasy-football --weeks 1 2 3`. The league client is initialized once,
and data fetched for a week or transaction period is reused for subsequent
challenge runs in that process. ESPN's client still makes separate requests
for different weeks and transaction periods; it does not provide a bulk
multi-week endpoint.
For a scheduled run after the scoring week completes, use
`uv run fantasy-football --previous-week`; it selects the week before ESPN's
current scoring week each time it runs. The previous week must have an
assignment in the `challenges` section.
The `data.result_path` setting controls where result CSV files are written; its
default is `data/results`, relative to the current working directory. Each
season is stored in `challenge_rankings_weekly_<season>.csv`. Running a week
again replaces that week's rows, while rows for other weeks remain intact and
the file is kept in week/rank order.
After writing the CSV, the CLI also creates a shareable PNG leaderboard at
`images/weekly_challenge_<season>_week_<week>.png` within the results directory.
The portrait layout uses a fixed 9:19.5 phone aspect ratio and fits the full
12-team leaderboard on one screen. For matchup-based challenges, each row shows
the opponent beside its points. Blow Out ranks all non-tied teams by signed
margin; unqualified teams in other matchup challenges show both point totals
without a score.
It reads the week's name, description, and excluded positions from
`data/raw/challenge_descriptions.csv`; the image includes eligible teams, their
challenge scores, calculation values, player names, and payouts. Unqualified
matchup rows still show both teams' points.
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

Challenge CSV rows include team eligibility, the opposing team when applicable,
both calculation inputs, the operation and rank order, placement, and payout.
Head-to-head challenges show team points and opponent points. Blow Out scores
each team by its signed margin. Other ineligible matchup teams share the place
after the scored results, with their score left blank.
The `players` cell is a JSON array of objects containing each player's name,
associated value, and value label. Teams without a scored result share the place immediately after the
lowest scored place (or first place if no team has a score); their unavailable
calculations remain blank. Only scored first-place results receive a payout.
Results can be provisional when required ESPN values are unavailable. Weeks
outside the configured 1–17 challenge schedule fail with an explicit error
rather than running a different week's challenge.