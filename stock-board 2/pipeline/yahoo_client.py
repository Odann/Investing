"""
Pulls what the scoring needs from Yahoo Finance, using the yfinance library.

Yahoo has no official public API or API key. yfinance reads the same data the
Yahoo Finance website shows, for free. It is unofficial, so Yahoo can change or
rate-limit it; when a ticker fails, the run keeps that stock's previous data.
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


def price_history(symbol: str):
    """Daily closes for the last 13 months (a little extra for the 12-month return)."""
    start = (date.today() - timedelta(days=400)).isoformat()
    hist = yf.Ticker(symbol).history(start=start, interval="1d", auto_adjust=False)
    if hist is None or hist.empty or "Close" not in hist:
        raise YahooError(f"{symbol}: no price history")
    return hist["Close"].dropna()


def twelve_month_return(closes):
    if len(closes) < 2:
        return None
    end = closes.index[-1]
    start_cut = end - timedelta(days=365)
    past = closes[closes.index <= start_cut]
    base = past.iloc[-1] if len(past) else closes.iloc[0]
    return float(closes.iloc[-1] / base - 1)


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
    s = divs.copy()
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


def fetch_stock(symbol: str, news_items: int = 3, news_days: int = 90) -> dict:
    """Everything the scoring and the dashboard need for one stock."""
    t = yf.Ticker(symbol)
    try:
        info = t.info or {}
    except Exception as e:
        raise YahooError(f"{symbol}: {e}") from e
    closes = price_history(symbol)
    price = _first(info, "currentPrice", "regularMarketPrice") or float(closes.iloc[-1])
    prev_close = _first(info, "regularMarketPreviousClose", "previousClose")

    try:
        divs = t.dividends
    except Exception:
        divs = None
    div = dividend_stats(divs)

    trailing_eps = _first(info, "trailingEps")
    forward_eps = _first(info, "forwardEps")
    eps_growth_next = (forward_eps / trailing_eps - 1) if (forward_eps and trailing_eps and trailing_eps > 0) else None

    fcf = _first(info, "freeCashflow")
    mcap = _first(info, "marketCap")
    # Yahoo's own yield field has switched between fraction and percent over the
    # years, so the yield is worked out from the dividend rate instead.
    div_rate = _first(info, "dividendRate") or (div["ttm"] or None)

    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency") or "CAD",
        "financial_currency": info.get("financialCurrency"),
        "price": round(price, 4),
        "day_change": (price / prev_close - 1) if prev_close else None,
        "ma50": _first(info, "fiftyDayAverage"),
        "ma200": _first(info, "twoHundredDayAverage"),
        "low52": _first(info, "fiftyTwoWeekLow"),
        "high52": _first(info, "fiftyTwoWeekHigh"),
        "return_12m": twelve_month_return(closes),
        "volatility": annual_volatility(closes),
        "beta": _first(info, "beta"),
        "market_cap": mcap,
        "forward_pe": _first(info, "forwardPE"),
        "trailing_pe": _first(info, "trailingPE"),
        "peg": _first(info, "trailingPegRatio", "pegRatio"),
        "trailing_eps": trailing_eps,
        "forward_eps": forward_eps,
        "eps_growth_next": eps_growth_next,
        "earnings_growth_q": _first(info, "earningsGrowth"),
        "revenue_growth": _first(info, "revenueGrowth"),
        "eps_history": eps_history(t),
        "roe": _first(info, "returnOnEquity"),
        "profit_margin": _first(info, "profitMargins"),
        "operating_margin": _first(info, "operatingMargins"),
        "debt_to_equity": _first(info, "debtToEquity"),   # Yahoo gives this as a percent
        "free_cash_flow": fcf,
        "fcf_yield": (fcf / mcap) if (fcf is not None and mcap) else None,
        "dividend_rate": div_rate,
        "dividend_yield": (div_rate / price) if (div_rate and price) else None,
        "payout_ratio": _first(info, "payoutRatio"),
        "dividend_growth_1y": div["growth_1y"],
        "dividend_cagr_5y": div["cagr_5y"],
        "dividend_years_raised": div["years_raised"],
        "target_price": _first(info, "targetMeanPrice"),
        "analyst_rating": info.get("recommendationKey"),
        "analyst_count": _first(info, "numberOfAnalystOpinions"),
        "next_earnings": next_earnings(t),
        "news": headlines(t, news_items, news_days),
        "chart": weekly_chart(closes),
    }


def fetch_benchmark(symbol: str) -> dict:
    closes = price_history(symbol)
    return {"symbol": symbol, "price": round(float(closes.iloc[-1]), 2),
            "return_12m": twelve_month_return(closes)}
