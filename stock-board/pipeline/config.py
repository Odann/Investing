"""All the settings you're likely to want to change, in one place."""

from pathlib import Path

# ---------- What to track ----------
# Yahoo Finance symbols: TSX stocks end in .TO, TSX Venture in .V.
# Units and class shares use a dash: BEP.UN -> BEP-UN.TO, BBD.A -> BBD-A.TO.
# ETFs are left out on purpose: the four lenses are built for single companies.

# Stocks you own. Only the ticker goes here, never quantities or costs:
# everything in docs/data is public.
# AMD: you hold the Canadian CDR (AMD.NE), but Yahoo has little company data
# for CDRs, so it's scored on the Nasdaq shares (prices shown in USD).
HOLDINGS = ["RY.TO", "SU.TO", "AXL.V", "AMD"]

# Held CDRs scored on their US shares: {scored symbol: the CDR you hold}.
# Shown as a note on the card.
CDR_HOLDINGS = {"AMD": "AMD.NE"}

# ETFs you own. The four lenses don't fit funds, so these are shown with price,
# 12-month return and yield but not scored or rated.
ETF_HOLDINGS = ["VFV.TO", "VDY.TO"]

WATCHLIST = [
    "CCO.TO", "BEP-UN.TO", "K.TO", "CVO.TO", "CNR.TO", "CJT.TO", "CLS.TO",
    "TD.TO", "SAP.TO", "KXS.TO", "BNS.TO", "BBD-A.TO", "CVE.TO",
    "POW.TO", "MFC.TO", "MG.TO", "NPI.TO", "NA.TO", "ABX.TO", "SVI.TO",
    "CU.TO", "T.TO", "CSU.TO", "AEM.TO", "HR-UN.TO", "DCBO.TO", "FTS.TO",
    "AQN.TO", "ALA.TO", "DOL.TO", "TRP.TO", "ENB.TO",
    "H.TO", "CS.TO", "EPRX.TO",   # former holdings, still tracked
]

# ---------- Recommendations ----------
# Each update also scores these large TSX companies. The best Buy-rated stocks
# you don't own (from this list and the watchlist) show up as "Recommended".
# Stocks here that fail to load or lack data are skipped quietly.
DISCOVERY = [
    # Financials
    "BMO.TO", "CM.TO", "SLF.TO", "GWO.TO", "IFC.TO", "BN.TO", "BAM.TO",
    "FFH.TO", "X.TO", "EQB.TO",
    # Energy
    "CNQ.TO", "IMO.TO", "TOU.TO", "ARX.TO", "PPL.TO", "KEY.TO", "WCP.TO",
    # Materials
    "NTR.TO", "WPM.TO", "FNV.TO", "TECK-B.TO", "FM.TO", "LUN.TO", "IVN.TO",
    "CCL-B.TO",
    # Industrials
    "CP.TO", "WSP.TO", "TFII.TO", "STN.TO", "TIH.TO", "WCN.TO", "RBA.TO",
    "CAE.TO", "GFL.TO", "ATRL.TO", "AC.TO",
    # Technology
    "SHOP.TO", "OTEX.TO", "GIB-A.TO", "DSG.TO", "TOI.V",
    # Consumer
    "ATD.TO", "L.TO", "MRU.TO", "WN.TO", "QSR.TO", "GIL.TO", "CTC-A.TO",
    "EMP-A.TO",
    # Telecom and utilities
    "BCE.TO", "RCI-B.TO", "QBR-B.TO", "EMA.TO", "CPX.TO", "BLX.TO",
]
RECOMMEND_COUNT = 6        # how many to show
RECOMMEND_PER_SECTOR = 2   # at most this many from one sector, for variety
RECOMMEND_MAX_RISK = 1.0   # skip stocks with a bigger risk penalty (medium risk tolerance)
# Sectors you already have plenty of aren't recommended. A sector counts as
# heavy if you hold 2+ stocks in it, or an ETF you hold has 35%+ of its money
# there. Add sectors here to skip them too.
HEAVY_SECTORS = []
HEAVY_ETF_WEIGHT = 0.35

# ---------- Yahoo request budget ----------
# Prices are fetched every run (one request per stock). Fundamentals (profile,
# earnings, valuation, news) take several requests, so they're cached and
# refreshed on a rotation: about 1/FUNDAMENTALS_SPREAD of the stocks each run,
# never older than FUNDAMENTALS_MAX_AGE_DAYS. Holdings refresh every run so
# their news and earnings dates stay current.
FUNDAMENTALS_SPREAD = 5
FUNDAMENTALS_MAX_AGE_DAYS = 8
FUNDAMENTALS_DAILY_FOR_HOLDINGS = True
SCORE_HISTORY_POINTS = 260   # about a year of weekday updates per stock

