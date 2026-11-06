from types import SimpleNamespace
from typing import Any, cast

from fantasy_football.challenges.challenges import Challenges


def make_team(team_id: int, name: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(team_id=team_id, team_name=name or f"Team {team_id}")


def make_player(
    player_id: int,
    name: str,
    points: float,
    position: str,
    *,
    slot: str | None = None,
    stats: dict[str, Any] | None = None,
    pro_team: str = "",
    pro_opponent: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        playerId=player_id,
        name=name,
        points=points,
        position=position,
        slot_position=slot or position,
        breakdown=stats or {},
        proTeam=pro_team,
        pro_opponent=pro_opponent,
    )


def make_box(
    home_team: SimpleNamespace,
    away_team: SimpleNamespace,
    home_score: float,
    away_score: float,
    *,
    home_projected: float | None = None,
    away_projected: float | None = None,
    home_lineup: list[SimpleNamespace] | None = None,
    away_lineup: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        home_projected=home_score if home_projected is None else home_projected,
        away_projected=away_score if away_projected is None else away_projected,
        home_lineup=home_lineup or [],
        away_lineup=away_lineup or [],
    )


class FakeLeague:
    def __init__(self, box_scores=None, standings=None, transactions=None):
        self._box_scores = box_scores or []
        self._standings = standings or []
        self._transactions = transactions or {}
        self.teams = []
        team_ids = set()
        for box_score in self._box_scores:
            for side in ("home", "away"):
                team = getattr(box_score, f"{side}_team", None)
                if team is not None and team.team_id not in team_ids:
                    self.teams.append(team)
                    team_ids.add(team.team_id)
        self.box_score_calls = 0
        self.transaction_calls = []
        self.standings_calls = []

    def box_scores(self, week, player_team_cache=None):
        self.box_score_calls += 1
        return self._box_scores

    def standings_weekly(self, week):
        self.standings_calls.append(week)
        return self._standings

    def transactions(self, scoring_period, types):
        self.transaction_calls.append((scoring_period, types))
        period_transactions = self._transactions.get(scoring_period, [])
        if isinstance(period_transactions, Exception):
            raise period_transactions
        return [
            transaction
            for transaction in period_transactions
            if transaction.type in types
        ]


def make_challenges(league: FakeLeague) -> Challenges:
    return Challenges(cast(Any, league))


def test_score_margin_and_tied_cutoff_rankings():
    home = make_team(1)
    away = make_team(2)
    other_home = make_team(3)
    other_away = make_team(4)
    league = FakeLeague(
        [
            make_box(home, away, 110, 100),
            make_box(other_home, other_away, 100, 95),
        ]
    )
    challenges = make_challenges(league)

    assert [entry.team for entry in challenges.highest_scoring_team(1).placements] == [
        "Team 1",
        "Team 2",
        "Team 3",
        "Team 4",
    ]
    assert challenges.largest_margin_winners(1).placements[0].team == "Team 1"
    assert challenges.largest_margin_winners(1).placements[0].opponent_team == "Team 2"
    blow_out_loser = next(
        entry
        for entry in challenges.largest_margin_winners(1).placements
        if entry.team == "Team 2"
    )
    assert blow_out_loser.opponent_team == "Team 1"
    assert challenges.photo_finish(1).placements[0].team == "Team 3"
    assert challenges.photo_finish(1).placements[0].opponent_team == "Team 4"
    assert challenges.biggest_loser(1).placements[0].team == "Team 2"
    assert challenges.biggest_loser(1).placements[0].opponent_team == "Team 1"
    biggest_loser = challenges.biggest_loser(1).placements[0]
    assert (biggest_loser.value_1, biggest_loser.value_2, biggest_loser.difference) == (
        100,
        110,
        -10,
    )
    biggest_winner = next(
        entry
        for entry in challenges.biggest_loser(1).placements
        if entry.team == "Team 1"
    )
    assert biggest_winner.opponent_team == "Team 2"
    assert not biggest_winner.eligible
    assert (
        biggest_winner.value_1,
        biggest_winner.value_2,
        biggest_winner.difference,
    ) == (110, 100, None)

    tied_league = FakeLeague(
        [
            make_box(make_team(index * 2), make_team(index * 2 + 1), 10, 10)
            for index in range(7)
        ]
    )
    tied = make_challenges(tied_league).highest_scoring_team(1).placements
    assert len(tied) == 14
    assert {entry.place for entry in tied} == {1}


def test_challenge_instance_reuses_box_scores_for_the_same_week():
    league = FakeLeague([make_box(make_team(1), make_team(2), 110, 100)])
    challenges = make_challenges(league)

    challenges.highest_scoring_team(1)
    challenges.highest_scoring_team(1)

    assert league.box_score_calls == 1


def test_challenge_instance_reuses_transactions_across_overlapping_weeks():
    league = FakeLeague()
    challenges = make_challenges(league)
    transaction_types = {"FREEAGENT", "WAIVER"}

    challenges._transactions(range(4, 5), transaction_types)
    challenges._transactions(range(4, 6), transaction_types)

    assert league.transaction_calls == [
        (4, transaction_types),
        (5, transaction_types),
    ]


def test_all_team_challenges_keep_teams_eligible_when_their_score_is_unavailable():
    home = make_team(1)
    away = make_team(2)
    missing_box_score_team = make_team(3)
    league = FakeLeague([make_box(home, away, 100, 90)])
    league.teams.append(missing_box_score_team)

    result = make_challenges(league).highest_scoring_team(1)
    missing_team = next(
        placement for placement in result.placements if placement.team == "Team 3"
    )

    assert missing_team.eligible is True
    assert missing_team.value_1 is None
    assert missing_team.value_2 is None
    assert missing_team.difference is None
    assert missing_team.place == 3


def test_player_score_projection_touchdown_and_defense_challenges():
    home_qb = make_player(1, "Home QB", 21, "QB", stats={"passingTouchdowns": 2})
    home_rb = make_player(2, "Home RB", 16, "RB", stats={"rushingTouchdowns": 1})
    home_dst = make_player(3, "Home DST", 25, "D/ST")
    away_qb = make_player(4, "Away QB", 22, "QB", stats={"passingTouchdowns": 1})
    away_rb = make_player(5, "Away RB", 18, "RB")
    away_dst = make_player(6, "Away DST", 4, "D/ST")
    league = FakeLeague(
        [
            make_box(
                make_team(1),
                make_team(2),
                100,
                90,
                home_projected=90,
                away_projected=100,
                home_lineup=[home_qb, home_rb, home_dst],
                away_lineup=[away_qb, away_rb, away_dst],
            )
        ]
    )
    challenges = make_challenges(league)

    assert challenges.blackjack(1).placements[0].players == ("Home QB",)
    assert challenges.show_me_your_tds(1).placements[0].team == "Team 1"
    assert challenges.show_me_your_tds(1).placements[0].value == 3
    assert challenges.over_achiever(1).placements[0].team == "Team 1"
    assert challenges.defense_wins_championships(1).placements[0].team == "Team 1"
    assert challenges.sweet_sixteen(1).placements[0].players == ("Home RB",)
    assert challenges.bulls_eye(1).placements[0].place == 1
    top_scorer = challenges.highest_scoring_team(1)
    assert all(entry.eligible for entry in top_scorer.placements)
    assert (
        top_scorer.placements[0].value_1,
        top_scorer.placements[0].value_2,
        top_scorer.placements[0].difference,
    ) == (100, 0.0, 100)
    assert top_scorer.operation == "subtract"
    assert top_scorer.rank_order == "descending"


def test_consolation_prize_compares_skill_players_to_flex():
    home_lineup = [
        make_player(1, "Starting RB", 10, "RB"),
        make_player(2, "Starting TE", 5, "TE", slot="RB/WR/TE"),
        make_player(3, "Bench WR", 15, "WR", slot="BE"),
    ]
    league = FakeLeague(
        [make_box(make_team(1), make_team(2), 50, 40, home_lineup=home_lineup)]
    )

    result = make_challenges(league).consolation_prize(1).placements

    assert result[0].team == "Team 1"
    assert result[0].value == 10
    assert result[0].players == ("Bench WR", "Starting TE")


def test_transaction_challenges_filter_started_players_and_fetch_once():
    team = make_team(1)
    waiver_player = make_player(100, "Waiver RB", 20, "RB")
    trade_player = make_player(200, "Traded WR", 18, "WR")
    waiver_transaction = SimpleNamespace(
        type="WAIVER",
        team=team,
        items=[SimpleNamespace(type="ADD", playerId=100)],
    )
    trade_transaction = SimpleNamespace(
        type="TRADE_ACCEPT",
        team=team,
        items=[SimpleNamespace(type="TRADED", playerId=200)],
    )
    league = FakeLeague(
        [
            make_box(
                team,
                make_team(2),
                70,
                60,
                home_lineup=[waiver_player, trade_player],
            )
        ],
        transactions={4: [waiver_transaction], 3: [trade_transaction]},
    )
    challenges = make_challenges(league)

    waiver_result = challenges.waiver_wizard(4)
    assert waiver_result.placements[0].players == ("Waiver RB",)
    assert league.box_score_calls == 1
    assert challenges.art_of_the_deal(4).placements[0].players == ("Traded WR",)


def test_standings_filter_and_provisional_play_detail_results():
    teams = [make_team(index) for index in range(1, 15)]
    boxes = [
        make_box(teams[index], teams[index + 1], 100 - index, 90 - index)
        for index in range(0, 14, 2)
    ]
    kicker = make_player(
        30,
        "Kicker",
        12,
        "K",
        stats={"madeFieldGoalsFrom50Plus": 1},
    )
    qb = make_player(31, "QB", 24, "QB", stats={"passingTouchdowns": 1})
    boxes[0].home_lineup = [kicker, qb]
    league = FakeLeague(boxes, standings=teams)
    challenges = make_challenges(league)

    eligible = challenges.gone_but_not_forgotten(14).placements
    assert len(eligible) == 14
    assert {entry.team for entry in eligible if entry.eligible} == {
        f"Team {team_id}" for team_id in range(7, 13)
    }
    assert all(
        not entry.eligible
        and entry.value_1 is None
        and entry.value_2 is None
        and entry.difference is None
        and entry.place == 7
        and not entry.players
        for entry in eligible
        if entry.team in {f"Team {team_id}" for team_id in (*range(1, 7), 13, 14)}
    )
    field_goal_result = challenges.legatron(1)
    assert field_goal_result.is_final is False
    assert field_goal_result.needs_additional_data is True
    assert field_goal_result.placements[0].value == 50
    passing_result = challenges.hail_mary(1)
    assert passing_result.is_final is False
    assert passing_result.placements[0].players == ("QB",)


def test_munich_challenge_requires_the_patriots_lions_game():
    patriots_player = make_player(
        1, "Patriot", 22, "WR", pro_team="NE", pro_opponent="DET"
    )
    unrelated_player = make_player(
        2, "Other Patriot", 30, "WR", pro_team="NE", pro_opponent="BUF"
    )
    league = FakeLeague(
        [
            make_box(
                make_team(1),
                make_team(2),
                40,
                35,
                home_lineup=[patriots_player, unrelated_player],
            )
        ]
    )

    result = make_challenges(league).lederhosen_bowl(1).placements

    assert result[0].players == ("Patriot",)


def test_all_league_teams_are_returned_even_after_a_tied_twelfth_place():
    teams = [make_team(team_id) for team_id in range(1, 15)]
    scores = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 89, 80]
    boxes = [
        make_box(teams[index], teams[index + 1], scores[index], scores[index + 1])
        for index in range(0, len(teams), 2)
    ]

    placements = make_challenges(FakeLeague(boxes)).highest_scoring_team(1).placements

    assert len(placements) == 14
    assert placements[-1].place == 14
    assert {entry.value for entry in placements if entry.place == 12} == {89}
    assert placements[-1].value == 80


