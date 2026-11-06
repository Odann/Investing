"""
Pulls what the scoring needs from Yahoo Finance, using the yfinance library.

Yahoo has no official public API or API key. yfinance reads the same data the
Yahoo Finance website shows, for free. It is unofficial, so Yahoo can change or
rate-limit it; when a ticker fails, the run keeps that stock's previous data.

To keep the number of requests down, each stock's data comes in two parts:
- Prices: one price-history request per stock, every run. Moving averages, the
  52-week range, returns, volatility, dividends and the chart all come from it.
- Fundamentals: the company profile, earnings, valuation, news and ETF
  holdings. These change slowly, so they're cached in docs/data/fundamentals.json
  and refreshed on a rotation (see FUNDAMENTALS_* in config.py).
"""

import math
from datetime import date, datetime, timedelta, timezone

import yfinance as yf


class YahooError(RuntimeError):
    pass


def _num(x):
    """A clean float, or None for missing / NaN / infinite values."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _first(info: dict, *keys):
    for k in keys:
        v = _num(info.get(k))
        if v is not None:
            return v
    return None


# ---------- Prices (every run) ----------
def _history(symbol: str):
    """Daily prices and dividends for the last 13 months."""
    start = (date.today() - timedelta(days=400)).isoformat()
    hist = yf.Ticker(symbol).history(start=start, interval="1d", auto_adjust=False, actions=True)
    if hist is None or hist.empty or "Close" not in hist:
        raise YahooError(f"{symbol}: no price history")
    return hist


def price_history(symbol: str):
    """Daily closes, as traded."""
    return _history(symbol)["Close"].dropna()


def adjusted_by_date(hist) -> dict:
    """{"YYYY-MM-DD": close adjusted for dividends and splits}. Comparing two of
    these gives the total return between the dates, dividends included."""
    col = "Adj Close" if "Adj Close" in hist else "Close"
    series = hist[col].dropna()
    return {d.strftime("%Y-%m-%d"): round(float(v), 4) for d, v in series.items()}


def fetch_adjusted(symbol: str) -> dict:
    """Total-return price series for one symbol (used for the grading benchmark)."""
    return adjusted_by_date(_history(symbol))


def trailing_return(closes, days_back: int, skip_days: int = 0):
    """Return from `days_back` calendar days ago to `skip_days` ago."""
    if len(closes) < 2:
        return None
    end_date = closes.index[-1] - timedelta(days=skip_days)
    ends = closes[closes.index <= end_date]
    if not len(ends):
        return None
    start_cut = closes.index[-1] - timedelta(days=days_back)
    past = closes[closes.index <= start_cut]
    base = past.iloc[-1] if len(past) else closes.iloc[0]
    return float(ends.iloc[-1] / base - 1)


def twelve_month_return(closes):
    return trailing_return(closes, 365)


def annual_volatility(closes):
    """Standard deviation of daily returns over the last year, annualized."""
    rets = closes.pct_change().dropna().tail(252)
    if len(rets) < 60:
        return None
    return float(rets.std() * math.sqrt(252))


def weekly_chart(closes, points=52):
    """Last year of weekly closes, for the sparkline on each card."""
    weekly = closes.resample("W-FRI").last().dropna().tail(points)
    return [round(float(v), 4) for v in weekly]


def dividend_stats(divs, today: date | None = None):
    """
    From the payment history: last 12 months paid, growth over 1 and 5 years,
    and how many consecutive calendar years the total went up.
    """
    today = today or date.today()
    if divs is None or len(divs) == 0:
        return {"ttm": 0.0, "growth_1y": None, "cagr_5y": None, "years_raised": 0}
    s = divs[divs > 0].copy()
    if not len(s):
        return {"ttm": 0.0, "growth_1y": None, "cagr_5y": None, "years_raised": 0}
    try:
        s.index = s.index.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    cutoff = datetime(today.year, today.month, today.day)
    ttm = float(s[s.index > cutoff - timedelta(days=365)].sum())
    prev = float(s[(s.index > cutoff - timedelta(days=730)) & (s.index <= cutoff - timedelta(days=365))].sum())
    five_ago = float(s[(s.index > cutoff - timedelta(days=6 * 365)) & (s.index <= cutoff - timedelta(days=5 * 365))].sum())

    # Full calendar years only (the current year is still being paid)
    yearly = s.groupby(s.index.year).sum()
    yearly = yearly[yearly.index < today.year]
    streak = 0
    vals = list(yearly.values)
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i - 1] * 1.0001:
            streak += 1
        else:
            break
    return {
        "ttm": round(ttm, 4),
        "growth_1y": (ttm / prev - 1) if prev > 0 and ttm > 0 else None,
        "cagr_5y": ((ttm / five_ago) ** (1 / 5) - 1) if five_ago > 0 and ttm > 0 else None,
        "years_raised": streak,
    }


def fetch_prices(symbol: str) -> dict:
    """Everything that comes from the price history: one request."""
    hist = _history(symbol)
    closes = hist["Close"].dropna()
    price = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2]) if len(closes) > 1 else None
    year = closes[closes.index > closes.index[-1] - timedelta(days=365)]
    week_ago = closes[closes.index <= closes.index[-1] - timedelta(days=7)]
    # Dividend history: the 13 months in the price request, plus older payments
    # from the cached fundamentals (merged in fetch_stock) for 5-year growth.
    divs = hist["Dividends"] if "Dividends" in hist else None
    return {
        "price": round(price, 4),
        "day_change": (price / prev_close - 1) if prev_close else None,
        "week_change": (price / float(week_ago.iloc[-1]) - 1) if len(week_ago) else None,
        "ma50": float(closes.tail(50).mean()) if len(closes) >= 50 else None,
        "ma200": float(closes.tail(200).mean()) if len(closes) >= 200 else None,
        "low52": float(year.min()),
        "high52": float(year.max()),
        "return_12m": twelve_month_return(closes),
        # Classic momentum: 12 months back to 1 month ago, skipping the latest month
        "return_12_1": trailing_return(closes, 365, skip_days=30),
        "volatility": annual_volatility(closes),
        "chart": weekly_chart(closes),
        "adj_closes": adjusted_by_date(hist),   # for grading only; not saved
        "recent_dividends": {d.strftime("%Y-%m-%d"): float(v) for d, v in (divs[divs > 0].items() if divs is not None else [])},
        "as_of": closes.index[-1].strftime("%Y-%m-%d"),
    }


# ---------- Fundamentals (cached, refreshed on a rotation) ----------
def eps_history(ticker):
    """Diluted EPS for the last few fiscal years, oldest first."""
    try:
        inc = ticker.income_stmt
    except Exception:
        return []
    if inc is None or inc.empty:
        return []
    for row in ("Diluted EPS", "Basic EPS"):
        if row in inc.index:
            series = inc.loc[row].dropna().sort_index()
            return [round(float(v), 4) for v in series.values]
    return []


def headlines(ticker, max_items: int, max_days: int):
    """Recent news, normalized across the two formats yfinance has returned."""
    try:
        raw = ticker.news or []
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
    out = []
    for item in raw:
        c = item.get("content", item)
        title = c.get("title")
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
               or c.get("link"))
        source = (c.get("provider") or {}).get("displayName") or c.get("publisher")
        when = c.get("pubDate") or c.get("displayTime")
        if when is None and c.get("providerPublishTime"):
            when = datetime.fromtimestamp(c["providerPublishTime"], timezone.utc).isoformat()
        if not title or not url:
            continue
        try:
            if when and datetime.fromisoformat(when.replace("Z", "+00:00")) < cutoff:
                continue
        except ValueError:
            pass
        out.append({"title": title, "url": url, "source": source, "published": when})
        if len(out) >= max_items:
            break
    return out


def next_earnings(ticker):
    try:
        cal = ticker.calendar or {}
    except Exception:
        return None
    dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
    if not dates:
        return None
    d = dates[0] if isinstance(dates, (list, tuple)) else dates
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _date_from_ts(x):
    v = _num(x)
    if v is None:
        return None
    try:
        return datetime.fromtimestamp(v, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


# Yahoo's fund sector keys -> the sector names Yahoo uses for companies
FUND_SECTORS = {
    "realestate": "Real Estate", "consumer_cyclical": "Consumer Cyclical",
    "basic_materials": "Basic Materials", "consumer_defensive": "Consumer Defensive",
    "technology": "Technology", "communication_services": "Communication Services",
    "financial_services": "Financial Services", "utilities": "Utilities",
    "industrials": "Industrials", "energy": "Energy", "healthcare": "Healthcare",
}


def fund_look_through(ticker, top_n: int = 10):
    """Sector weights and largest holdings of an ETF, when Yahoo has them."""
    try:
        fd = ticker.funds_data
    except Exception:
        return None
    out = {}
    try:
        sw = fd.sector_weightings or {}
        sectors = {FUND_SECTORS.get(k, k): round(float(v), 4) for k, v in sw.items() if _num(v)}
        if sectors:
            out["sectors"] = dict(sorted(sectors.items(), key=lambda kv: -kv[1]))
    except Exception:
        pass
    try:
        th = fd.top_holdings
        if th is not None and not th.empty:
            col = "Holding Percent" if "Holding Percent" in th.columns else th.columns[-1]
            name_col = "Name" if "Name" in th.columns else None
            out["top_holdings"] = [
                {"symbol": str(sym), "name": str(row[name_col]) if name_col else str(sym),
                 "weight": round(float(row[col]), 4)}
                for sym, row in th.head(top_n).iterrows() if _num(row[col]) is not None]
    except Exception:
        pass
    return out or None


def fetch_fundamentals(symbol: str, news_items: int = 3, news_days: int = 90, etf: bool = False) -> dict:
    """The slow-changing data. Several requests, so it's cached between runs."""
    t = yf.Ticker(symbol)
    try:
        info = t.info or {}
    except Exception as e:
        raise YahooError(f"{symbol}: {e}") from e
    if not info:
        raise YahooError(f"{symbol}: no profile data")

    try:
        divs = t.dividends
    except Exception:
        divs = None
    older_divs = {}
    if divs is not None and len(divs):
        cutoff = (date.today() - timedelta(days=7 * 365)).isoformat()
        older_divs = {d.strftime("%Y-%m-%d"): round(float(v), 6) for d, v in divs.items()
                      if v > 0 and d.strftime("%Y-%m-%d") >= cutoff}

    trailing_eps = _first(info, "trailingEps")
    forward_eps = _first(info, "forwardEps")
    out = {
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency") or "CAD",
        "financial_currency": info.get("financialCurrency"),
        "beta": _first(info, "beta", "beta3Year"),
        "market_cap": _first(info, "marketCap"),
        "shares": _first(info, "sharesOutstanding", "impliedSharesOutstanding"),
        "trailing_eps": trailing_eps,
        "forward_eps": forward_eps,
        "peg": _first(info, "trailingPegRatio", "pegRatio"),
        "earnings_growth_q": _first(info, "earningsGrowth"),
        "revenue_growth": _first(info, "revenueGrowth"),
        "roe": _first(info, "returnOnEquity"),
        "profit_margin": _first(info, "profitMargins"),
        "operating_margin": _first(info, "operatingMargins"),
        "debt_to_equity": _first(info, "debtToEquity"),   # Yahoo gives this as a percent
        "free_cash_flow": _first(info, "freeCashflow"),
        "operating_cash_flow": _first(info, "operatingCashflow"),
        "book_value": _first(info, "bookValue"),
        "dividend_rate_info": _first(info, "dividendRate", "trailingAnnualDividendRate"),
        "payout_ratio": _first(info, "payoutRatio"),
        "ex_dividend_date": _date_from_ts(info.get("exDividendDate")),
        "target_price": _first(info, "targetMeanPrice"),
        "analyst_rating": info.get("recommendationKey"),
        "analyst_count": _first(info, "numberOfAnalystOpinions"),
        "expense_ratio": _first(info, "netExpenseRatio", "annualReportExpenseRatio"),
        "dividend_history": older_divs,
        "news": headlines(t, news_items, news_days),
    }
    if etf:
        out["look_through"] = fund_look_through(t)
    else:
        out["eps_history"] = eps_history(t)
        out["next_earnings"] = next_earnings(t)
    return out


