# Johnsons Punt Club

A small web app that runs the punt club spreadsheet for you. You enter each bet and its result, and the app works out stakes, carry-overs, banking, penalties, Brownlow votes and the leaderboard.

- **Leaderboard** (public, no login): ranked by total banked, Brownlow votes, ROI or total collected. It also shows what each punter has left to bet this month.
- **Month sheets** (public): each punter's stake, bets, results, collect, banked amount and carry-over, with rule warnings.
- **Punter pages** (public): a punter's month-by-month history and every bet.
- **Enter bets** (admin): add a bet, settle pending bets with one click (Won + collect amount, or Lost), and edit or delete bets.
- **Members** (admin): add, rename or deactivate punters.
- **Season & data** (admin): monthly stake, max bets and start month; start next season; import the existing Excel workbook; export to Excel.

## The rules it applies

Seasons run October to September. Each month, for each punter:

| | |
|---|---|
| Stake to bet | $50 + half of last month's collect − last month's overspend |
| Banked | half of this month's collect |
| Carried to next month | the other half of this month's collect |
| Overspend | anything staked above the stake to bet. It's deducted from next month (Greg bet $90 of $50 in Oct 2025, so he had $10 in Nov). |
| Unused stake | forfeited once the month is over (Jimmy P, Oct 2025: $5) |
| Bet limit | 2 bets a month. Going over is flagged. |
| Bonus bets | bookmaker bonus bets ("BONER") don't use stake or count towards the limit. Their collect counts as normal. |
| Brownlow | 3-2-1 votes each month to the three biggest collects (ties share the higher score). The next two get special mentions. |

"Collect" is the total the bookmaker paid out, stake included. A $10 win at $3.00 is a $30 collect, so $15 is banked and $15 goes on top of next month's $50.

**Net** is banked minus what the punter has paid in so far ($50 × months started). **ROI** is net ÷ paid in.

The monthly stake, bet limit and season start can be changed under *Season & data*.

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set ADMIN_PASSWORD and SECRET_KEY
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. The first start creates the 2025-2026 season and the 20 current members. To load this season's bets, log in (Admin), go to **Season & data** and upload `Johnsons_Punt_Club_2025-2026.xlsx`.

Data is stored in SQLite at `data/club.db`, or in the database named by `DATABASE_URL`.

## Deploy (Render, Railway, or any host that runs Python)

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment: `ADMIN_PASSWORD`, `SECRET_KEY` (any long random string) and `DATABASE_URL`

Use a Postgres database for `DATABASE_URL` on hosted platforms. Their free-tier disks are wiped on redeploy, so a SQLite file would lose the club's data.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Layout

```
app/engine.py            the club rules (pure functions, unit tested)
app/services/club.py     loads a season from the database and runs the rules
app/services/excel_io.py import/export in the club spreadsheet's layout
app/routes/public.py     leaderboard, month and punter pages, /api/leaderboard
app/routes/admin.py      login, bet entry, members, settings, import
app/templates/           pages
```

`johnsonspun.zip` holds the earlier prototype, which sent bet receipts to members over WhatsApp via Twilio. This app doesn't use it.
