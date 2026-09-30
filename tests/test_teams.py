import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.db import SessionLocal
from app.engine import WON, BetIn, compute_season, compute_teams
from app.main import app
from app.models import Bet, Member, Season, Team
from app.services import club


def test_team_points_follow_members_votes():
    # Oct: 1 collects most (3 votes), 3 next (2), 5 next (1)
    # Nov: 4 (3 votes) and 3 (2) are both team B -> B has 5; 5 gets 1 -> C
    bets = [BetIn(1, 0, 50, WON, 300), BetIn(3, 0, 50, WON, 200), BetIn(5, 0, 50, WON, 150),
            BetIn(4, 1, 50, WON, 300), BetIn(3, 1, 50, WON, 200), BetIn(5, 1, 50, WON, 100)]
    summaries, _ = compute_season(range(1, 7), bets, 50, 2, current=1)
    teams = compute_teams({10: [1, 2], 20: [3, 4], 30: [5, 6]}, summaries, current=1)
    assert [teams[t].month_votes[:2] for t in (10, 20, 30)] == [[3, 0], [2, 5], [1, 1]]
    assert [teams[t].month_points[:2] for t in (10, 20, 30)] == [[3, 0], [2, 3], [1, 2]]
    assert [teams[t].points for t in (10, 20, 30)] == [3, 5, 3]
    assert teams[20].banked == (200 + 300 + 200) / 2


def test_tied_teams_share_points_and_zero_votes_score_nothing():
    summaries, _ = compute_season([1, 2, 3], [BetIn(1, 0, 50, WON, 100), BetIn(2, 0, 50, WON, 100)], 50, 2, 0)
    teams = compute_teams({10: [1], 20: [2], 30: [3]}, summaries, current=0)
    assert [teams[t].month_points[0] for t in (10, 20, 30)] == [3, 3, 0]


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2025, 11, 15)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(club, "date", FixedDate)
    with TestClient(app) as c:
        c.post("/login", data={"password": "test-pw"})
        yield c


def ids(*names):
    with SessionLocal() as db:
        return [db.query(Member).filter(Member.name == n).one().id for n in names]


def test_admin_sets_up_teams_and_dashboard_ranks_them(client):
    c = client
    for name in ("Kings", "Roosters"):
        c.post("/admin/teams", data={"name": name})
    assert "already a team" in c.post("/admin/teams", data={"name": "kings"}).text
    with SessionLocal() as db:
        season = club.active_season(db)
        kings, roosters = (db.query(Team).filter(Team.season_id == season.id, Team.name == n).one().id
                           for n in ("Kings", "Roosters"))
    josh, michael, paul, peter, robbie = ids("Josh", "Michael", "Paul", "Peter", "Robbie")
    r = c.post("/admin/teams/assign", data={f"team-{josh}": kings, f"team-{michael}": kings,
                                            f"team-{paul}": roosters, f"team-{peter}": roosters,
                                            f"team-{robbie}": ""})
    assert "Teams saved" in r.text and "Kings has 2 punters" in r.text

    # A big November collect for a Rooster puts them on top
    with SessionLocal() as db:
        db.add(Bet(season_id=season.id, member_id=peter, month=1, stake=50, description="W Big Win",
                   result="won", collect=5000))
        db.commit()

    board = c.get("/api/leaderboard").json()
    assert board["teams"][0]["team"] == "Roosters" and board["teams"][0]["points"] >= 3
    assert sorted(board["teams"][0]["members"]) == ["Paul", "Peter"]
    assert next(p for p in board["leaderboard"] if p["punter"] == "Josh")["team"] == "Kings"

    page = c.get("/").text
    assert "Team leaderboard" in page and "Individual leaderboard" in page
    assert "What everyone has to bet in Nov 2025" in page
    assert c.get("/teams").status_code == 200
    assert "Team points" in c.get("/month/1").text

    wb = load_workbook(io.BytesIO(c.get("/export.xlsx").content))
    assert wb["Teams"]["B3"].value == "Roosters"

    # A punter logged in with a PIN sees their own stake up top
    c.post(f"/admin/members/{josh}", data={"name": "Josh", "active": "on", "pin": "5555"})
    c.post("/me/login", data={"member_id": josh, "pin": "5555"})
    page = c.get("/").text
    assert 'class="hero"' in page and "left to bet in Nov 2025" in page and "Kings" in page


def test_new_season_carries_teams_over(client):
    c = client
    with SessionLocal() as db:
        old = club.active_season(db)
        old_id = old.id
        team_count = db.query(Team).filter(Team.season_id == old_id).count()
    assert team_count > 0
    c.post("/admin/new-season")
    with SessionLocal() as db:
        new = db.query(Season).filter(Season.active.is_(True)).one()
        assert new.id != old_id
        copied = db.query(Team).filter(Team.season_id == new.id).all()
        assert len(copied) == team_count and sum(len(t.memberships) for t in copied) > 0
        # put the original season back for any later tests
        new.active, db.get(Season, old_id).active = False, True
        db.commit()
