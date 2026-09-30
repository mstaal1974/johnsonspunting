from datetime import date

from app.engine import LOST, PENDING, WON, BetIn, award_brownlow, compute_member, compute_season, current_month_index


def member(bets, current=11, base=50.0, max_bets=2):
    return compute_member(1, [BetIn(1, *b) for b in bets], base, max_bets, current)


def test_win_is_split_between_bank_and_next_month():
    s = member([(0, 50, WON, 200.0)])
    oct_, nov = s.months[0], s.months[1]
    assert oct_.banked == 100 and oct_.carry_out == 100
    assert nov.available == 150  # $50 + half the $200 collect


def test_carry_only_lasts_one_month():
    s = member([(0, 50, WON, 200.0), (1, 150, LOST)])
    assert s.months[2].available == 50


def test_losing_month_resets_to_base():
    s = member([(0, 50, LOST)])
    assert s.months[1].available == 50
    assert s.banked == 0


def test_overspend_is_deducted_next_month():
    # Greg in Oct 2025: three $30 bets on a $50 stake -> $10 to bet in November
    s = member([(0, 30, LOST), (0, 30, LOST), (0, 30, LOST)])
    assert s.months[0].overspend == 40
    assert s.months[1].available == 10
    assert any("3 bets" in f for f in s.months[0].flags)


def test_penalty_bigger_than_a_month_rolls_on():
    s = member([(0, 200, LOST)])
    assert s.months[1].available == 0
    assert s.months[2].available == 0  # 150 owed: 50 in Nov, 50 in Dec, 50 in Jan
    assert s.months[3].available == 0
    assert s.months[4].available == 50


def test_unused_stake_forfeited_only_once_month_closes():
    # Jimmy P: $25 + $20 of $50
    closed = member([(0, 25, LOST), (0, 20, LOST)], current=1)
    assert closed.months[0].unused == 5 and closed.forfeited == 5
    still_open = member([(0, 25, LOST), (0, 20, LOST)], current=0)
    assert still_open.months[0].unused == 0
    assert still_open.current_available == 5


def test_bonus_bets_use_no_stake_but_collect_counts():
    s = member([(0, 50, LOST), (0, 20, WON, 80.0, True)])
    oct_ = s.months[0]
    assert oct_.staked == 50 and oct_.bets == 1 and oct_.bonus_bets == 1
    assert oct_.overspend == 0 and not oct_.flags
    assert oct_.banked == 40 and s.months[1].available == 90


def test_pending_bets_count_nothing_yet():
    s = member([(0, 50, PENDING)], current=0)
    assert s.pending == 1 and s.collect == 0 and s.current_available == 0


def test_contributions_only_for_months_started():
    assert member([], current=2).contributed == 150
    assert member([], current=-1).contributed == 0
    assert member([], current=12).contributed == 600


def test_brownlow_top_three_with_ties():
    votes, mentions = award_brownlow({1: 452, 2: 333.38, 3: 232, 4: 180, 5: 174, 6: 0, 7: 20})
    assert votes == {1: 3, 2: 2, 3: 1}
    assert mentions == [4, 5]
    votes, _ = award_brownlow({1: 100, 2: 100, 3: 50, 4: 10})
    assert votes == {1: 3, 2: 3, 3: 1}


def test_season_totals_brownlow():
    summaries, _ = compute_season(
        [1, 2],
        [BetIn(1, 0, 50, WON, 300), BetIn(2, 0, 50, WON, 100), BetIn(2, 1, 50, WON, 90)],
        50, 2, 11,
    )
    assert summaries[1].brownlow == 3 and summaries[2].brownlow == 2 + 3


def test_current_month_index():
    start = date(2025, 10, 1)
    assert current_month_index(start, date(2025, 9, 30)) == -1
    assert current_month_index(start, date(2025, 10, 15)) == 0
    assert current_month_index(start, date(2026, 9, 28)) == 11
    assert current_month_index(start, date(2026, 11, 1)) == 12