def test_blackjack_excludes_bench_dst_and_over_twenty_one_players():
    home_lineup = [
        make_player(1, "DST", 35, "D/ST"),
        make_player(2, "Over 21 QB", 22, "QB"),
        make_player(3, "Bench RB", 21, "RB", slot="BE"),
        make_player(4, "Starting RB", 19, "RB"),
    ]
    away_lineup = [make_player(5, "Eligible RB", 20, "RB")]
    league = FakeLeague(
        [
            make_box(
                make_team(1),
                make_team(2),
                60,
                55,
                home_lineup=home_lineup,
                away_lineup=away_lineup,
            )
        ]
    )

    placements = make_challenges(league).blackjack(1).placements

    assert [(entry.place, entry.team, entry.players) for entry in placements] == [
        (1, "Team 2", ("Eligible RB",)),
        (2, "Team 1", ("Starting RB",)),
    ]


def test_touchdown_total_sums_each_player_touchdown_category():
    touchdown_categories = {
        "passingTouchdowns": 1,
        "rushingTouchdowns": 2,
        "receivingTouchdowns": 1,
        "fumbleRecoveredForTD": 1,
        "defensiveTouchdowns": 1,
        "defensiveBlockedKickForTouchdowns": 1,
        "kickoffReturnTouchdowns": 1,
        "puntReturnTouchdowns": 1,
        "interceptionReturnTouchdowns": 1,
        "fumbleReturnTouchdowns": 1,
    }
    starter = make_player(1, "Starting Player", 0, "WR", stats=touchdown_categories)
    bench = make_player(
        2,
        "Bench Player",
        0,
        "WR",
        slot="BE",
        stats={stat_name: 100 for stat_name in touchdown_categories},
    )
    league = FakeLeague(
        [make_box(make_team(1), make_team(2), 10, 9, home_lineup=[starter, bench])]
    )

    result = make_challenges(league).show_me_your_tds(1).placements

    assert result[0].team == "Team 1"
    assert result[0].value == sum(touchdown_categories.values())


