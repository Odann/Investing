# Stock Board

A personal research dashboard for TSX stocks. It scores your holdings and
watchlist on four lenses, rates each one, and tracks whether its own ratings beat
the market over time. It runs entirely on free GitHub services, with no server
to keep alive and no API key.

```
GitHub Actions (weekdays after the close)    GitHub Pages
  ├─ Yahoo Finance (yfinance): prices,          └─ docs/index.html
  │  fundamentals, dividends, news                   reads docs/data/*.json
  ├─ pipeline/ → scores, rates, grades              (loads instantly)
  └─ commits docs/data/*.json  ─────────────────▶
```

## About the "API key"

Yahoo Finance doesn't offer an official API or API key any more. This project uses
[yfinance](https://github.com/ranaroussi/yfinance), a free library that reads the
same data the Yahoo Finance website shows. That means:

- **Nothing to sign up for**, and no secret to add to GitHub.
- **It's unofficial.** Yahoo sometimes rate-limits or briefly blocks it, often
  more on cloud servers like GitHub's. When a stock fails, the run keeps its
  previous data and says so at the top of the page; the next run usually works.
  If every run fails for days, update the library version in `requirements.txt`.
- The workflow runs once a weekday to stay polite. Prices are fetched for every
  stock each run, but company data (earnings, valuation, news) is cached and
  refreshed for about a fifth of the stocks per run, plus your holdings daily.
  That cuts Yahoo requests by more than half. Tune it with `FUNDAMENTALS_*` in
  `pipeline/config.py`.

## Set it up (about 10 minutes)

1. **Make a GitHub repo.** Create a new **public** repository (free GitHub Pages
   needs a public repo). On its empty page, choose "uploading an existing file"
   and drag in **everything inside** this folder, not the folder itself.
   The `.github` folder is hidden on a Mac: in Finder, press **Cmd + Shift + .**
   to show it before you select everything. After committing, check that
   `.github/workflows/main.yml` appears at the top of the repo.
   (The project files can also sit inside a subfolder; the workflow finds them.
   Only `.github` has to be at the top.)
2. **Turn on Pages.** Settings → Pages → Build and deployment → Source:
   **GitHub Actions**.
3. **Run it once.** Actions tab → Update scores → Run workflow. When it turns
   green (about 10 minutes for ~100 stocks), your dashboard is live at
   `https://<your-username>.github.io/<repo-name>/`. Bookmark it, or use
   "Add to Home Screen" on your phone.

From then on it updates itself every weekday at about 5:37 PM Toronto time. The
page shows sample data until the first run finishes.

## Using it

- **Top-rated** is the highest adjusted score in the current view. The chips under
  the header switch between all stocks, your holdings, the watchlist, and stocks
  rated Buy.
- **Full breakdown** on any card shows each lens's measures, the risk flags, what
  would change the rating, recent headlines, and every number used. Each
  breakdown has its own link (for example `…/#RY.TO`).
- **Recommended** lists the best Buy-rated stocks you don't own. Each update
  scores your watchlist plus about 55 large TSX companies (`DISCOVERY` in
  `pipeline/config.py`), then picks the top 6, at most 2 per sector. "New idea"
  means it isn't on your watchlist yet. New ideas are logged in the results table
  too, so you can see whether they beat the index.
- **ETFs you hold** (`ETF_HOLDINGS`) appear with your holdings showing price,
  12-month return and yield. They aren't scored, because the lenses are built
  for single companies.
- **CDRs:** a Canadian CDR you hold is scored on its US shares (see
  `CDR_HOLDINGS`), with prices in USD and a note on the card.
- **Your positions** (header) lets you enter quantity and average cost for each
  holding. They're saved only in that browser, never on GitHub, and power the
  value, gain, allocation and sector-exposure panels. Enter them on each device.
- **Add a ticker** (header) checks the symbol and gives you the exact line to
  paste into `pipeline/config.py`, with a link to edit it on GitHub.
- **Search, sector filter, sort, and Cards/Table** sit above the lists. Click a
  table header to sort by it.
- **Compare** on any card or row picks up to 3 stocks for a side-by-side view.
- **Since the last update** lists rating changes, new recommendations and big
  score moves. **Coming up** shows earnings and ex-dividend dates for your
  holdings in the next 2 weeks. **The week** chip shows a weekly digest.
- The **market strip** in the header shows the TSX, S&P 500, USD/CAD and the
  best and worst sectors of the day (median move of the stocks tracked here).
- Each breakdown has a **score over time** chart, and dotted-underlined terms
  explain themselves on hover (all of them are listed in the page footer).
- **Dark mode** follows your phone or computer setting.
- **Run an update** in the header opens the GitHub page with the "Run workflow"
  button, for when you want fresher data than the schedule gives you.
- **How the ratings have done** logs every rating at that day's price when it first
  appears or changes, then compares its total return (dividends included) over
  exactly 30, 90 and 180 days with the index's: XIC for Canadian stocks, SPY for
  US ones. If the model is worth anything, Buy calls should beat the
  index more often than Sell calls. Give it a year before reading much into it.

## How stocks are scored

All the logic is in `pipeline/analyze.py`. Each lens adds up points from the
measures Yahoo provides and scales them to 0–10, so a missing number doesn't count
as zero. A stock is only rated when Trend, GARP and Quality each have at least two
measures; the rest appear under "Not enough data to score".

1. **Trend (30%):** price vs. the 50- and 200-day averages, whether the 50-day is
   above the 200-day, 12-month return vs. the S&P/TSX Composite, and position in
   the 52-week range.
2. **GARP (30%):** PEG ratio, forward P/E (trailing if there's no forecast) and
   expected EPS growth. A company with no earnings scores 1.
3. **Quality (25%):** return on equity, profit margin, debt-to-equity, free cash
   flow yield, and how often EPS rose in recent years. Banks and insurers skip
   debt and free cash flow (deposits count as debt). Utilities skip free cash flow
   and get a looser debt scale, because borrowing to build is how they grow.
4. **Dividend growth (15%):** 5-year dividend growth, payout ratio and years of
   increases. Non-payers show "n/a" and the 15% is spread over the other three.
5. **Risk adjustment (up to −1.5):** high beta, high volatility, a stretched or
   missing P/E, heavy debt, a very small company, or a drawdown of 20%+ from the
   52-week high.

6. **REITs** (Yahoo industry starting "REIT") get their own rules, because their
   earnings swing with property revaluations: GARP uses price-to-book and revenue
   growth, Quality uses operating margin and debt, the dividend skips the payout
   ratio, and losses don't count as a risk flag.
7. **US stocks** (like AMD) measure relative strength against the S&P 500.
8. **Sector-relative P/E:** GARP ranks each stock's P/E against the other stocks
   in its sector scored that run (at least 5), instead of a fixed scale.
9. **Momentum** uses the 12-month return leaving out the latest month, the
   standard version in research (the last month tends to reverse).
10. **Pipelines and utilities** have their dividend judged on operating cash
    flow instead of the payout ratio of earnings.

**Recommendations** also skip sectors you're already heavy in (2+ held stocks,
or 35%+ of an ETF you hold) and anything with a risk penalty over 1.0.

**Ratings:** stocks you hold are Buy more at 8+, Hold at 5 to 7.9, Sell below 5.
Stocks you don't hold are Buy at 7+, Don't buy below 7. Anything within 0.5 of a
line is marked Borderline. A rating only changes once the score clears the line by
0.25 (`RATING_BUFFER`), so a stock sitting on a line doesn't flip back and forth.

The rules are mechanical on purpose. They can't see things like a lawsuit, a
regulator's decision or a one-time charge, so read the breakdown and the
headlines before acting on a rating.

## Settings

Everything you'd want to change is in `pipeline/config.py`: your holdings, ETFs,
the watchlist, the discovery list and how many recommendations to show, weights, rating lines, sector rules and grading periods. The update time
is in `.github/workflows/main.yml`. If you rename that file, change
`WORKFLOW_FILE` near the top of the script in `docs/index.html` so the
"Run an update" link still works.

Yahoo symbols: TSX stocks end in `.TO`, TSX Venture in `.V`, and units or class
shares use a dash (`BEP.UN` → `BEP-UN.TO`, `BBD.A` → `BBD-A.TO`). ETFs go in
`ETF_HOLDINGS`, not `HOLDINGS`, because the lenses are built for single companies.

## Run it on your own computer

```
pip install -r requirements.txt
python -m pipeline.update
python -m http.server -d docs     # then open http://localhost:8000
```

If you change classes in `docs/index.html`, rebuild the CSS with
`npx tailwindcss@3 -i styles/input.css -o docs/styles.css --minify`.
The workflow also rebuilds it on every run.

## Good to know

- **The data is public.** The dashboard and the files in `docs/data` can be seen
  by anyone who finds the URL (search engines are asked not to index it). That
  includes which stocks you hold, so the config only takes tickers: never put
  share counts or costs in it.
- **GitHub may pause scheduled runs** in a repo with no activity for 60 days. If the
  page says the data is more than three days old, open the Actions tab and
  re-enable the workflow.
- **Currencies:** prices are in the currency the shares trade in (CAD for `.TO`
  and `.V`). Some TSX companies report in US dollars; the breakdown says so.

## Files

| Path | What it is |
| --- | --- |
| `pipeline/update.py` | One full run: fetch, score, log, grade, save |
| `pipeline/analyze.py` | The four lenses, risk adjustment and ratings |
| `pipeline/grade.py` | Logs rating changes and grades them against the index |
| `pipeline/yahoo_client.py` | Yahoo Finance calls (through yfinance) |
| `pipeline/config.py` | Settings |
| `docs/index.html` | The dashboard |
| `docs/data/scores.json` | Current scores (rewritten each run) |
| `docs/data/history.json` | Every rating logged, with results |
| `docs/data/snapshots.json` | Last run's scores and ratings |
| `docs/data/score_history.json` | Each stock's score by day, for the chart in its breakdown |
| `docs/data/fundamentals.json` | Cached company data from Yahoo (refreshed on a rotation) |
| `.github/workflows/main.yml` | The schedule |

Scores come from fixed rules applied to Yahoo Finance data, which can be delayed or
wrong. This is a research tool, not financial advice.