# Extras for the market strip at the top of the page
FX_SYMBOL = "CAD=X"          # Canadian dollars per US dollar

# Relative strength is measured against this. ^GSPTSE is the S&P/TSX Composite.
BENCHMARK = "^GSPTSE"
BENCHMARK_NAME = "S&P/TSX Composite"

# Stocks that trade in US dollars (like AMD) are compared with the S&P 500 instead.
US_BENCHMARK = "^GSPC"
US_BENCHMARK_NAME = "S&P 500"

# Ratings are graded on total return (dividends included), so they're compared
# with index ETFs, whose adjusted prices include dividends. The indexes above
# are price-only.
GRADE_BENCHMARK = {"CAD": "XIC.TO", "USD": "SPY"}
GRADE_BENCHMARK_NAME = {"CAD": "S&P/TSX Composite (XIC, with dividends)",
                        "USD": "S&P 500 (SPY, with dividends)"}

# ---------- Scoring ----------
# Composite weights. A stock with no dividend has its dividend weight spread
# proportionally across the other three lenses.
WEIGHTS = {"trend": 0.30, "garp": 0.30, "quality": 0.25, "dividend": 0.15}

# Medium-risk adjustment: points subtracted after the composite, capped here.
MAX_RISK_PENALTY = 1.5

# Rating thresholds on the adjusted score
HELD_BUY_MORE = 8.0       # held: 8+ Buy more
HELD_HOLD = 5.0           # held: 5 to 7.9 Hold, below 5 Sell
WATCH_BUY = 7.0           # not held: 7+ Buy, below 7 Don't buy
BORDERLINE = 0.5          # flag scores within this distance of a threshold

# Sectors where debt-to-equity and free cash flow don't mean what they do
# elsewhere (deposits and policy liabilities count as debt). Quality uses ROE
# and margins only for these.
FINANCIAL_SECTORS = {"Financial Services"}

# Regulated utilities borrow to build the assets their rates are set on, so
# negative free cash flow is normal for them. Quality skips free cash flow and
# allows more debt (full marks up to debt-to-equity 1.0, none at 3.0 instead
# of 0.5 and 2.0), and the heavy-debt risk flag starts at 3.0 instead of 2.0.
UTILITY_SECTORS = {"Utilities"}

# REITs report earnings that swing with property revaluations, and pay out
# from funds from operations (FFO), which Yahoo doesn't provide. For these,
# GARP uses price-to-book and revenue growth, Quality uses the utility debt scale
# and skips free cash flow and EPS consistency, Dividend skips the payout ratio,
# and losses don't trigger risk flags. Yahoo's REIT industries all start with
# "REIT" (e.g. "REIT - Diversified"); real estate service companies don't.
REIT_INDUSTRY_PREFIX = "REIT"

# Pipelines and utilities pay dividends from cash flow. For these (and any
# sector in UTILITY_SECTORS), the dividend lens uses dividends as a share of
# operating cash flow instead of the payout ratio of earnings.
CASH_PAYOUT_INDUSTRIES = {"Oil & Gas Midstream"}

# GARP judges P/E against the other stocks in the same sector scored that run,
# when there are at least this many of them (fewer: a fixed P/E scale).
SECTOR_MIN_PEERS = 5

# A rating only changes once the score clears the line by this much, so a stock
# sitting on a line doesn't flip between ratings (and log a new call) every day.
RATING_BUFFER = 0.25

# ---------- Results tracking ----------
# Every rating is logged with the price on the day it appeared, then graded
# against the benchmark after each of these horizons.
GRADE_AFTER_DAYS = [30, 90, 180]

# ---------- Politeness toward Yahoo ----------
PAUSE_SECONDS = 0.6       # wait between tickers so Yahoo doesn't rate-limit the run
RETRY_WAIT_SECONDS = 20  # if Yahoo rate-limits anyway, wait this long and retry once
NEWS_DAYS = 90            # headlines older than this aren't shown as catalysts
NEWS_PER_STOCK = 3

# Where the dashboard reads its data from
DATA_DIR = Path(__file__).resolve().parent.parent / "docs" / "data"