def test_blow_out_ranks_signed_margins_but_photo_finish_excludes_losers():
    boxes = [
        make_box(make_team(1), make_team(2), 105, 100),
        make_box(make_team(3), make_team(4), 100, 105),
        make_box(make_team(5), make_team(6), 102, 100),
        make_box(make_team(7), make_team(8), 100, 100),
    ]
    challenges = make_challenges(FakeLeague(boxes))

    blow_out = challenges.largest_margin_winners(1).placements
    photo_finish = challenges.photo_finish(1).placements

    assert [(entry.place, entry.value) for entry in blow_out[:6]] == [
        (1, 5),
        (1, 5),
        (3, 2),
        (4, -2),
        (5, -5),
        (5, -5),
    ]
    assert all(
        not entry.eligible
        and entry.place == 6
        and entry.difference is None
        and entry.value_1 is not None
        and entry.value_2 is not None
        for entry in blow_out[6:]
    )
    assert [(entry.place, entry.value) for entry in photo_finish[:3]] == [
        (1, 2),
        (2, 5),
        (2, 5),
    ]
    assert all(
        not entry.eligible
        and entry.place == 3
        and entry.difference is None
        and entry.value_1 is not None
        and entry.value_2 is not None
        for entry in photo_finish[3:]
    )
    loser = next(entry for entry in photo_finish if entry.team == "Team 2")
    assert (loser.value_1, loser.value_2, loser.difference) == (100, 105, None)


