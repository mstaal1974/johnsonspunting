from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app import engine
from app.models import Bet, Member, Season

DEFAULT_PUNTERS = [
    "Andrew", "Ben", "Brad", "Col", "Darren", "Glenn", "Greg", "Jimmy E", "Jimmy P",
    "Johnny W", "Josh", "Matt", "Michael", "Nathan", "Nigel", "Paul", "Peter", "Robbie",
    "Sean", "Tom",
]


def season_start_for(today: date) -> date:
    """Seasons run October to September."""
    return date(today.year if today.month >= 10 else today.year - 1, 10, 1)


def season_name(start: date) -> str:
    end = engine.month_start(start, engine.MONTHS_PER_SEASON - 1)
    return f"{start.year}-{end.year}" if end.year != start.year else str(start.year)


def ensure_seed(db: Session, today: date | None = None) -> None:
    if db.query(Season).count() == 0:
        start = date(2025, 10, 1)
        db.add(Season(name=season_name(start), start=start, base_stake=50.0, max_bets=2, active=True))
    if db.query(Member).count() == 0:
        db.add_all(Member(name=n) for n in DEFAULT_PUNTERS)
    db.commit()


def active_season(db: Session) -> Season:
    season = db.query(Season).filter(Season.active.is_(True)).order_by(Season.start.desc()).first()
    if season is None:
        ensure_seed(db)
        season = db.query(Season).order_by(Season.start.desc()).first()
    return season


def month_labels(season: Season) -> list[str]:
    return [engine.month_start(season.start, m).strftime("%b %Y") for m in range(engine.MONTHS_PER_SEASON)]


@dataclass
class SeasonView:
    season: Season
    members: list[Member]
    summaries: dict[int, engine.MemberSummary]
    mentions: list[list[int]]
    current: int  # index of month in progress (-1 before season, 12 after)
    labels: list[str]
    bets: list[Bet]

    @property
    def current_label(self) -> str:
        if self.current < 0:
            return "Season not started"
        if self.current >= engine.MONTHS_PER_SEASON:
            return "Season finished"
        return self.labels[self.current]

    @property
    def default_month(self) -> int:
        return max(0, min(self.current, engine.MONTHS_PER_SEASON - 1))

    def member(self, member_id: int) -> Member | None:
        return next((m for m in self.members if m.id == member_id), None)

    def ranked(self, sort: str = "banked") -> list[tuple[int, Member, engine.MemberSummary]]:
        keys = {
            "banked": lambda s: (s.banked, s.brownlow),
            "brownlow": lambda s: (s.brownlow, s.banked),
            "roi": lambda s: (s.roi if s.roi is not None else float("-inf"), s.banked),
            "collect": lambda s: (s.collect, s.banked),
        }
        key = keys.get(sort, keys["banked"])
        rows = sorted(
            ((m, self.summaries[m.id]) for m in self.members),
            key=lambda ms: (key(ms[1]), -ms[0].id), reverse=True,
        )
        out, prev, rank = [], None, 0
        for i, (m, s) in enumerate(rows, start=1):
            if key(s) != prev:
                rank, prev = i, key(s)
            out.append((rank, m, s))
        return out

    def totals(self) -> dict[str, float]:
        ss = self.summaries.values()
        return {
            "contributed": sum(s.contributed for s in ss),
            "staked": sum(s.staked for s in ss),
            "collect": sum(s.collect for s in ss),
            "banked": sum(s.banked for s in ss),
            "forfeited": sum(s.forfeited for s in ss),
            "pending": sum(s.pending for s in ss),
        }


def build_view(db: Session, season: Season | None = None, today: date | None = None) -> SeasonView:
    season = season or active_season(db)
    today = today or date.today()
    bets = db.query(Bet).filter(Bet.season_id == season.id).order_by(Bet.month, Bet.id).all()
    member_ids_with_bets = {b.member_id for b in bets}
    members = (
        db.query(Member)
        .filter((Member.active.is_(True)) | (Member.id.in_(member_ids_with_bets)))
        .order_by(Member.name)
        .all()
    )
    current = engine.current_month_index(season.start, today)
    summaries, mentions = engine.compute_season(
        [m.id for m in members],
        [engine.BetIn(b.member_id, b.month, b.stake, b.result, b.collect, b.bonus) for b in bets],
        season.base_stake,
        season.max_bets,
        current,
    )
    return SeasonView(season, members, summaries, mentions, current, month_labels(season), bets)
