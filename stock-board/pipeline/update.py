"""
One update run: pull each stock from Yahoo Finance, score and rate it, log
rating changes, grade older calls, and write the JSON files the dashboard reads.

    python -m pipeline.update

GitHub Actions runs this on a schedule (see .github/workflows/update-scores.yml).
"""

import json
import sys
import time
from datetime import datetime, timezone

from . import config
from .analyze import NotEnoughData, score_stock
from .grade import grade_calls, log_calls

SCORES_FILE = config.DATA_DIR / "scores.json"
HISTORY_FILE = config.DATA_DIR / "history.json"
SNAPSHOT_FILE = config.DATA_DIR / "snapshots.json"


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def with_retry(fn, *args):
    """Yahoo sometimes rate-limits a burst of requests; wait and try once more."""
    try:
        return fn(*args)
    except Exception as e:
        if "rate" not in str(e).lower() and "too many" not in str(e).lower():
            raise
        print(f"Rate-limited by Yahoo; waiting {config.RETRY_WAIT_SECONDS}s and retrying.", file=sys.stderr)
        time.sleep(config.RETRY_WAIT_SECONDS)
        return fn(*args)


def tickers():
    """(symbol, group) for holdings, then the watchlist, then the discovery list,
    without duplicates. group is "held", "watch" or "discover"."""
    seen, out = set(), []
    for group, syms in (("held", config.HOLDINGS), ("watch", config.WATCHLIST),
                        ("discover", getattr(config, "DISCOVERY", []))):
        for sym in syms:
            if sym not in seen:
                seen.add(sym)
                out.append((sym, group))
    return out


def etf_record(m: dict) -> dict:
    """What the dashboard shows for an ETF: no scores, just the basics."""
    return {k: m.get(k) for k in (
        "symbol", "name", "currency", "price", "day_change", "return_12m",
        "ma50", "ma200", "low52", "high52", "dividend_yield", "chart")}


def pick_recommendations(candidates: list[dict]) -> list[dict]:
    """The best Buy-rated stocks you don't own, with a cap per sector for variety."""
    count = getattr(config, "RECOMMEND_COUNT", 6)
    per_sector = getattr(config, "RECOMMEND_PER_SECTOR", 2)
    picks, by_sector = [], {}
    for s in sorted(candidates, key=lambda x: x["adjusted"], reverse=True):
        if s.get("stale") or s["held"] or s["rating"] != "Buy":
            continue
        sector = s.get("sector") or "Other"
        if by_sector.get(sector, 0) >= per_sector:
            continue
        by_sector[sector] = by_sector.get(sector, 0) + 1
        picks.append(s)
        if len(picks) >= count:
            break
    return picks


