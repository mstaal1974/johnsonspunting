import hmac
import os
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.engine import LOST, MONTHS_PER_SEASON, PENDING, WON
from app.models import Bet, Member, Season
from app.services.club import build_view, season_name
from app.services.excel_io import export_workbook, import_workbook
from app.services.pins import hash_pin, valid_pin
from app.templating import flash, is_admin, render

router = APIRouter()


def require_admin(request: Request):
    if not is_admin(request):
        raise HTTPException(303, headers={"Location": "/login"})


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def parse_money(v: str, field: str) -> float:
    try:
        x = float((v or "0").replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        raise ValueError(f"{field} must be a number")
    if x < 0:
        raise ValueError(f"{field} can't be negative")
    return round(x, 2)


@router.get("/login")
def login_get(request: Request):
    return render(request, "login.html", error=None)


@router.post("/login")
def login_post(request: Request, password: str = Form(...)):
    expected = os.getenv("ADMIN_PASSWORD", "change_me")
    if hmac.compare_digest(password.encode(), expected.encode()):
        request.session["is_admin"] = True
        return back("/admin")
    return render(request, "login.html", error="Wrong password")


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return back("/")


# --- Bets -------------------------------------------------------------------

@router.get("/admin", dependencies=[Depends(require_admin)])
def admin_home(request: Request, month: int | None = None, db: Session = Depends(get_db)):
    view = build_view(db)
    month = view.default_month if month is None else max(0, min(month, MONTHS_PER_SEASON - 1))
    month_bets = [b for b in view.bets if b.month == month]
    pending = [b for b in view.bets if b.result == PENDING]
    return render(request, "admin.html", view=view, month=month, month_bets=month_bets, pending=pending,
                  active_members=[m for m in view.members if m.active])


def _bet_fields(month, member_id, stake, description, odds, bonus, result, collect, db):
    if not 0 <= month < MONTHS_PER_SEASON:
        raise ValueError("Pick a month in the season")
    if db.get(Member, member_id) is None:
        raise ValueError("Pick a punter")
    if result not in (PENDING, WON, LOST):
        raise ValueError("Unknown result")
    stake_v = parse_money(stake, "Stake")
    if stake_v == 0:
        raise ValueError("Stake must be more than $0")
    collect_v = parse_money(collect, "Collect") if result == WON else 0.0
    if result == WON and collect_v == 0:
        raise ValueError("Enter the amount collected for a winning bet")
    return dict(month=month, member_id=member_id, stake=stake_v, description=description.strip(),
                odds=odds.strip() or None, bonus=bonus == "on", result=result, collect=collect_v)


@router.post("/admin/bets", dependencies=[Depends(require_admin)])
def add_bet(
    request: Request,
    month: int = Form(...), member_id: int = Form(...), stake: str = Form(...),
    description: str = Form(""), odds: str = Form(""), bonus: str = Form("off"),
    result: str = Form(PENDING), collect: str = Form(""),
    db: Session = Depends(get_db),
):
    season = build_view(db).season
    try:
        fields = _bet_fields(month, member_id, stake, description, odds, bonus, result, collect, db)
    except ValueError as e:
        flash(request, str(e), "error")
        return back(f"/admin?month={month}")
    bet = Bet(season_id=season.id, **fields)
    db.add(bet)
    db.commit()

    line = build_view(db).summaries[member_id].months[month]
    name = db.get(Member, member_id).name
    flash(request, f"Saved {name}'s ${bet.stake:,.2f} bet.")
    for f in line.flags:
        if "forfeited" not in f:
            flash(request, f"{name}: {f}", "warn")
    return back(f"/admin?month={month}")


@router.post("/admin/bets/{bet_id}/settle", dependencies=[Depends(require_admin)])
def settle_bet(request: Request, bet_id: int, result: str = Form(...), collect: str = Form(""),
               db: Session = Depends(get_db)):
    bet = db.get(Bet, bet_id) or _404()
    try:
        if result == WON:
            c = parse_money(collect, "Collect")
            if c == 0:
                raise ValueError("Enter the amount collected")
            bet.result, bet.collect = WON, c
        elif result in (LOST, PENDING):
            bet.result, bet.collect = result, 0.0
        else:
            raise ValueError("Unknown result")
    except ValueError as e:
        flash(request, str(e), "error")
        return back(request.headers.get("referer") or "/admin")
    db.commit()
    msg = f"{bet.member.name}: marked {bet.result}"
    if bet.result == WON:
        msg += f" - ${bet.collect / 2:,.2f} banked, ${bet.collect / 2:,.2f} added to next month"
    flash(request, msg)
    return back(request.headers.get("referer") or f"/admin?month={bet.month}")


@router.get("/admin/bets/{bet_id}", dependencies=[Depends(require_admin)])
def edit_bet_get(request: Request, bet_id: int, db: Session = Depends(get_db)):
    bet = db.get(Bet, bet_id) or _404()
    view = build_view(db)
    return render(request, "bet_edit.html", view=view, bet=bet)


@router.post("/admin/bets/{bet_id}", dependencies=[Depends(require_admin)])
def edit_bet_post(
    request: Request, bet_id: int,
    month: int = Form(...), member_id: int = Form(...), stake: str = Form(...),
    description: str = Form(""), odds: str = Form(""), bonus: str = Form("off"),
    result: str = Form(PENDING), collect: str = Form(""),
    db: Session = Depends(get_db),
):
    bet = db.get(Bet, bet_id) or _404()
    try:
        fields = _bet_fields(month, member_id, stake, description, odds, bonus, result, collect, db)
    except ValueError as e:
        flash(request, str(e), "error")
        return back(f"/admin/bets/{bet_id}")
    for k, v in fields.items():
        setattr(bet, k, v)
    db.commit()
    flash(request, "Bet updated.")
    return back(f"/admin?month={bet.month}")


@router.post("/admin/bets/{bet_id}/delete", dependencies=[Depends(require_admin)])
def delete_bet(request: Request, bet_id: int, db: Session = Depends(get_db)):
    bet = db.get(Bet, bet_id) or _404()
    month = bet.month
    db.delete(bet)
    db.commit()
    flash(request, "Bet deleted.")
    return back(f"/admin?month={month}")


def _404():
    raise HTTPException(404)


# --- Members ----------------------------------------------------------------

@router.get("/admin/members", dependencies=[Depends(require_admin)])
def members(request: Request, db: Session = Depends(get_db)):
    return render(request, "members.html", members=db.query(Member).order_by(Member.name).all())


@router.post("/admin/members", dependencies=[Depends(require_admin)])
def add_member(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    name = name.strip()
    if not name:
        flash(request, "Enter a name", "error")
    elif db.query(Member).filter(Member.name.ilike(name)).first():
        flash(request, f"{name} is already a member", "error")
    else:
        db.add(Member(name=name))
        db.commit()
        flash(request, f"Added {name}.")
    return back("/admin/members")


@router.post("/admin/members/{member_id}", dependencies=[Depends(require_admin)])
def update_member(request: Request, member_id: int, name: str = Form(...), active: str = Form("off"),
                  pin: str = Form(""), clear_pin: str = Form("off"), db: Session = Depends(get_db)):
    m = db.get(Member, member_id) or _404()
    name = name.strip()
    clash = db.query(Member).filter(Member.name.ilike(name), Member.id != member_id).first()
    if not name or clash:
        flash(request, "Name is empty or already taken", "error")
        return back("/admin/members")
    pin = pin.strip()
    if pin and not valid_pin(pin):
        flash(request, "A PIN must be 4 to 8 digits", "error")
        return back("/admin/members")
    m.name, m.active = name, active == "on"
    if pin:
        m.pin_hash, m.failed_logins, m.locked_until = hash_pin(pin), 0, None
    elif clear_pin == "on":
        m.pin_hash = None
    db.commit()
    flash(request, f"Updated {m.name}." + (" New PIN saved - give them the PIN and their login link." if pin else ""))
    return back("/admin/members")


# --- Season settings, import & export ----------------------------------------

@router.get("/admin/data", dependencies=[Depends(require_admin)])
def data_page(request: Request, db: Session = Depends(get_db)):
    view = build_view(db)
    return render(request, "data.html", view=view)


@router.post("/admin/settings", dependencies=[Depends(require_admin)])
def save_settings(request: Request, start: str = Form(...), base_stake: str = Form(...),
                  max_bets: int = Form(...), db: Session = Depends(get_db)):
    season: Season = build_view(db).season
    try:
        y, m = (int(x) for x in start.split("-")[:2])
        season.start = date(y, m, 1)
        season.base_stake = parse_money(base_stake, "Base stake")
        if max_bets < 1:
            raise ValueError("Max bets must be at least 1")
        season.max_bets = max_bets
        season.name = season_name(season.start)
    except ValueError as e:
        flash(request, str(e), "error")
        return back("/admin/data")
    db.commit()
    flash(request, "Season settings saved.")
    return back("/admin/data")


@router.post("/admin/new-season", dependencies=[Depends(require_admin)])
def new_season(request: Request, db: Session = Depends(get_db)):
    old: Season = build_view(db).season
    start = date(old.start.year + 1, old.start.month, 1)
    if db.query(Season).filter(Season.start == start).first():
        flash(request, f"Season starting {start:%b %Y} already exists", "error")
        return back("/admin/data")
    old.active = False
    db.add(Season(name=season_name(start), start=start, base_stake=old.base_stake,
                  max_bets=old.max_bets, active=True))
    db.commit()
    flash(request, f"Started season {season_name(start)}. Everyone is back to ${old.base_stake:,.0f}.")
    return back("/admin/data")


@router.post("/admin/import", dependencies=[Depends(require_admin)])
async def import_xlsx(request: Request, file: UploadFile = File(...), zero_is_lost: str = Form("off"),
                      db: Session = Depends(get_db)):
    try:
        result = import_workbook(db, await file.read(), zero_collect_is_lost=zero_is_lost == "on")
    except Exception as e:  # bad/unsupported workbook
        db.rollback()
        flash(request, f"Import failed: {e}", "error")
        return back("/admin/data")
    flash(request, f"Imported season {result['season']}: {result['members']} punters, {result['bets']} bets.")
    for w in result["warnings"]:
        flash(request, w, "warn")
    return back("/admin/data")


@router.get("/export.xlsx")
def export_xlsx(db: Session = Depends(get_db)):
    view = build_view(db)
    return Response(
        export_workbook(view),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Johnsons_Punt_Club_{view.season.name}.xlsx"'},
    )
