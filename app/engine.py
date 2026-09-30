"""Club ledger rules.

Pure functions only: everything here takes plain values and returns plain
values, so the rules can be tested without a database.

Monthly cycle for each punter:
  available = base stake + carry-in - penalty-in
  collect   = total returned by winning bets this month
  banked    = collect / 2           (kept for the punter)
  carry-out = collect / 2           (added to next month's stake)
  overspend = staked - available    (deducted from next month's stake)
  unused    = available - staked    (forfeited once the month is over)

Bonus bets (bookmaker bonus credit, marked "BONER" in the old spreadsheet)
don't use the punter's stake or count towards the bet limit, but anything
they collect is treated like any other collect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

MONTHS_PER_SEASON = 12
BROWNLOW_POINTS = (3, 2, 1)
SPECIAL_MENTIONS = 2

PENDING, WON, LOST = "pending", "won", "lost"


@dataclass(frozen=True)
class BetIn:
    member_id: int
    month: int  # 0 = first month of the season
    stake: float
    result: str = PENDING
    collect: float = 0.0
    bonus: bool = False


@dataclass
class MonthLine:
    month: int
    base: float
    carry_in: float = 0.0
    penalty_in: float = 0.0
    available: float = 0.0
    staked: float = 0.0
    collect: float = 0.0
    banked: float = 0.0
    carry_out: float = 0.0
    overspend: float = 0.0
    unused: float = 0.0
    bets: int = 0
    bonus_bets: int = 0
    winners: int = 0
    pending: int = 0
    brownlow: int = 0
    flags: list[str] = field(default_factory=list)


@dataclass
class MemberSummary:
    member_id: int
    months: list[MonthLine]
    contributed: float = 0.0
    staked: float = 0.0
    collect: float = 0.0
    banked: float = 0.0
    forfeited: float = 0.0
    bets: int = 0
    winners: int = 0
    pending: int = 0
    brownlow: int = 0
    current_available: float = 0.0

    @property
    def net(self) -> float:
        return self.banked - self.contributed

    @property
    def roi(self) -> float | None:
        return self.net / self.contributed if self.contributed else None

    @property
    def strike_rate(self) -> float | None:
        settled = self.bets - self.pending
        return self.winners / settled if settled else None


def month_start(season_start: date, month: int) -> date:
    y, m = divmod(season_start.month - 1 + month, 12)
    return date(season_start.year + y, m + 1, 1)


def current_month_index(season_start: date, today: date) -> int:
    """Index of the month containing `today`; -1 before the season, 12 after."""
    diff = (today.year - season_start.year) * 12 + today.month - season_start.month
    return max(-1, min(diff, MONTHS_PER_SEASON))


def compute_member(
    member_id: int,
    bets: Iterable[BetIn],
    base_stake: float,
    max_bets: int,
    current: int,
) -> MemberSummary:
    """Roll one punter's season forward month by month.

    `current` is the index of the month in progress (see
    current_month_index). Months before it are closed: they count towards
    contributions and their unused stake is forfeited. The current month
    counts towards contributions but is still open for bets.
    """
    months_open = max(0, min(current + 1, MONTHS_PER_SEASON))
    by_month: dict[int, list[BetIn]] = {}
    for b in bets:
        by_month.setdefault(b.month, []).append(b)

    lines: list[MonthLine] = []
    carry = penalty = 0.0
    for m in range(MONTHS_PER_SEASON):
        line = MonthLine(month=m, base=base_stake, carry_in=carry, penalty_in=penalty)
        available = base_stake + carry - penalty
        # A penalty bigger than a whole month's stake rolls on to the next month.
        debt_left = max(0.0, -available)
        line.available = max(0.0, available)

        month_bets = by_month.get(m, [])
        paid = [b for b in month_bets if not b.bonus]
        line.bets = len(paid)
        line.bonus_bets = len(month_bets) - len(paid)
        line.staked = sum(b.stake for b in paid)
        line.winners = sum(1 for b in month_bets if b.result == WON)
        line.pending = sum(1 for b in month_bets if b.result == PENDING)
        line.collect = sum(b.collect for b in month_bets if b.result == WON)
        line.banked = line.collect / 2
        line.carry_out = line.collect / 2
        line.overspend = max(0.0, line.staked - line.available)
        closed = m < current
        if closed:
            line.unused = max(0.0, line.available - line.staked)

        if line.bets > max_bets:
            line.flags.append(f"{line.bets} bets placed (max {max_bets})")
        if line.overspend > 0:
            line.flags.append(f"Overspent ${line.overspend:,.2f} - deducted next month")
        if closed and line.unused > 0:
            line.flags.append(f"${line.unused:,.2f} unused - forfeited")

        lines.append(line)
        carry = line.carry_out
        penalty = line.overspend + debt_left

    open_lines = lines[:months_open]
    s = MemberSummary(member_id=member_id, months=lines)
    s.contributed = base_stake * len(open_lines)
    s.staked = sum(l.staked for l in open_lines)
    s.collect = sum(l.collect for l in open_lines)
    s.banked = sum(l.banked for l in open_lines)
    s.forfeited = sum(l.unused for l in open_lines)
    s.bets = sum(l.bets + l.bonus_bets for l in open_lines)
    s.winners = sum(l.winners for l in open_lines)
    s.pending = sum(l.pending for l in open_lines)
    if 0 <= current < MONTHS_PER_SEASON:
        cur = lines[current]
        s.current_available = max(0.0, cur.available - cur.staked)
    return s


def award_brownlow(collects: dict[int, float]) -> tuple[dict[int, int], list[int]]:
    """3-2-1 votes for the month's three biggest collects.

    Ties share the higher score (standard competition ranking), so two punters
    tied on top both get 3 and the next gets 1. Returns (votes, special
    mentions) where mentions are the next best collects after the vote-getters.
    """
    ranked = sorted(((c, mid) for mid, c in collects.items() if c > 0), reverse=True)
    votes: dict[int, int] = {}
    mentions: list[int] = []
    rank = 0
    prev = None
    for i, (c, mid) in enumerate(ranked):
        if c != prev:
            rank = i
            prev = c
        if rank < len(BROWNLOW_POINTS):
            votes[mid] = BROWNLOW_POINTS[rank]
        elif len(mentions) < SPECIAL_MENTIONS:
            mentions.append(mid)
    return votes, mentions


def compute_season(
    member_ids: Iterable[int],
    bets: Iterable[BetIn],
    base_stake: float,
    max_bets: int,
    current: int,
) -> tuple[dict[int, MemberSummary], list[list[int]]]:
    """Summaries for every member plus the special mentions for each month."""
    bets = list(bets)
    by_member: dict[int, list[BetIn]] = {mid: [] for mid in member_ids}
    for b in bets:
        by_member.setdefault(b.member_id, []).append(b)

    summaries = {
        mid: compute_member(mid, mb, base_stake, max_bets, current)
        for mid, mb in by_member.items()
    }

    mentions_by_month: list[list[int]] = []
    for m in range(MONTHS_PER_SEASON):
        collects = {mid: s.months[m].collect for mid, s in summaries.items()}
        votes, mentions = award_brownlow(collects)
        for mid, pts in votes.items():
            summaries[mid].months[m].brownlow = pts
        mentions_by_month.append(mentions)
    for s in summaries.values():
        s.brownlow = sum(l.brownlow for l in s.months[: max(0, min(current + 1, MONTHS_PER_SEASON))])
    return summaries, mentions_by_month
