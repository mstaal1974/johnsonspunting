import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app import db as dbmod
from app.db import SessionLocal
from app.main import app
from app.models import Bet, Member
from app.services import club, pins, slip_reader
from app.services.slip_reader import SlipBet, SlipReading, SlipReadError


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2025, 11, 15)  # November, month 1 of the 2025-26 season


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(club, "date", FixedDate)
    with TestClient(app) as c:
        yield c


def member(name):
    with SessionLocal() as db:
        return db.query(Member).filter(Member.name == name).one()


def admin_set_pin(c, name, pin):
    c.post("/login", data={"password": "test-pw"})
    m = member(name)
    c.post(f"/admin/members/{m.id}", data={"name": m.name, "active": "on", "pin": pin})
    c.get("/logout")
    return m


def login(c, m, pin):
    return c.post("/me/login", data={"member_id": m.id, "pin": pin})


def test_pin_hashing_and_lockout():
    m = Member(name="x", pin_hash=pins.hash_pin("4321"), failed_logins=0)
    assert "4321" not in m.pin_hash
    assert pins.check_pin(m, "4321") is None
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for _ in range(4):
        assert pins.check_pin(m, "0000", now) == "Wrong PIN."
    assert "15 minutes" in pins.check_pin(m, "0000", now)
    assert "Try again" in pins.check_pin(m, "4321", now)  # locked even with the right PIN
    assert pins.check_pin(m, "4321", datetime(2026, 1, 1, 0, 20, tzinfo=timezone.utc)) is None
    assert pins.valid_pin("1234") and not pins.valid_pin("12") and not pins.valid_pin("12ab")


def test_punter_enters_edits_and_deletes_own_bet(client):
    c = client
    assert c.get("/me", follow_redirects=False).headers["location"] == "/me/login"
    m = admin_set_pin(c, "Matt", "2468")
    assert "Wrong PIN" in login(c, m, "1111").text
    r = login(c, m, "2468")
    assert "Hi Matt" in r.text and "Nov 2025" in r.text

    r = c.post("/me/bets", data={"bets-0-stake": "$30", "bets-0-description": "W Snitzel Dancer", "bets-0-odds": "$4.80"})
    assert "Saved 1 bet ($30.00 of your stake)" in r.text
    with SessionLocal() as db:
        bet = db.query(Bet).filter(Bet.member_id == m.id).one()
        assert (bet.month, bet.result, bet.source, bet.stake) == (1, "pending", "punter", 30)

    r = c.post(f"/me/bets/{bet.id}", data={"stake": "60", "description": "W Snitzel Dancer", "odds": "$4.80"})
    assert "Overspent $10.00" in r.text  # warned, but saved
    c.post(f"/me/bets/{bet.id}/delete")
    with SessionLocal() as db:
        assert db.get(Bet, bet.id) is None


def test_punter_cannot_touch_other_or_settled_bets(client):
    c = client
    tom, sean = admin_set_pin(c, "Tom", "1357"), admin_set_pin(c, "Sean", "9753")
    with SessionLocal() as db:
        season = club.active_season(db)
        other = Bet(season_id=season.id, member_id=sean.id, month=1, stake=10, description="x")
        settled = Bet(season_id=season.id, member_id=tom.id, month=1, stake=10, description="y", result="lost")
        old = Bet(season_id=season.id, member_id=tom.id, month=0, stake=10, description="z")
        db.add_all([other, settled, old])
        db.commit()
        ids = other.id, settled.id, old.id
    login(c, tom, "1357")
    assert c.post(f"/me/bets/{ids[0]}/delete").status_code == 404
    assert c.post(f"/me/bets/{ids[1]}/delete").status_code == 403
    assert c.post(f"/me/bets/{ids[2]}/delete").status_code == 403
    with SessionLocal() as db:
        assert all(db.get(Bet, i) for i in ids)


