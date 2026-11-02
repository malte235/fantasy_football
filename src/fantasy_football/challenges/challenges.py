import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, cast

from espn_api.football import League  # type: ignore[import-not-found]

Operation = Literal["subtract", "absolute_difference"]
RankOrder = Literal["ascending", "descending"]
Side = tuple[str, float, float, list[Any]]
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChallengeCandidate:
    """A team's eligibility and the two values used by a challenge."""

    team: str
    value_1: float | None
    value_2: float | None = 0.0
    players: tuple[str, ...] = ()
    details: str | None = None


@dataclass(frozen=True, slots=True)
class ChallengePlacement:
    """One team's eligibility, calculation inputs, and ranked result."""

    place: int | None
    team: str
    eligible: bool
    value_1: float | None
    value_2: float | None
    difference: float | None
    players: tuple[str, ...] = ()
    details: str | None = None
    payout_dkk: float = 0.0

    @property
    def value(self) -> float | None:
        """Compatibility alias for the challenge's calculated difference."""
        return self.difference


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    """Challenge calculation metadata and ranked team results."""

    challenge: str
    value_1_label: str
    value_2_label: str
    operation: Operation
    rank_order: RankOrder
    placements: tuple[ChallengePlacement, ...]
    is_final: bool = True
    needs_additional_data: bool = False
    note: str | None = None