def run(fetch_stock=None, fetch_benchmark=None, now: datetime | None = None, pause: float | None = None,
        fetch_adjusted=None) -> dict:
    if fetch_stock is None or fetch_benchmark is None or fetch_adjusted is None:
        from . import yahoo_client
        fetch_stock = fetch_stock or (lambda s: yahoo_client.fetch_stock(s, config.NEWS_PER_STOCK, config.NEWS_DAYS))
        fetch_benchmark = fetch_benchmark or yahoo_client.fetch_benchmark
        fetch_adjusted = fetch_adjusted or yahoo_client.fetch_adjusted
    pause = config.PAUSE_SECONDS if pause is None else pause
    now = now or datetime.now(timezone.utc)

    old = load(SCORES_FILE, {})
    if old.get("sample"):
        old = {}   # first real run: drop the sample data
    history = load(HISTORY_FILE, {"calls": []})
    if history.get("sample"):
        history = {"calls": []}
    snapshots = load(SNAPSHOT_FILE, {})
    old_by_symbol = {s["symbol"]: s for s in old.get("stocks", [])}

    notes, failed = [], []
    try:
        bench = with_retry(fetch_benchmark, config.BENCHMARK)
    except Exception as e:
        print(f"Benchmark {config.BENCHMARK}: {e}", file=sys.stderr)
        bench = old.get("benchmark")
        notes.append(f"Couldn't refresh the {config.BENCHMARK_NAME}; relative strength uses the last value.")
    if bench:
        bench = {**bench, "name": config.BENCHMARK_NAME}

    us_symbol = getattr(config, "US_BENCHMARK", None)
    us_bench = None
    if us_symbol:
        try:
            us_bench = {**with_retry(fetch_benchmark, us_symbol), "name": config.US_BENCHMARK_NAME}
        except Exception as e:
            print(f"Benchmark {us_symbol}: {e}", file=sys.stderr)
            us_bench = old.get("us_benchmark")

    def bench_for(m):
        """US-dollar stocks are compared with the S&P 500, the rest with the TSX."""
        return us_bench if (m.get("currency") == "USD" and us_bench) else bench

    def previous(sym):
        """Last update's score and rating; older files stored just the score."""
        prev = snapshots.get(sym)
        if prev is None or isinstance(prev, dict):
            return prev
        rating = old_by_symbol.get(sym, {}).get("rating")
        return {"adjusted": prev, "rating": rating}

    old_by_symbol |= {r["symbol"]: r for r in old.get("recommended", []) if r["symbol"] not in old_by_symbol}
    stocks, prices, unscored, discovered, adjusted = [], {}, [], [], {}
    cdrs = getattr(config, "CDR_HOLDINGS", {})
    for sym, group in tickers():
        held = group == "held"
        try:
            m = with_retry(fetch_stock, sym)
            try:
                if m.get("adj_closes"):
                    adjusted[sym] = m["adj_closes"]
                rec = score_stock(m, bench_for(m), held, previous(sym))
            except NotEnoughData as e:
                if group == "discover":
                    continue   # not enough data to recommend; skip quietly
                print(f"{sym}: not enough data for {e}", file=sys.stderr)
                unscored.append({"symbol": sym, "name": m.get("name") or sym, "held": held,
                                 "price": m.get("price"), "currency": m.get("currency"),
                                 "missing": str(e), "news": m.get("news") or [],
                                 "next_earnings": m.get("next_earnings")})
                continue
            if sym in cdrs:
                rec["cdr"] = cdrs[sym]
            (discovered if group == "discover" else stocks).append(rec)
            prices[sym] = rec["price"]
        except Exception as e:
            print(f"{sym}: {e}", file=sys.stderr)
            if group == "discover":
                continue   # a missed discovery stock just isn't considered this run
            failed.append(sym)
            prev = old_by_symbol.get(sym)
            if prev:
                stocks.append({**prev, "held": held, "stale": True})
        if pause:
            time.sleep(pause)

    old_etfs = {e["symbol"]: e for e in old.get("etfs", [])}
    etfs = []
    for sym in getattr(config, "ETF_HOLDINGS", []):
        try:
            m = with_retry(fetch_stock, sym)
            if m.get("adj_closes"):
                adjusted[sym] = m["adj_closes"]
            etfs.append(etf_record(m))
            prices[sym] = etfs[-1]["price"]
        except Exception as e:
            print(f"{sym}: {e}", file=sys.stderr)
            failed.append(sym)
            if sym in old_etfs:
                etfs.append({**old_etfs[sym], "stale": True})
        if pause:
            time.sleep(pause)

    if failed:
        kept = [s["symbol"] for s in stocks if s.get("stale")]
        notes.append(f"Couldn't refresh {', '.join(failed)} from Yahoo this run."
                     + (f" Showing the last data for {', '.join(kept)}." if kept else ""))

    if not any(not s.get("stale") for s in stocks) and not unscored:
        # Nothing came back at all (Yahoo down or blocking): keep the files as they are.
        print("No stock data came back from Yahoo; leaving the existing data in place.", file=sys.stderr)
        return {"stocks": [], "failed": failed}

    stocks.sort(key=lambda s: s["adjusted"], reverse=True)
    bench_price = (bench or {}).get("price")

    watch_syms = {s["symbol"] for s in stocks if not s["held"]}
    recommended = [{**s, "source": "watchlist" if s["symbol"] in watch_syms else "new"}
                   for s in pick_recommendations(stocks + discovered)]

    # New ideas are logged too, so the results table shows how they did
    log_calls(history, stocks + [r for r in recommended if r["source"] == "new"], bench_price, now)
    grade_bench = {}
    for cur, sym in getattr(config, "GRADE_BENCHMARK", {}).items():
        try:
            grade_bench[cur] = with_retry(fetch_adjusted, sym)
        except Exception as e:
            print(f"Grading benchmark {sym}: {e}", file=sys.stderr)
    n = grade_calls(history, prices, bench_price, now, adjusted, grade_bench)

    out = {
        "generated_at": now.isoformat(),
        "benchmark": {**(bench or {}), "name": config.BENCHMARK_NAME},
        "us_benchmark": us_bench,
        "settings": {
            "weights": config.WEIGHTS,
            "max_risk_penalty": config.MAX_RISK_PENALTY,
            "held_buy_more": config.HELD_BUY_MORE, "held_hold": config.HELD_HOLD,
            "watch_buy": config.WATCH_BUY, "borderline": config.BORDERLINE,
            "grade_after_days": config.GRADE_AFTER_DAYS,
            "recommend_count": getattr(config, "RECOMMEND_COUNT", 6),
            "recommend_per_sector": getattr(config, "RECOMMEND_PER_SECTOR", 2),
            "discovery_count": len(getattr(config, "DISCOVERY", [])),
            "rating_buffer": getattr(config, "RATING_BUFFER", 0),
            "grade_benchmark_name": getattr(config, "GRADE_BENCHMARK_NAME", {}),
        },
        "notes": sorted(set(notes)),
        "failed": failed,
        "stocks": stocks,
        "recommended": recommended,
        "etfs": etfs,
        "unscored": unscored,
    }
    save(SCORES_FILE, out)
    save(HISTORY_FILE, history)
    save(SNAPSHOT_FILE, {s["symbol"]: {"adjusted": s["adjusted"], "rating": s["rating"]}
                         for s in stocks + discovered if not s.get("stale")}
         | {k: v for k, v in snapshots.items() if k in failed})
    print(f"Scored {len(stocks) - len([s for s in stocks if s.get('stale')])} stock(s), "
          f"{len(unscored)} without enough data, {len(failed)} failed, graded {n} call result(s). "
          f"Checked {len(discovered)} discovery stock(s); recommending {len(recommended)}.")
    return out


if __name__ == "__main__":
    out = run()
    if not out["stocks"] and not out.get("unscored"):
        sys.exit("No stocks could be scored. Yahoo may be blocking or down; try again later.")
