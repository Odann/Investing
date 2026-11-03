"""All the settings you're likely to want to change, in one place."""

from pathlib import Path

# ---------- What to track ----------
# Yahoo Finance symbols: TSX stocks end in .TO, TSX Venture in .V.
# Units and class shares use a dash: BEP.UN -> BEP-UN.TO, BBD.A -> BBD-A.TO.
# ETFs are left out on purpose: the four lenses are built for single companies.

# Stocks you own. Only the ticker goes here, never quantities or costs:
# everything in docs/data is public.
HOLDINGS = ["RY.TO", "H.TO", "CS.TO", "EPRX.TO", "AXL.V"]

WATCHLIST = [
    "CCO.TO", "BEP-UN.TO", "K.TO", "CVO.TO", "CNR.TO", "CJT.TO", "CLS.TO",
    "TD.TO", "SAP.TO", "KXS.TO", "BNS.TO", "BBD-A.TO", "SU.TO", "CVE.TO",
    "POW.TO", "MFC.TO", "MG.TO", "NPI.TO", "NA.TO", "ABX.TO", "SVI.TO",
    "CU.TO", "T.TO", "CSU.TO", "AEM.TO", "HR-UN.TO", "DCBO.TO", "FTS.TO",
    "AQN.TO", "ALA.TO", "DOL.TO", "TRP.TO", "ENB.TO",
]

# Relative strength is measured against this. ^GSPTSE is the S&P/TSX Composite.
BENCHMARK = "^GSPTSE"
BENCHMARK_NAME = "S&P/TSX Composite"

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
