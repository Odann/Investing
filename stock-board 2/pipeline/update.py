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
    """Holdings first, then the watchlist, without duplicates."""
    seen, out = set(), []
    for sym in config.HOLDINGS + config.WATCHLIST:
        if sym not in seen:
            seen.add(sym)
            out.append((sym, sym in config.HOLDINGS))
    return out


def run(fetch_stock=None, fetch_benchmark=None, now: datetime | None = None, pause: float | None = None) -> dict:
    if fetch_stock is None or fetch_benchmark is None:
        from . import yahoo_client
        fetch_stock = fetch_stock or (lambda s: yahoo_client.fetch_stock(s, config.NEWS_PER_STOCK, config.NEWS_DAYS))
        fetch_benchmark = fetch_benchmark or yahoo_client.fetch_benchmark
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

    stocks, prices, unscored = [], {}, []
    for sym, held in tickers():
        try:
            m = with_retry(fetch_stock, sym)
            try:
                rec = score_stock(m, bench, held, snapshots.get(sym))
            except NotEnoughData as e:
                print(f"{sym}: not enough data for {e}", file=sys.stderr)
                unscored.append({"symbol": sym, "name": m.get("name") or sym, "held": held,
                                 "price": m.get("price"), "currency": m.get("currency"),
                                 "missing": str(e), "news": m.get("news") or [],
                                 "next_earnings": m.get("next_earnings")})
                continue
            stocks.append(rec)
            prices[sym] = rec["price"]
        except Exception as e:
            print(f"{sym}: {e}", file=sys.stderr)
            failed.append(sym)
            prev = old_by_symbol.get(sym)
            if prev:
                stocks.append({**prev, "held": held, "stale": True})
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

    log_calls(history, stocks, bench_price, now)
    n = grade_calls(history, prices, bench_price, now)

    out = {
        "generated_at": now.isoformat(),
        "benchmark": {**(bench or {}), "name": config.BENCHMARK_NAME},
        "settings": {
            "weights": config.WEIGHTS,
            "max_risk_penalty": config.MAX_RISK_PENALTY,
            "held_buy_more": config.HELD_BUY_MORE, "held_hold": config.HELD_HOLD,
            "watch_buy": config.WATCH_BUY, "borderline": config.BORDERLINE,
            "grade_after_days": config.GRADE_AFTER_DAYS,
        },
        "notes": sorted(set(notes)),
        "failed": failed,
        "stocks": stocks,
        "unscored": unscored,
    }
    save(SCORES_FILE, out)
    save(HISTORY_FILE, history)
    save(SNAPSHOT_FILE, {s["symbol"]: s["adjusted"] for s in stocks if not s.get("stale")}
         | {k: v for k, v in snapshots.items() if k in failed})
    print(f"Scored {len(stocks) - len([s for s in stocks if s.get('stale')])} stock(s), "
          f"{len(unscored)} without enough data, {len(failed)} failed, graded {n} call result(s).")
    return out


if __name__ == "__main__":
    out = run()
    if not out["stocks"] and not out.get("unscored"):
        sys.exit("No stocks could be scored. Yahoo may be blocking or down; try again later.")