def test_head_to_head_ties_do_not_pay_ineligible_teams():
    league = FakeLeague([make_box(make_team(1), make_team(2), 10, 10)])

    result = make_challenges(league).largest_margin_winners(1)
    result = Challenges._apply_payout(result, 50)

    assert all(not placement.eligible for placement in result.placements)
    assert all(placement.difference is None for placement in result.placements)
    assert all(
        (placement.value_1, placement.value_2) == (10, 10)
        for placement in result.placements
    )
    assert all(placement.payout_dkk == 0 for placement in result.placements)


def test_projection_challenges_rank_over_and_absolute_difference_separately():
    boxes = [
        make_box(
            make_team(1), make_team(2), 110, 95, home_projected=100, away_projected=100
        ),
        make_box(
            make_team(3), make_team(4), 80, 100, home_projected=100, away_projected=90
        ),
    ]
    challenges = make_challenges(FakeLeague(boxes))

    over_achiever_result = challenges.over_achiever(1)
    overachievers = over_achiever_result.placements
    bulls_eye_result = challenges.bulls_eye(1)
    bulls_eye = bulls_eye_result.placements

    assert [(entry.team, entry.value) for entry in overachievers[:2]] == [
        ("Team 1", 10),
        ("Team 4", 10),
    ]
    assert (overachievers[0].place, overachievers[1].place) == (1, 1)
    assert (
        overachievers[0].value_1,
        overachievers[0].value_2,
        overachievers[0].difference,
    ) == (110, 100, 10)
    assert over_achiever_result.operation == "subtract"
    assert bulls_eye_result.operation == "absolute_difference"
    assert bulls_eye_result.rank_order == "ascending"
    assert (
        bulls_eye[0].value_1,
        bulls_eye[0].value_2,
        bulls_eye[0].difference,
    ) == (95, 100, 5)
    assert (bulls_eye[0].team, bulls_eye[0].value) == ("Team 2", 5)


