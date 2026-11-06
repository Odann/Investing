"""
Tracks how the ratings have done.

A "call" is logged whenever a stock first appears or its rating changes, at that
day's price. At each later update, calls that have reached 30, 90 or 180 days old
are graded: the stock's return since the call vs. the benchmark's return over
the same stretch. If good ratings mean anything, Buy calls should beat the
benchmark more often than Sell calls do.
"""

from datetime import datetime

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
            "bench_price": bench_price,
            "results": {},
        })
        added += 1
    return added


def grade_calls(history: dict, prices: dict, bench_price: float | None, now: datetime) -> int:
    """Fill in each horizon a call has reached. `prices` is {symbol: today's price}."""
    graded = 0
    for c in history["calls"]:
        age = (now - parse_time(c["logged_at"])).days
        for h in config.GRADE_AFTER_DAYS:
            key = str(h)
            if key in c["results"] or age < h:
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
            }
            graded += 1
    return graded