def test_scan_slip_then_confirm_with_edits(client, monkeypatch):
    c = client
    m = admin_set_pin(c, "Nigel", "8642")
    login(c, m, "8642")

    assert "Scan a bet slip" not in c.get("/me").text  # hidden without an API key
    monkeypatch.setattr(slip_reader, "available", lambda: True)
    seen = {}

    def fake_read(image, media_type):
        seen["args"] = (image, media_type)
        return SlipReading([SlipBet(20, "W Sam Hawkens", "$2.30", False),
                            SlipBet(20, "GGs SRM SR5", "$41.00", True)], note="Check the second stake")

    monkeypatch.setattr(slip_reader, "read_slip", fake_read)
    assert "Scan a bet slip" in c.get("/me").text
    r = c.post("/me/slip", files={"photo": ("slip.jpg", b"\xff\xd8fakejpeg", "image/jpeg")})
    assert seen["args"] == (b"\xff\xd8fakejpeg", "image/jpeg")
    assert 'value="W Sam Hawkens"' in r.text and "Check the second stake" in r.text
    with SessionLocal() as db:
        assert db.query(Bet).filter(Bet.member_id == m.id).count() == 0  # nothing saved yet

    # Punter corrects the first stake and unticks the second bet
    r = c.post("/me/bets", data={
        "has-keep": "1", "from_slip": "1",
        "bets-0-keep": "on", "bets-0-stake": "25", "bets-0-description": "W Sam Hawkens", "bets-0-odds": "$2.30",
        "bets-1-stake": "20", "bets-1-description": "GGs SRM SR5", "bets-1-odds": "$41.00", "bets-1-bonus": "on",
    })
    assert "Saved 1 bet" in r.text
    with SessionLocal() as db:
        (bet,) = db.query(Bet).filter(Bet.member_id == m.id).all()
        assert (bet.stake, bet.description, bet.source, bet.bonus) == (25, "W Sam Hawkens", "slip", False)


def test_scan_errors_are_shown(client, monkeypatch):
    c = client
    m = admin_set_pin(c, "Paul", "1122")
    login(c, m, "1122")
    monkeypatch.setattr(slip_reader, "available", lambda: True)

    def boom(image, media_type):
        raise SlipReadError("That doesn't look like a bet slip")

    monkeypatch.setattr(slip_reader, "read_slip", boom)
    r = c.post("/me/slip", files={"photo": ("cat.jpg", b"x", "image/jpeg")})
    assert "look like a bet slip" in r.text


class FakeMessages:
    def __init__(self, payload, stop_reason="end_turn"):
        self.payload, self.stop_reason, self.kwargs = payload, stop_reason, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def fake_client(payload, stop_reason="end_turn"):
    msgs = FakeMessages(payload, stop_reason)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def test_read_slip_request_and_parsing():
    client, msgs = fake_client({"is_bet_slip": True, "note": "",
                                "bets": [{"stake": 15, "description": "EW Apophis", "odds": "$5.50", "bonus": False}]})
    reading = slip_reader.read_slip(b"img", "image/png", client=client)
    assert reading.bets == [SlipBet(15, "EW Apophis", "$5.50", False)]
    k = msgs.kwargs
    assert k["model"] == slip_reader.MODEL
    assert k["output_config"]["format"]["schema"] == slip_reader.SCHEMA
    image = k["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/png" and image["source"]["data"] == "aW1n"


@pytest.mark.parametrize("payload,stop,msg", [
    ({"is_bet_slip": False, "bets": [], "note": ""}, "end_turn", "look like a bet slip"),
    ({}, "refusal", "couldn't process"),
])
def test_read_slip_failures(payload, stop, msg):
    client, _ = fake_client(payload, stop)
    with pytest.raises(SlipReadError, match=msg):
        slip_reader.read_slip(b"img", "image/jpeg", client=client)
    with pytest.raises(SlipReadError, match="isn't a photo"):
        slip_reader.read_slip(b"img", "application/pdf", client=client)


def test_old_database_gets_new_columns(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE members (id INTEGER PRIMARY KEY, name VARCHAR(100), active BOOLEAN)"))
        conn.execute(text("INSERT INTO members (name, active) VALUES ('Andrew', 1)"))
    monkeypatch.setattr(dbmod, "engine", eng)
    dbmod.add_missing_columns()
    cols = {c["name"] for c in inspect(eng).get_columns("members")}
    assert {"pin_hash", "failed_logins", "locked_until"} <= cols
    with eng.connect() as conn:
        assert conn.execute(text("SELECT failed_logins, pin_hash FROM members")).one() == (0, None)