def test_waiver_wizard_filters_drops_bench_players_and_wrong_team():
    home_team = make_team(1)
    away_team = make_team(2)
    home_starter = make_player(100, "Waiver Starter", 20, "RB")
    home_bench = make_player(101, "Waiver Bench", 40, "WR", slot="BE")
    away_player = make_player(102, "Other Team Pickup", 30, "TE")
    transactions = {
        3: [
            SimpleNamespace(
                type="WAIVER",
                team=home_team,
                items=[SimpleNamespace(type="ADD", playerId=102)],
            )
        ],
        4: [
            SimpleNamespace(
                type="WAIVER",
                team=home_team,
                items=[
                    SimpleNamespace(type="ADD", playerId=100),
                    SimpleNamespace(type="DROP", playerId=101),
                ],
            ),
            SimpleNamespace(
                type="FREEAGENT",
                team=away_team,
                items=[SimpleNamespace(type="ADD", playerId=102)],
            ),
        ],
    }
    league = FakeLeague(
        [
            make_box(
                home_team,
                away_team,
                60,
                55,
                home_lineup=[home_starter, home_bench],
                away_lineup=[away_player],
            )
        ],
        transactions=transactions,
    )
    challenges = make_challenges(league)

    placements = challenges.waiver_wizard(4).placements

    assert [(entry.team, entry.value, entry.players) for entry in placements] == [
        ("Team 2", 30, ("Other Team Pickup",)),
        ("Team 1", 20, ("Waiver Starter",)),
    ]
    assert [period for period, _ in league.transaction_calls] == [4]


def test_waiver_wizard_before_week_four_skips_data_requests():
    league = FakeLeague()

    result = make_challenges(league).waiver_wizard(3)

    assert result.placements == ()
    assert league.box_score_calls == 0
    assert league.transaction_calls == []