def combine(symbol: str, prices: dict, fund: dict) -> dict:
    """Merge prices and fundamentals into the record the scoring reads.
    Valuation ratios are recomputed from today's price, so cached fundamentals
    don't leave P/E or yield stale."""
    price = prices["price"]
    teps, feps = fund.get("trailing_eps"), fund.get("forward_eps")

    divs = {**(fund.get("dividend_history") or {}), **(prices.get("recent_dividends") or {})}
    div = {"ttm": 0.0, "growth_1y": None, "cagr_5y": None, "years_raised": 0}
    if divs:
        import pandas as pd
        s = pd.Series(divs)
        s.index = pd.to_datetime(s.index)
        div = dividend_stats(s.sort_index())
    div_rate = div["ttm"] or fund.get("dividend_rate_info") or None
    if fund.get("dividend_rate_info") and div["ttm"] and fund["dividend_rate_info"] > div["ttm"]:
        div_rate = fund["dividend_rate_info"]   # Yahoo's forward rate catches a fresh raise

    mcap = (fund.get("shares") * price) if fund.get("shares") else fund.get("market_cap")
    fcf, ocf = fund.get("free_cash_flow"), fund.get("operating_cash_flow")
    bv = fund.get("book_value")
    cash_payout = None
    if div_rate and fund.get("shares") and ocf and ocf > 0:
        cash_payout = div_rate * fund["shares"] / ocf

    return {
        "symbol": symbol,
        **{k: fund.get(k) for k in (
            "name", "sector", "industry", "currency", "financial_currency", "beta", "trailing_eps",
            "forward_eps", "peg", "earnings_growth_q", "revenue_growth", "roe", "profit_margin",
            "operating_margin", "debt_to_equity", "free_cash_flow", "payout_ratio", "ex_dividend_date",
            "target_price", "analyst_rating", "analyst_count", "expense_ratio", "next_earnings",
            "look_through")},
        **{k: prices.get(k) for k in (
            "price", "day_change", "week_change", "ma50", "ma200", "low52", "high52", "return_12m",
            "return_12_1", "volatility", "chart", "adj_closes", "as_of")},
        "name": fund.get("name") or symbol,
        "currency": fund.get("currency") or "CAD",
        "market_cap": mcap,
        "forward_pe": (price / feps) if feps and feps > 0 else None,
        "trailing_pe": (price / teps) if teps and teps > 0 else None,
        "eps_growth_next": (feps / teps - 1) if (feps and teps and teps > 0) else None,
        "eps_history": fund.get("eps_history") or [],
        "fcf_yield": (fcf / mcap) if (fcf is not None and mcap) else None,
        "price_to_book": (price / bv) if bv and bv > 0 else None,
        "dividend_rate": div_rate,
        "dividend_yield": (div_rate / price) if (div_rate and price) else None,
        "cash_payout": cash_payout,
        "dividend_growth_1y": div["growth_1y"],
        "dividend_cagr_5y": div["cagr_5y"],
        "dividend_years_raised": div["years_raised"],
        "news": fund.get("news") or [],
    }


def fetch_stock(symbol: str, news_items: int = 3, news_days: int = 90,
                fundamentals: dict | None = None, etf: bool = False) -> dict:
    """Prices always; fundamentals only when none are passed in (cache miss or
    due for a refresh). The fresh fundamentals come back under "_fundamentals"
    so the caller can cache them."""
    prices = fetch_prices(symbol)
    fresh = None
    if fundamentals is None:
        fresh = fetch_fundamentals(symbol, news_items, news_days, etf=etf)
        fundamentals = fresh
    m = combine(symbol, prices, fundamentals)
    if fresh is not None:
        m["_fundamentals"] = fresh
    return m


def fetch_benchmark(symbol: str) -> dict:
    hist = _history(symbol)
    closes = hist["Close"].dropna()
    prev = float(closes.iloc[-2]) if len(closes) > 1 else None
    price = float(closes.iloc[-1])
    return {"symbol": symbol, "price": round(price, 4),
            "day_change": (price / prev - 1) if prev else None,
            "return_12m": twelve_month_return(closes),
            "return_12_1": trailing_return(closes, 365, skip_days=30)}
