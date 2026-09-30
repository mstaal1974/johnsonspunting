"""Pages where punters log in with their PIN and enter their own bets.

Punters can only add bets to the current month, and only edit or delete their
own bets while they're still pending. Results are entered by the admin.
"""
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import MONTHS_PER_SEASON, PENDING
from app.models import Bet, Member
from app.services import slip_reader
from app.services.club import build_view
from app.services.pins import check_pin
from app.templating import flash, render

router = APIRouter(prefix="/me")


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def current_punter(request: Request, db: Session = Depends(get_db)) -> Member:
    member = db.get(Member, request.session.get("member_id") or 0)
    if member is None or not member.active or not member.pin_hash:
        request.session.pop("member_id", None)
        request.session.pop("member_name", None)
        raise HTTPException(303, headers={"Location": "/me/login"})
    return member


def _open_month(view) -> int:
    if not 0 <= view.current < MONTHS_PER_SEASON:
        raise ValueError("The season isn't running, so bets can't be entered right now.")
    return view.current


def _own_pending_bet(db: Session, bet_id: int, member: Member, view) -> Bet:
    bet = db.get(Bet, bet_id)
    if bet is None or bet.member_id != member.id or bet.season_id != view.season.id:
        raise HTTPException(404)
    if bet.result != PENDING or bet.month != view.current:
        raise HTTPException(403, "Only pending bets from this month can be changed. Ask the admin.")
    return bet


def _money(v: str) -> float:
    try:
        x = round(float((v or "").replace("$", "").replace(",", "").strip()), 2)
    except ValueError:
        raise ValueError("Stakes must be numbers, like 25 or 12.50")
    if x <= 0:
        raise ValueError("Each stake must be more than $0")
    return x


def _parse_rows(form) -> list[dict]:
    """Rows arrive as bets-<n>-stake / -description / -odds / -bonus / -keep."""
    idx = sorted({int(m.group(1)) for k in form.keys() if (m := re.fullmatch(r"bets-(\d+)-stake", k))})
    rows = []
    for i in idx:
        # The slip confirm page has a "keep" tick per row; skip rows the punter unticked
        if "has-keep" in form and f"bets-{i}-keep" not in form:
            continue
        description = (form.get(f"bets-{i}-description") or "").strip()
        if not description:
            raise ValueError("Say what each bet is on")
        rows.append({
            "stake": _money(form.get(f"bets-{i}-stake")),
            "description": description[:300],
            "odds": (form.get(f"bets-{i}-odds") or "").strip()[:30] or None,
            "bonus": f"bets-{i}-bonus" in form,
        })
    if not rows:
        raise ValueError("No bets to save")
    return rows


def _warnings(view, member_id: int, month: int) -> list[str]:
    line = view.summaries[member_id].months[month]
    return [f for f in line.flags if "forfeited" not in f]


# --- Login -------------------------------------------------------------------

@router.get("/login")
def login_get(request: Request, m: int | None = None, db: Session = Depends(get_db)):
    members = db.query(Member).filter(Member.active.is_(True), Member.pin_hash.isnot(None)).order_by(Member.name).all()
    return render(request, "me_login.html", members=members, selected=m, error=None)


@router.post("/login")
def login_post(request: Request, member_id: int = Form(...), pin: str = Form(...), db: Session = Depends(get_db)):
    member = db.get(Member, member_id)
    error = "Pick your name" if member is None or not member.active else check_pin(member, pin.strip())
    db.commit()  # records failed attempts / lockout
    if error:
        members = db.query(Member).filter(Member.active.is_(True), Member.pin_hash.isnot(None)).order_by(Member.name).all()
        return render(request, "me_login.html", members=members, selected=member_id, error=error)
    request.session["member_id"] = member.id
    request.session["member_name"] = member.name
    return back("/me")


@router.get("/logout")
def logout(request: Request):
    request.session.pop("member_id", None)
    request.session.pop("member_name", None)
    return back("/")


# --- My bets -----------------------------------------------------------------

@router.get("")
def my_bets(request: Request, member: Member = Depends(current_punter), db: Session = Depends(get_db)):
    view = build_view(db)
    month = view.current if 0 <= view.current < MONTHS_PER_SEASON else None
    bets = [b for b in view.bets if b.member_id == member.id and b.month == month]
    return render(request, "me.html", view=view, member=member, month=month, bets=bets,
                  line=view.summaries[member.id].months[month] if month is not None else None,
                  can_scan=slip_reader.available())


@router.post("/slip")
async def scan_slip(request: Request, photo: UploadFile = File(...), member: Member = Depends(current_punter),
                    db: Session = Depends(get_db)):
    view = build_view(db)
    try:
        month = _open_month(view)
        if not slip_reader.available():
            raise slip_reader.SlipReadError("Slip scanning isn't switched on - enter the bet by hand.")
        reading = slip_reader.read_slip(await photo.read(), photo.content_type or "")
    except (ValueError, slip_reader.SlipReadError) as e:
        flash(request, str(e), "error")
        return back("/me")
    line = view.summaries[member.id].months[month]
    return render(request, "me_confirm.html", view=view, member=member, month=month, line=line,
                  rows=reading.bets, note=reading.note)


@router.post("/bets")
async def save_bets(request: Request, member: Member = Depends(current_punter), db: Session = Depends(get_db)):
    form = await request.form()
    view = build_view(db)
    try:
        month = _open_month(view)
        rows = _parse_rows(form)
    except ValueError as e:
        flash(request, str(e), "error")
        return back("/me")
    source = "slip" if form.get("from_slip") else "punter"
    for r in rows:
        db.add(Bet(season_id=view.season.id, member_id=member.id, month=month, result=PENDING,
                   collect=0.0, source=source, **r))
    db.commit()
    total = sum(r["stake"] for r in rows if not r["bonus"])
    flash(request, f"Saved {len(rows)} bet{'s' if len(rows) != 1 else ''}"
                   + (f" (${total:,.2f} of your stake)." if total else "."))
    for w in _warnings(build_view(db), member.id, month):
        flash(request, w, "warn")
    return back("/me")


@router.get("/bets/{bet_id}")
def edit_get(request: Request, bet_id: int, member: Member = Depends(current_punter), db: Session = Depends(get_db)):
    view = build_view(db)
    bet = _own_pending_bet(db, bet_id, member, view)
    return render(request, "me_edit.html", view=view, member=member, bet=bet)


@router.post("/bets/{bet_id}")
def edit_post(request: Request, bet_id: int, stake: str = Form(...), description: str = Form(...),
              odds: str = Form(""), bonus: str = Form("off"),
              member: Member = Depends(current_punter), db: Session = Depends(get_db)):
    view = build_view(db)
    bet = _own_pending_bet(db, bet_id, member, view)
    try:
        bet.stake = _money(stake)
        if not description.strip():
            raise ValueError("Say what the bet is on")
    except ValueError as e:
        flash(request, str(e), "error")
        return back(f"/me/bets/{bet_id}")
    bet.description, bet.odds, bet.bonus = description.strip()[:300], odds.strip()[:30] or None, bonus == "on"
    db.commit()
    flash(request, "Bet updated.")
    for w in _warnings(build_view(db), member.id, bet.month):
        flash(request, w, "warn")
    return back("/me")


@router.post("/bets/{bet_id}/delete")
def delete(request: Request, bet_id: int, member: Member = Depends(current_punter), db: Session = Depends(get_db)):
    view = build_view(db)
    bet = _own_pending_bet(db, bet_id, member, view)
    db.delete(bet)
    db.commit()
    flash(request, "Bet deleted.")
    return back("/me")