def test_empty_transaction_periods_are_ignored_but_other_errors_propagate():
    league = FakeLeague(transactions={4: Exception("No transactions found")})

    result = make_challenges(league).waiver_wizard(4)

    assert result.placements == ()
    assert league.box_score_calls == 1

    failing_league = FakeLeague(transactions={4: RuntimeError("request failed")})
    try:
        make_challenges(failing_league).waiver_wizard(4)
    except RuntimeError as error:
        assert str(error) == "request failed"
    else:
        raise AssertionError("unexpected transaction errors should propagate")


def test_trade_challenge_uses_only_pre_week_trades_and_started_players():
    team = make_team(1)
    prior_trade = make_player(200, "Prior Trade", 18, "WR")
    current_trade = make_player(201, "Current Week Trade", 30, "RB")
    bench_trade = make_player(202, "Bench Trade", 40, "TE", slot="BE")
    transactions = {
        3: [
            SimpleNamespace(
                type="TRADE_ACCEPT",
                team=team,
                items=[SimpleNamespace(type="TRADED", playerId=200)],
            )
        ],
        4: [
            SimpleNamespace(
                type="TRADE_ACCEPT",
                team=team,
                items=[SimpleNamespace(type="TRADED", playerId=201)],
            )
        ],
    }
    league = FakeLeague(
        [
            make_box(
                team,
                make_team(2),
                80,
                60,
                home_lineup=[prior_trade, current_trade, bench_trade],
            )
        ],
        transactions=transactions,
    )

    result = make_challenges(league).art_of_the_deal(4).placements

    assert result[0].players == ("Prior Trade",)
    assert result[0].value == 18
    assert [period for period, _ in league.transaction_calls] == [1, 2, 3]


def test_consolation_prize_returns_only_the_largest_positive_regret():
    lineup = [
        make_player(1, "Starting RB", 12, "RB"),
        make_player(2, "Starting WR", 8, "WR"),
        make_player(3, "Starting FLEX", 5, "TE", slot="RB/WR/TE"),
        make_player(4, "Bench RB", 15, "RB", slot="BE"),
        make_player(5, "Bench TE", 20, "TE", slot="BE"),
        make_player(6, "Bench Kicker", 30, "K", slot="BE"),
    ]
    league = FakeLeague(
        [make_box(make_team(1), make_team(2), 50, 40, home_lineup=lineup)]
    )

    result = make_challenges(league).consolation_prize(1).placements

    assert result[0].players == ("Bench TE", "Starting FLEX")
    assert result[0].player_values == (20.0, 5.0)
    assert result[0].player_value_indices == (1, 2)
    assert result[0].value == 15


def test_legatron_uses_highest_available_bucket_and_keeps_bucket_ties():
    home_kicker = make_player(
        1,
        "Home Kicker",
        12,
        "K",
        stats={"madeFieldGoalsFrom60Plus": 1, "madeFieldGoalsFrom50Plus": 2},
    )
    away_kicker = make_player(
        2, "Away Kicker", 10, "K", stats={"madeFieldGoalsFrom50Plus": 1}
    )
    bench_kicker = make_player(
        4,
        "Bench Kicker",
        30,
        "K",
        slot="BE",
        stats={"madeFieldGoalsFrom60Plus": 1},
    )
    other_kicker = make_player(
        3, "Other Kicker", 11, "K", stats={"madeFieldGoalsFrom50Plus": 1}
    )
    league = FakeLeague(
        [
            make_box(
                make_team(1),
                make_team(2),
                50,
                45,
                home_lineup=[home_kicker],
                away_lineup=[away_kicker, bench_kicker],
            ),
            make_box(make_team(3), make_team(4), 40, 35, home_lineup=[other_kicker]),
        ]
    )

    result = make_challenges(league).legatron(1).placements

    assert [(entry.place, entry.team, entry.value) for entry in result] == [
        (1, "Team 1", 60),
        (2, "Team 2", 50),
        (2, "Team 3", 50),
        (3, "Team 4", None),
    ]
    assert result[-1].eligible is False


