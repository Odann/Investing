"""
Tracks how the ratings have done.

A "call" is logged whenever a stock first appears or its rating changes, at that
day's price. At each later update, calls that have reached 30, 90 or 180 days old
are graded: the stock's total return (dividends included) over exactly that
many days vs. an index ETF's total return over the same days (XIC for Canadian
stocks, SPY for US ones). If either total-return series is missing, it falls
back to price change vs. the price index, and marks the result "price". If good ratings mean anything, Buy calls should beat the
benchmark more often than Sell calls do.
"""

from bisect import bisect_right
from datetime import datetime, timedelta

from . import config


def parse_time(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def log_calls(history: dict, stocks: list[dict], bench_price: float | None, now: datetime) -> int:
    """Add a call for each stock that is new or whose rating changed. Returns count added."""
    last = {}
    for c in history["calls"]:
        last[c["symbol"]] = c   # calls are appended in time order, so the last one wins
    added = 0
    for s in stocks:
        if s.get("stale"):
            continue
        prev = last.get(s["symbol"])
        if prev and prev["rating"] == s["rating"]:
            continue
        history["calls"].append({
            "id": f"{s['symbol']}|{now.date().isoformat()}|{s['rating']}",
            "symbol": s["symbol"],
            "name": s["name"],
            "rating": s["rating"],
            "held": s["held"],
            "score": s["adjusted"],
            "logged_at": now.isoformat(),
            "price": s["price"],
            "currency": s.get("currency") or "CAD",
            "bench_price": bench_price,
            "results": {},
        })
        added += 1
    return added


def value_on(series: dict, day: str):
    """The last value on or before `day` ("YYYY-MM-DD"), from {date: value}."""
    if not series:
        return None
    days = sorted(series)
    i = bisect_right(days, day)
    return series[days[i - 1]] if i else None


def total_return(series: dict, start: str, end: str):
    a, b = value_on(series, start), value_on(series, end)
    if not a or not b or not series or min(series) > start:
        return None
    return b / a - 1


def grade_calls(history: dict, prices: dict, bench_price: float | None, now: datetime,
                adjusted: dict | None = None, grade_bench: dict | None = None) -> int:
    """Fill in each horizon a call has reached. `prices` is {symbol: today's price}.
    `adjusted` is {symbol: {date: dividend-adjusted close}} and `grade_bench` is
    {currency: {date: adjusted close}} for the total-return comparison."""
    adjusted, grade_bench = adjusted or {}, grade_bench or {}
    graded = 0
    for c in history["calls"]:
        logged = parse_time(c["logged_at"])
        age = (now - logged).days
        for h in config.GRADE_AFTER_DAYS:
            key = str(h)
            if key in c["results"] or age < h:
                continue
            start, end = logged.date().isoformat(), (logged + timedelta(days=h)).date().isoformat()
            ret = total_return(adjusted.get(c["symbol"]), start, end)
            bench = total_return(grade_bench.get(c.get("currency") or "CAD"), start, end)
            if ret is not None and bench is not None:
                c["results"][key] = {
                    "graded_at": now.isoformat(),
                    "price": prices.get(c["symbol"]),
                    "return": round(ret, 4),
                    "benchmark": round(bench, 4),
                    "excess": round(ret - bench, 4),
                    "basis": "total",
                }
                graded += 1
                continue
            price = prices.get(c["symbol"])
            if price is None or not c.get("price"):
                continue   # dropped from the list or no price today; try again next run
            ret = price / c["price"] - 1
            bench = (bench_price / c["bench_price"] - 1) if (bench_price and c.get("bench_price")) else None
            c["results"][key] = {
                "graded_at": now.isoformat(),
                "price": price,
                "return": round(ret, 4),
                "benchmark": round(bench, 4) if bench is not None else None,
                "excess": round(ret - bench, 4) if bench is not None else None,
                "basis": "price",
            }
            graded += 1
    return graded
