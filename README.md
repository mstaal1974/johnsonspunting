# Johnsons Punt Club

A small web app that runs the punt club spreadsheet for you. You enter each bet and its result, and the app works out stakes, carry-overs, banking, penalties, Brownlow votes and the leaderboard.

- **Leaderboard** (public, no login): ranked by total banked, Brownlow votes, ROI or total collected. It also shows what each punter has left to bet this month.
- **Month sheets** (public): each punter's stake, bets, results, collect, banked amount and carry-over, with rule warnings.
- **Punter pages** (public): a punter's month-by-month history and every bet.
- **My bets** (punters, with a PIN): see what's left to bet this month and enter bets. They can scan a photo or screenshot of a bet slip (Claude reads it and fills in the form for them to check and correct) or type them in. They can edit or delete their own bets while they're pending.
- **Bets & results** (admin): add a bet, settle pending bets with one click (Won + collect amount, or Lost), and edit or delete bets. Bets entered by punters are marked.
- **Members** (admin): add, rename or deactivate punters, and set each punter's PIN (their login link is shown next to it).
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

Data is stored in SQLite at `data/club.db`, or in the Postgres database named by `DATABASE_URL` (or `POSTGRES_URL`).

## Deploy on Vercel

Vercel detects it as a FastAPI project and serves the `app` in `api/index.py`. Don't add a `vercel.json` rewrite: Vercel now passes the rewritten path to FastAPI, so every page would 404.

1. Import the GitHub repo in Vercel (no build settings needed).
2. **Add a database.** Go to the project's **Storage** tab, create a **Neon** (Postgres) database and connect it to the project. This sets `POSTGRES_URL`/`DATABASE_URL` for you. Without it the app still runs, but Vercel wipes the data whenever the function restarts. Admins see a red warning when that's the case.
3. Under **Settings → Environment Variables**, add `ADMIN_PASSWORD` and `SECRET_KEY` (any long random string). To turn on bet-slip scanning, also add `ANTHROPIC_API_KEY` (create one at console.anthropic.com). Without it punters type their bets in instead.
4. Redeploy, open the site, log in and import the workbook under **Season & data**.

## Punters entering their own bets

1. As admin, open **Members**, type a 4-8 digit PIN next to each punter and click **Save**.
2. Send each punter their PIN and login link (shown on the Members page, e.g. `https://your-site/me/login?m=3`).
3. They open **My bets**, then either tap **Read my slip** and pick a photo or screenshot of their bet slip, or type the bet in.
4. After a scan they see the bets Claude read, with a running check against what they have left and the bet limit. They fix anything wrong, untick anything they don't want and tap **Save bets**. Nothing is saved until they do.

Punters can only add bets to the current month and only change their own pending bets. Results are still entered by the admin. After 5 wrong PINs, that punter is locked out for 15 minutes.

Slip scanning uses Claude (`claude-opus-5-5` by default; set `SLIP_MODEL` to change it) and costs a few cents per slip at most. If Claude declines to read an image, the request is automatically retried on a fallback model.

## Deploy elsewhere (Render, Railway, any host that runs Python)

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment: `ADMIN_PASSWORD`, `SECRET_KEY`, `DATABASE_URL` (Postgres) and optionally `ANTHROPIC_API_KEY`

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
app/routes/punter.py     punter PIN login and self-service bet entry
app/services/slip_reader.py  reads bet slip photos with Claude
app/templates/           pages
```

`johnsonspun.zip` holds the earlier prototype, which sent bet receipts to members over WhatsApp via Twilio. This app doesn't use it.