def test_sweet_sixteen_compares_both_directions_and_excludes_dst_and_bench():
    home_lineup = [
        make_player(1, "Far Under 16", 4, "QB"),
        make_player(2, "Under 16", 14, "RB"),
        make_player(3, "DST Exact", 16, "D/ST"),
        make_player(4, "Bench Exact", 16, "WR", slot="BE"),
    ]
    away_lineup = [make_player(5, "Closest", 17, "WR")]
    league = FakeLeague(
        [
            make_box(
                make_team(1),
                make_team(2),
                50,
                45,
                home_lineup=home_lineup,
                away_lineup=away_lineup,
            )
        ]
    )

    result = make_challenges(league).sweet_sixteen(1).placements

    assert result[0].team == "Team 2"
    assert result[0].players == ("Closest",)
    assert result[0].value == 1
    assert result[1].players == ("Under 16",)
    assert result[1].value_1 == 14
    assert result[1].value_2 == 16
    assert result[1].difference == 2


def test_hail_mary_returns_only_starting_qbs_who_threw_a_touchdown():
    no_pass_td = make_player(1, "No Pass TD", 25, "QB", stats={"rushingTouchdowns": 1})
    bench_qb = make_player(
        2, "Bench QB", 30, "QB", slot="BE", stats={"passingTouchdowns": 2}
    )
    passing_qb = make_player(3, "Passing QB", 20, "QB", stats={"passingTouchdowns": 1})
    teams = [make_team(team_id) for team_id in range(1, 13)]
    boxes = [
        make_box(
            teams[index],
            teams[index + 1],
            60,
            55,
            home_lineup=[no_pass_td, bench_qb] if index == 0 else [],
            away_lineup=[passing_qb] if index == 0 else [],
        )
        for index in range(0, 12, 2)
    ]
    league = FakeLeague(boxes)

    result = make_challenges(league).hail_mary(17)

    assert result.is_final is False
    assert result.needs_additional_data is True
    assert len(result.placements) == 12
    assert (
        result.placements[0].team,
        result.placements[0].value,
        result.placements[0].players,
    ) == ("Team 1", None, ())
    assert result.placements[0].eligible is False
    assert (
        result.placements[1].team,
        result.placements[1].value,
        result.placements[1].players,
    ) == ("Team 2", None, ("Passing QB",))
    assert result.placements[1].eligible is True
    assert all(not placement.eligible for placement in result.placements[2:])


def test_filtered_week_four_and_five_results_include_all_twelve_teams():
    teams = [make_team(team_id) for team_id in range(1, 13)]
    waiver_player = make_player(100, "Waiver Starter", 17, "RB")
    boxes = [
        make_box(
            teams[index],
            teams[index + 1],
            100,
            90,
            home_lineup=[waiver_player] if index == 0 else [],
        )
        for index in range(0, 12, 2)
    ]
    transaction = SimpleNamespace(
        type="WAIVER",
        team=teams[0],
        items=[SimpleNamespace(type="ADD", playerId=100)],
    )
    challenges = make_challenges(FakeLeague(boxes, transactions={4: [transaction]}))

    waiver_results = challenges.waiver_wizard(4).placements
    blowout_results = challenges.largest_margin_winners(5).placements

    assert len(waiver_results) == 12
    assert waiver_results[0].team == "Team 1"
    assert waiver_results[0].players == ("Waiver Starter",)
    assert all(
        not placement.eligible
        and placement.value_1 is None
        and placement.value_2 is None
        and placement.difference is None
        and placement.place == 2
        and placement.players == ()
        for placement in waiver_results[1:]
    )

    assert len(blowout_results) == 12
    losing_teams = {f"Team {team_id}" for team_id in range(2, 13, 2)}
    assert {
        placement.team for placement in blowout_results if placement.difference == -10
    } == losing_teams
    assert all(
        placement.eligible
        and placement.place == 7
        and placement.value_1 is not None
        and placement.value_2 is not None
        and placement.difference == -10
        and placement.players == ()
        for placement in blowout_results
        if placement.team in losing_teams
    )
