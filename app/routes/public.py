from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import MONTHS_PER_SEASON
from app.services.club import build_view
from app.templating import render

router = APIRouter()

SORTS = {"banked": "Total banked", "brownlow": "Brownlow", "roi": "ROI", "collect": "Collected"}


@router.get("/")
def leaderboard(request: Request, sort: str = "banked", db: Session = Depends(get_db)):
    view = build_view(db)
    sort = sort if sort in SORTS else "banked"
    return render(request, "leaderboard.html", view=view, rows=view.ranked(sort), sort=sort,
                  sorts=SORTS, totals=view.totals())


@router.get("/month/{month}")
def month_sheet(request: Request, month: int, db: Session = Depends(get_db)):
    if not 0 <= month < MONTHS_PER_SEASON:
        raise HTTPException(404)
    view = build_view(db)
    bets_by_member = {}
    for b in view.bets:
        if b.month == month:
            bets_by_member.setdefault(b.member_id, []).append(b)
    votes = sorted(
        ((view.summaries[m.id].months[month].brownlow, m) for m in view.members
         if view.summaries[m.id].months[month].brownlow),
        key=lambda x: (-x[0], -view.summaries[x[1].id].months[month].collect),
    )
    return render(request, "month.html", view=view, month=month, bets_by_member=bets_by_member,
                  votes=votes, mentions=[view.member(i) for i in view.mentions[month]])


@router.get("/punter/{member_id}")
def punter(request: Request, member_id: int, db: Session = Depends(get_db)):
    view = build_view(db)
    member = view.member(member_id)
    if member is None:
        raise HTTPException(404)
    rank = next(r for r, m, _ in view.ranked() if m.id == member_id)
    bets = [b for b in view.bets if b.member_id == member_id]
    return render(request, "punter.html", view=view, member=member, s=view.summaries[member_id],
                  rank=rank, bets=bets)


@router.get("/api/leaderboard")
def api_leaderboard(sort: str = "banked", db: Session = Depends(get_db)):
    view = build_view(db)
    return {
        "season": view.season.name,
        "current_month": view.current_label,
        "leaderboard": [
            {"rank": r, "punter": m.name, "banked": s.banked, "contributed": s.contributed, "net": s.net,
             "roi": s.roi, "collected": s.collect, "staked": s.staked, "bets": s.bets, "winners": s.winners,
             "brownlow": s.brownlow, "available_this_month": s.current_available}
            for r, m, s in view.ranked(sort)
        ],
    }