class Challenges:
    """Container for fantasy football challenge logic."""

    def __init__(self, league_data: League):
        self.league_data = league_data

    def execute(
        self,
        challenges_by_week: Mapping[int, str],
        payout_amount_dkk: int,
        week_override: int | None = None,
    ) -> tuple[int, ChallengeResult]:
        """Run the configured weekly challenge and apply its payout."""
        if week_override is None:
            week = int(cast(Any, self.league_data).current_week)
            logger.info("ESPN reports current scoring week %s.", week)
        else:
            week = week_override
            logger.info("Using requested scoring week %s.", week)

        challenge_name = challenges_by_week.get(week)
        if challenge_name is None:
            configured_weeks = sorted(challenges_by_week)
            logger.error(
                "No challenge configured for week %s; configured weeks are %s.",
                week,
                configured_weeks,
            )
            raise ValueError(
                f"ESPN reported scoring week {week}, but no challenge is configured "
                f"for it. Configured weeks: {configured_weeks}."
            )

        logger.info("Selected challenge %s for week %s.", challenge_name, week)
        runner = getattr(self, challenge_name)
        logger.info("Running challenge %s for week %s.", challenge_name, week)
        result = self._apply_payout(runner(week), payout_amount_dkk)
        logger.info(
            "Challenge %s completed for week %s (final=%s, needs_additional_data=%s).",
            challenge_name,
            week,
            result.is_final,
            result.needs_additional_data,
        )
        return week, result

    @staticmethod
    def _apply_payout(result: ChallengeResult, amount_dkk: int) -> ChallengeResult:
        """Split the payout evenly between every first-place team."""
        first_place_count = sum(
            placement.place == 1 and placement.difference is not None
            for placement in result.placements
        )
        per_winner_payout = (
            (Decimal(amount_dkk) / first_place_count).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if first_place_count
            else Decimal("0.00")
        )
        placements = tuple(
            replace(
                placement,
                payout_dkk=float(
                    per_winner_payout
                    if placement.place == 1 and placement.difference is not None
                    else Decimal("0.00")
                ),
            )
            for placement in result.placements
        )
        logger.info(
            "Payout is %s DKK per first-place team (%s first-place teams).",
            per_winner_payout,
            first_place_count,
        )
        return replace(result, placements=placements)

    def _box_scores(self, week: int) -> list[Any]:
        return cast(list[Any], cast(Any, self.league_data).box_scores(week))

    @staticmethod
    def _sides(box_scores: list[Any]) -> list[Side]:
        sides: list[Side] = []
        for box_score in box_scores:
            for side in ("home", "away"):
                team = getattr(box_score, f"{side}_team", None)
                if team is None:
                    continue
                sides.append(
                    (
                        str(getattr(team, "team_name", team)),
                        float(getattr(box_score, f"{side}_score", 0)),
                        float(getattr(box_score, f"{side}_projected", 0)),
                        list(getattr(box_score, f"{side}_lineup", [])),
                    )
                )
        return sides

    @staticmethod
    def _team_id(team: Any) -> int | None:
        team_id = getattr(team, "team_id", None)
        return int(team_id) if team_id is not None else None

    def _league_team_names(self) -> list[str]:
        teams = cast(list[Any], getattr(cast(Any, self.league_data), "teams", []))
        return list(
            dict.fromkeys(str(getattr(team, "team_name", team)) for team in teams)
        )

    def _include_unavailable_league_teams(
        self, candidates: list[ChallengeCandidate]
    ) -> list[ChallengeCandidate]:
        candidate_teams = {candidate.team for candidate in candidates}
        candidates.extend(
            ChallengeCandidate(team, None, None)
            for team in self._league_team_names()
            if team not in candidate_teams
        )
        return candidates

    @staticmethod
    def _is_starter(player: Any) -> bool:
        return getattr(player, "slot_position", "FA") not in {"BE", "IR", "FA", ""}

    @staticmethod
    def _stat(player: Any, stat_name: str) -> float:
        return float(getattr(player, "breakdown", {}).get(stat_name, 0) or 0)

    def _rank(
        self,
        challenge: str,
        value_1_label: str,
        value_2_label: str,
        candidates: list[ChallengeCandidate],
        *,
        operation: Operation = "subtract",
        rank_order: RankOrder = "descending",
        is_final: bool = True,
        needs_additional_data: bool = False,
        note: str | None = None,
    ) -> ChallengeResult:
        team_names = self._league_team_names()
        for candidate in candidates:
            if candidate.team not in team_names:
                team_names.append(candidate.team)
        candidates_by_team = {candidate.team: candidate for candidate in candidates}

        calculated: list[tuple[ChallengeCandidate, float]] = []
        for candidate in candidates:
            if candidate.value_1 is None or candidate.value_2 is None:
                continue
            difference = candidate.value_1 - candidate.value_2
            if operation == "absolute_difference":
                difference = abs(difference)
            calculated.append((candidate, round(difference, 2)))
        calculated.sort(
            key=lambda entry: entry[1],
            reverse=rank_order == "descending",
        )

        placements: list[ChallengePlacement] = []
        ranked_teams: set[str] = set()
        previous_difference: float | None = None
        place = 0
        for index, (candidate, difference) in enumerate(calculated, start=1):
            if difference != previous_difference:
                place = index
                previous_difference = difference
            placements.append(
                ChallengePlacement(
                    place,
                    candidate.team,
                    True,
                    candidate.value_1,
                    candidate.value_2,
                    difference,
                    candidate.players,
                    candidate.details,
                )
            )
            ranked_teams.add(candidate.team)

        for team in team_names:
            if team in ranked_teams:
                continue
            candidate = candidates_by_team.get(team)
            placements.append(
                ChallengePlacement(
                    place + 1 if calculated else 1,
                    team,
                    candidate is not None,
                    candidate.value_1 if candidate else None,
                    candidate.value_2 if candidate else None,
                    None,
                    candidate.players if candidate else (),
                    candidate.details if candidate else None,
                )
            )

        return ChallengeResult(
            challenge,
            value_1_label,
            value_2_label,
            operation,
            rank_order,
            tuple(placements),
            is_final,
            needs_additional_data,
            note,
        )

    @staticmethod
    def _best_player_per_team(
        sides: list[Side],
        eligible: Callable[[Any], bool],
        score: Callable[[Any], float],
        *,
        descending: bool = True,
        reference_value: float = 0.0,
        closest_to: float | None = None,
    ) -> list[ChallengeCandidate]:
        candidates: list[ChallengeCandidate] = []
        for team, _, _, lineup in sides:
            performances = [
                (float(score(player)), str(getattr(player, "name", "Unknown")))
                for player in lineup
                if eligible(player)
            ]
            if not performances:
                continue
            if closest_to is None:
                best_value = (max if descending else min)(
                    value for value, _ in performances
                )
                best_values = {best_value}
            else:
                best_distance = min(
                    abs(value - closest_to) for value, _ in performances
                )
                best_values = {
                    value
                    for value, _ in performances
                    if abs(value - closest_to) == best_distance
                }
                best_value = next(
                    value for value, _ in performances if value in best_values
                )
            player_names = tuple(
                sorted(name for value, name in performances if value in best_values)
            )
            candidates.append(
                ChallengeCandidate(
                    team,
                    best_value,
                    reference_value,
                    player_names,
                )
            )
        return candidates

    def highest_scoring_team(self, week: int) -> ChallengeResult:
        """Rank all teams by their weekly score."""
        candidates = [
            ChallengeCandidate(team, score)
            for team, score, _, _ in self._sides(self._box_scores(week))
        ]
        candidates = self._include_unavailable_league_teams(candidates)
        return self._rank("Top Scorer", "team points", "baseline", candidates)

    def blackjack(self, week: int) -> ChallengeResult:
        """Rank teams by their best starter score at or below 21, excluding DST."""
        sides = self._sides(self._box_scores(week))
        candidates = self._best_player_per_team(
            sides,
            lambda player: (
                self._is_starter(player)
                and getattr(player, "position", "") != "D/ST"
                and getattr(player, "slot_position", "") != "D/ST"
                and float(getattr(player, "points", 0)) <= 21
            ),
            lambda player: float(getattr(player, "points", 0)),
        )
        return self._rank(
            "Blackjack",
            "best eligible starter points",
            "baseline",
            candidates,
        )

    def show_me_your_tds(self, week: int) -> ChallengeResult:
        """Rank teams by the sum of player touchdown stat categories."""
        touchdown_stats = (
            "passingTouchdowns",
            "rushingTouchdowns",
            "receivingTouchdowns",
            "fumbleRecoveredForTD",
            "defensiveTouchdowns",
            "defensiveBlockedKickForTouchdowns",
            "kickoffReturnTouchdowns",
            "puntReturnTouchdowns",
            "interceptionReturnTouchdowns",
            "fumbleReturnTouchdowns",
        )
        candidates: list[ChallengeCandidate] = []
        for team, _, _, lineup in self._sides(self._box_scores(week)):
            touchdown_total = sum(
                self._stat(player, stat_name)
                for player in lineup
                if self._is_starter(player)
                for stat_name in touchdown_stats
            )
            candidates.append(ChallengeCandidate(team, touchdown_total))
        candidates = self._include_unavailable_league_teams(candidates)
        return self._rank(
            "Show me your TDs",
            "starter touchdown total",
            "baseline",
            candidates,
        )

    def _transactions(self, periods: range, types: set[str]) -> list[Any]:
        transactions: list[Any] = []
        for scoring_period in periods:
            try:
                period_transactions = cast(Any, self.league_data).transactions(
                    scoring_period=scoring_period,
                    types=types,
                )
            except Exception as error:
                if str(error) == "No transactions found":
                    continue
                raise
            transactions.extend(period_transactions)
        return transactions

    def waiver_wizard(self, week: int) -> ChallengeResult:
        """Rank started free-agent/waiver additions acquired after week 3."""
        if week <= 3:
            return self._rank(
                "Waiver Wizard",
                "picked-up starter points",
                "baseline",
                [],
            )
        acquired: set[tuple[int, int]] = set()
        for transaction in self._transactions(
            range(4, week + 1), {"FREEAGENT", "WAIVER"}
        ):
            team_id = self._team_id(getattr(transaction, "team", None))
            if team_id is None:
                continue
            for item in getattr(transaction, "items", []):
                item_type = str(getattr(item, "type", "")).upper()
                if "DROP" in item_type:
                    continue
                player_id = getattr(item, "playerId", None)
                if player_id is not None:
                    acquired.add((team_id, int(player_id)))

        candidates: list[ChallengeCandidate] = []
        for box_score in self._box_scores(week):
            for side in ("home", "away"):
                team_object = getattr(box_score, f"{side}_team", None)
                if team_object is None:
                    continue
                team_id = self._team_id(team_object)
                if team_id is None:
                    continue
                team = str(getattr(team_object, "team_name", team_object))
                lineup = list(getattr(box_score, f"{side}_lineup", []))
                performances = [
                    (
                        float(getattr(player, "points", 0)),
                        str(getattr(player, "name", "Unknown")),
                    )
                    for player in lineup
                    if self._is_starter(player)
                    and (team_id, int(getattr(player, "playerId", -1))) in acquired
                ]
                if performances:
                    best_value = max(value for value, _ in performances)
                    names = tuple(
                        sorted(
                            name for value, name in performances if value == best_value
                        )
                    )
                    candidates.append(
                        ChallengeCandidate(team, best_value, players=names)
                    )
        return self._rank(
            "Waiver Wizard",
            "picked-up starter points",
            "baseline",
            candidates,
        )

    def largest_margin_winners(self, week: int) -> ChallengeResult:
        """Rank winning teams by the difference between their scores."""
        candidates: list[ChallengeCandidate] = []
        for box_score in self._box_scores(week):
            home_team = getattr(box_score, "home_team", None)
            away_team = getattr(box_score, "away_team", None)
            if home_team is None or away_team is None:
                continue
            home_score = float(box_score.home_score)
            away_score = float(box_score.away_score)
            if home_score == away_score:
                continue
            winner, winner_score, loser_score = (
                (home_team, home_score, away_score)
                if home_score > away_score
                else (away_team, away_score, home_score)
            )
            candidates.append(
                ChallengeCandidate(
                    str(winner.team_name),
                    winner_score,
                    loser_score,
                )
            )
        return self._rank(
            "Blow Out",
            "winning team points",
            "opponent points",
            candidates,
        )

    def over_achiever(self, week: int) -> ChallengeResult:
        """Rank teams by points scored over projection."""
        candidates = [
            ChallengeCandidate(team, score, projected)
            for team, score, projected, _ in self._sides(self._box_scores(week))
        ]
        candidates = self._include_unavailable_league_teams(candidates)
        return self._rank(
            "Over Achiever",
            "team points",
            "projected team points",
            candidates,
        )

    def consolation_prize(self, week: int) -> ChallengeResult:
        """Rank teams by their largest positive bench-versus-starter score gap."""
        candidates: list[ChallengeCandidate] = []
        flex_slots = {"FLEX", "RB/WR", "WR/TE", "RB/WR/TE"}
        flex_positions = {"RB", "WR", "TE"}
        for team, _, _, lineup in self._sides(self._box_scores(week)):
            starters = [player for player in lineup if self._is_starter(player)]
            bench = [
                player
                for player in lineup
                if getattr(player, "slot_position", "") == "BE"
            ]
            regrets: list[tuple[float, float, float, str, tuple[str, ...]]] = []
            for bench_player in bench:
                position = str(getattr(bench_player, "position", ""))
                if not position:
                    continue
                comparable = [
                    player
                    for player in starters
                    if getattr(player, "slot_position", "") == position
                    or (
                        position in flex_positions
                        and getattr(player, "slot_position", "") in flex_slots
                    )
                ]
                if not comparable:
                    continue
                lowest_starter = min(
                    float(getattr(player, "points", 0)) for player in comparable
                )
                lowest_starter_names = tuple(
                    str(getattr(player, "name", "Unknown"))
                    for player in comparable
                    if float(getattr(player, "points", 0)) == lowest_starter
                )
                bench_points = float(getattr(bench_player, "points", 0))
                difference = round(bench_points - lowest_starter, 2)
                if difference > 0:
                    regrets.append(
                        (
                            difference,
                            bench_points,
                            lowest_starter,
                            str(getattr(bench_player, "name", "Unknown")),
                            lowest_starter_names,
                        )
                    )
            if regrets:
                worst_gap = max(regret[0] for regret in regrets)
                candidates.append(
                    ChallengeCandidate(
                        team,
                        next(regret[1] for regret in regrets if regret[0] == worst_gap),
                        next(regret[2] for regret in regrets if regret[0] == worst_gap),
                        tuple(
                            sorted(
                                {
                                    player_name
                                    for regret in regrets
                                    if regret[0] == worst_gap
                                    for player_name in (regret[3], *regret[4])
                                }
                            )
                        ),
                    )
                )
        return self._rank(
            "Consolation Prize",
            "bench player points",
            "comparable starter points",
            candidates,
        )

    def defense_wins_championships(self, week: int) -> ChallengeResult:
        """Rank teams by their starting D/ST score."""
        candidates = self._best_player_per_team(
            self._sides(self._box_scores(week)),
            lambda player: getattr(player, "slot_position", "") == "D/ST",
            lambda player: float(getattr(player, "points", 0)),
        )
        return self._rank(
            "Defense Wins Championships",
            "starting D/ST points",
            "baseline",
            candidates,
        )

    def photo_finish(self, week: int) -> ChallengeResult:
        """Rank winning teams by their smallest winning-score difference."""
        candidates: list[ChallengeCandidate] = []
        for box_score in self._box_scores(week):
            home_team = getattr(box_score, "home_team", None)
            away_team = getattr(box_score, "away_team", None)
            if home_team is None or away_team is None:
                continue
            home_score = float(box_score.home_score)
            away_score = float(box_score.away_score)
            if home_score == away_score:
                continue
            winner, winner_score, loser_score = (
                (home_team, home_score, away_score)
                if home_score > away_score
                else (away_team, away_score, home_score)
            )
            candidates.append(
                ChallengeCandidate(
                    str(winner.team_name),
                    winner_score,
                    loser_score,
                )
            )
        return self._rank(
            "Photo Finish",
            "winning team points",
            "opponent points",
            candidates,
            rank_order="ascending",
        )

    def lederhosen_bowl(self, week: int) -> ChallengeResult:
        """Rank starters from the Patriots-Lions game by fantasy points."""
        candidates = self._best_player_per_team(
            self._sides(self._box_scores(week)),
            lambda player: (
                self._is_starter(player)
                and (
                    (
                        getattr(player, "proTeam", "") == "NE"
                        and getattr(player, "pro_opponent", "") == "DET"
                    )
                    or (
                        getattr(player, "proTeam", "") == "DET"
                        and getattr(player, "pro_opponent", "") == "NE"
                    )
                )
            ),
            lambda player: float(getattr(player, "points", 0)),
        )
        return self._rank(
            "Lederhosen Bowl",
            "Munich-game starter points",
            "baseline",
            candidates,
        )

    def art_of_the_deal(self, week: int) -> ChallengeResult:
        """Rank started players appearing in a pre-week trade transaction."""
        traded_player_ids = {
            int(item.playerId)
            for transaction in self._transactions(
                range(1, week), {"TRADE_ACCEPT", "TRADE_UPHOLD"}
            )
            for item in getattr(transaction, "items", [])
            if getattr(item, "playerId", None) is not None
        }
        candidates = self._best_player_per_team(
            self._sides(self._box_scores(week)),
            lambda player: (
                self._is_starter(player)
                and int(getattr(player, "playerId", -1)) in traded_player_ids
            ),
            lambda player: float(getattr(player, "points", 0)),
        )
        return self._rank(
            "Art of the Deal",
            "traded starter points",
            "baseline",
            candidates,
        )

    def biggest_loser(self, week: int) -> ChallengeResult:
        """Rank losing teams by their score."""
        candidates: list[ChallengeCandidate] = []
        for box_score in self._box_scores(week):
            home_team = getattr(box_score, "home_team", None)
            away_team = getattr(box_score, "away_team", None)
            if home_team is None or away_team is None:
                continue
            home_score = float(box_score.home_score)
            away_score = float(box_score.away_score)
            if home_score == away_score:
                continue
            loser, losing_score = (
                (home_team, home_score)
                if home_score < away_score
                else (away_team, away_score)
            )
            candidates.append(ChallengeCandidate(str(loser.team_name), losing_score))
        return self._rank(
            "Biggest Loser",
            "losing team points",
            "baseline",
            candidates,
        )

    def bulls_eye(self, week: int) -> ChallengeResult:
        """Rank teams by absolute distance from their projected score."""
        candidates = [
            ChallengeCandidate(team, score, projected)
            for team, score, projected, _ in self._sides(self._box_scores(week))
        ]
        candidates = self._include_unavailable_league_teams(candidates)
        return self._rank(
            "Bulls-eye",
            "team points",
            "projected team points",
            candidates,
            operation="absolute_difference",
            rank_order="ascending",
        )

    def gone_but_not_forgotten(self, week: int = 14) -> ChallengeResult:
        """Rank teams seeded 7-12 after the requested week's standings."""
        standings = cast(list[Any], cast(Any, self.league_data).standings_weekly(week))
        eligible_teams: dict[int, str] = {}
        for place, team in enumerate(standings, start=1):
            team_id = self._team_id(team)
            if 7 <= place <= 12 and team_id is not None:
                eligible_teams[team_id] = str(getattr(team, "team_name", team))

        team_scores: dict[int, float] = {}
        for box_score in self._box_scores(week):
            for side in ("home", "away"):
                team = getattr(box_score, f"{side}_team", None)
                team_id = self._team_id(team)
                if team_id is not None:
                    team_scores[team_id] = float(getattr(box_score, f"{side}_score", 0))
        candidates = [
            ChallengeCandidate(
                team,
                team_scores.get(team_id),
            )
            for team_id, team in eligible_teams.items()
        ]
        return self._rank(
            "Gone but not forgotten",
            "team points",
            "baseline",
            candidates,
        )

    def legatron(self, week: int) -> ChallengeResult:
        """Return provisional longest-field-goal candidates from ESPN distance buckets."""
        thresholds = (
            ("madeFieldGoalsFrom60Plus", 60),
            ("madeFieldGoalsFrom50Plus", 50),
            ("madeFieldGoalsFrom40To49", 40),
            ("madeFieldGoalsFromUnder40", 0),
        )
        candidates: list[ChallengeCandidate] = []
        for team, _, _, lineup in self._sides(self._box_scores(week)):
            field_goals: list[tuple[float, str, int]] = []
            for player in lineup:
                if not self._is_starter(player):
                    continue
                for stat_name, threshold in thresholds:
                    if self._stat(player, stat_name) > 0:
                        field_goals.append(
                            (
                                float(threshold),
                                str(getattr(player, "name", "Unknown")),
                                threshold,
                            )
                        )
                        break
            if field_goals:
                best_threshold = max(value for value, _, _ in field_goals)
                names = tuple(
                    sorted(
                        name
                        for value, name, _ in field_goals
                        if value == best_threshold
                    )
                )
                candidates.append(
                    ChallengeCandidate(
                        team,
                        best_threshold,
                        players=names,
                        details=(
                            f"At least {int(best_threshold)} yards; exact kick "
                            "distance unavailable."
                        ),
                    )
                )
        return self._rank(
            "Legatron",
            "field-goal distance lower bound (yards)",
            "baseline",
            candidates,
            is_final=False,
            needs_additional_data=True,
            note="ESPN provides distance buckets, not the exact distance of each made kick.",
        )

    def sweet_sixteen(self, week: int) -> ChallengeResult:
        """Rank teams by their starter closest to 16 points, excluding DST."""
        candidates = self._best_player_per_team(
            self._sides(self._box_scores(week)),
            lambda player: (
                self._is_starter(player)
                and getattr(player, "position", "") != "D/ST"
                and getattr(player, "slot_position", "") != "D/ST"
            ),
            lambda player: float(getattr(player, "points", 0)),
            descending=False,
            reference_value=16.0,
            closest_to=16.0,
        )
        return self._rank(
            "Sweet 16",
            "starter points",
            "target points",
            candidates,
            operation="absolute_difference",
            rank_order="ascending",
        )

    def hail_mary(self, week: int) -> ChallengeResult:
        """Return provisional candidates: starting QBs who threw a TD this week."""
        candidates: list[ChallengeCandidate] = []
        for team, _, _, lineup in self._sides(self._box_scores(week)):
            qbs = [
                player
                for player in lineup
                if self._is_starter(player)
                and getattr(player, "position", "") == "QB"
                and self._stat(player, "passingTouchdowns") > 0
            ]
            if qbs:
                candidates.append(
                    ChallengeCandidate(
                        team,
                        None,
                        None,
                        tuple(
                            sorted(
                                str(getattr(player, "name", "Unknown"))
                                for player in qbs
                            )
                        ),
                        "Starting QB threw a passing TD; TD distance is unavailable.",
                    )
                )
        return self._rank(
            "Hail Mary",
            "passing touchdown distance",
            "baseline",
            candidates,
            is_final=False,
            needs_additional_data=True,
            note="ESPN's player stats do not include play-level touchdown distances.",
        )
