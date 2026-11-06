"""
One update run: pull each stock from Yahoo Finance, score and rate it, log
rating changes, grade older calls, and write the JSON files the dashboard reads.

    python -m pipeline.update

GitHub Actions runs this on a schedule (see .github/workflows/).
"""

import json
import math
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

from . import config
from .analyze import NotEnoughData, is_reit, pe_of, score_stock
from .grade import grade_calls, log_calls

SCORES_FILE = config.DATA_DIR / "scores.json"
HISTORY_FILE = config.DATA_DIR / "history.json"
SNAPSHOT_FILE = config.DATA_DIR / "snapshots.json"
FUNDAMENTALS_FILE = config.DATA_DIR / "fundamentals.json"
SCORE_HISTORY_FILE = config.DATA_DIR / "score_history.json"


def load(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, data, indent=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=indent, separators=None if indent else (",", ":")))
    tmp.replace(path)


def with_retry(fn, *args, **kwargs):
    """Yahoo sometimes rate-limits a burst of requests; wait and try once more."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        if "rate" not in str(e).lower() and "too many" not in str(e).lower():
            raise
        print(f"Rate-limited by Yahoo; waiting {config.RETRY_WAIT_SECONDS}s and retrying.", file=sys.stderr)
        time.sleep(config.RETRY_WAIT_SECONDS)
        return fn(*args, **kwargs)


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
        "symbol", "name", "currency", "price", "day_change", "week_change", "return_12m",
        "ma50", "ma200", "low52", "high52", "dividend_yield", "chart", "ex_dividend_date",
        "expense_ratio", "look_through")}


# ---------- Fundamentals cache ----------
def due_for_refresh(symbols, cache, held, now):
    """Which symbols get fresh fundamentals this run: anything missing or too old,
    holdings (if set), plus the oldest slice so the whole list rotates."""
    def age(sym):
        f = cache.get(sym, {}).get("fetched")
        if not f:
            return math.inf
        return (now - datetime.fromisoformat(f)).total_seconds() / 86400

    max_age = getattr(config, "FUNDAMENTALS_MAX_AGE_DAYS", 8)
    due = {s for s in symbols if age(s) >= max_age}
    if getattr(config, "FUNDAMENTALS_DAILY_FOR_HOLDINGS", True):
        due |= {s for s in symbols if s in held and age(s) >= 0.5}
    slice_n = math.ceil(len(symbols) / max(1, getattr(config, "FUNDAMENTALS_SPREAD", 5)))
    oldest = sorted((s for s in symbols if s not in due), key=age, reverse=True)
    due |= {s for s in oldest[:max(0, slice_n - len(due))] if age(s) >= 1}
    return due


def fetch_with_cache(fetch_stock, sym, cache, refresh, now, etf=False):
    """Fetch prices, plus fundamentals when due. If the fundamentals request
    fails but there's a cached copy, use the cache instead of failing the stock."""
    cached = cache.get(sym, {}).get("data")
    try:
        m = with_retry(fetch_stock, sym, None if (refresh or not cached) else cached, etf)
    except Exception:
        if not (refresh and cached):
            raise
        m = with_retry(fetch_stock, sym, cached, etf)
        m["_cache_fallback"] = True
    fresh = m.pop("_fundamentals", None)
    if fresh is not None:
        cache[sym] = {"fetched": now.isoformat(), "data": fresh}
    return m


# ---------- Recommendations ----------
def heavy_sectors(held_stocks, etfs):
    """Sectors you already have a lot of: 2+ held stocks, or 35%+ of an ETF you hold."""
    counts = {}
    for s in held_stocks:
        if s.get("sector"):
            counts[s["sector"]] = counts.get(s["sector"], 0) + 1
    heavy = {sec for sec, n in counts.items() if n >= 2}
    limit = getattr(config, "HEAVY_ETF_WEIGHT", 0.35)
    for e in etfs:
        for sec, w in ((e.get("look_through") or {}).get("sectors") or {}).items():
            if w >= limit:
                heavy.add(sec)
    return heavy | set(getattr(config, "HEAVY_SECTORS", []))


def pick_recommendations(candidates: list[dict], skip_sectors=frozenset()) -> list[dict]:
    """The best Buy-rated stocks you don't own: a cap per sector for variety,
    no sectors you're already heavy in, and nothing too risky."""
    count = getattr(config, "RECOMMEND_COUNT", 6)
    per_sector = getattr(config, "RECOMMEND_PER_SECTOR", 2)
    max_risk = getattr(config, "RECOMMEND_MAX_RISK", None)
    picks, by_sector = [], {}
    for s in sorted(candidates, key=lambda x: x["adjusted"], reverse=True):
        if s.get("stale") or s["held"] or s["rating"] != "Buy":
            continue
        if max_risk is not None and s.get("risk_penalty", 0) > max_risk:
            continue
        sector = s.get("sector") or "Other"
        if sector in skip_sectors or by_sector.get(sector, 0) >= per_sector:
            continue
        by_sector[sector] = by_sector.get(sector, 0) + 1
        picks.append(s)
        if len(picks) >= count:
            break
    return picks


# ---------- Page extras ----------
def sector_peers(records):
    """{sector: [P/E, ...]} across everything fetched this run, REITs excluded."""
    peers = {}
    for m in records:
        pe = pe_of(m)
        if pe is not None and m.get("sector") and not is_reit(m):
            peers.setdefault(m["sector"], []).append(pe)
    return peers


def market_strip(bench, us_bench, fx, scored):
    """Indexes, the dollar, and how each sector's stocks moved today (median)."""
    by_sector = {}
    for s in scored:
        if s.get("sector") and s.get("day_change") is not None and not s.get("stale"):
            by_sector.setdefault(s["sector"], []).append(s["day_change"])
    sectors = [{"name": k, "day_change": round(statistics.median(v), 5), "count": len(v)}
               for k, v in by_sector.items() if len(v) >= 2]
    sectors.sort(key=lambda x: -x["day_change"])
    pick = lambda b: ({k: b.get(k) for k in ("symbol", "name", "price", "day_change", "return_12m")} if b else None)
    return {"tsx": pick(bench), "sp500": pick(us_bench),
            "usdcad": ({"price": fx.get("price"), "day_change": fx.get("day_change")} if fx else None),
            "sectors": sectors}


def what_changed(stocks, recommended, old, previous):
    """Rating changes, new and dropped recommendations, and big score moves
    since the last update, for the summary at the top of the page."""
    if not old:
        return None
    ratings, moves = [], []
    for s in stocks:
        if s.get("stale"):
            continue
        prev = previous(s["symbol"]) or {}
        if prev.get("rating") and prev["rating"] != s["rating"]:
            ratings.append({"symbol": s["symbol"], "from": prev["rating"], "to": s["rating"], "held": s["held"]})
        if s.get("score_change") is not None and abs(s["score_change"]) >= 0.5:
            moves.append({"symbol": s["symbol"], "change": s["score_change"], "held": s["held"]})
    old_recs = {r["symbol"] for r in old.get("recommended", [])}
    new_recs = {r["symbol"] for r in recommended}
    moves.sort(key=lambda x: -abs(x["change"]))
    return {"since": old.get("generated_at"), "ratings": ratings,
            "new_recs": [s for s in new_recs - old_recs], "dropped_recs": sorted(old_recs - new_recs),
            "big_moves": moves[:8]}


def update_score_history(hist, scored, today):
    keep = getattr(config, "SCORE_HISTORY_POINTS", 260)
    for s in scored:
        if s.get("stale"):
            continue
        pts = [p for p in hist.get(s["symbol"], []) if p[0] != today]
        pts.append([today, s["adjusted"]])
        hist[s["symbol"]] = pts[-keep:]
    return hist


# ---------- The run ----------
def run(fetch_stock=None, fetch_benchmark=None, now: datetime | None = None, pause: float | None = None,
        fetch_adjusted=None, fetch_prices=None) -> dict:
    """fetch_stock(symbol, fundamentals_or_None, is_etf) -> record. The other
    fetchers are injectable too, for testing without Yahoo."""
    if None in (fetch_stock, fetch_benchmark, fetch_adjusted, fetch_prices):
        from . import yahoo_client as yc
        fetch_stock = fetch_stock or (lambda s, f, etf: yc.fetch_stock(
            s, config.NEWS_PER_STOCK, config.NEWS_DAYS, fundamentals=f, etf=etf))
        fetch_benchmark = fetch_benchmark or yc.fetch_benchmark
        fetch_adjusted = fetch_adjusted or yc.fetch_adjusted
        fetch_prices = fetch_prices or yc.fetch_prices
    pause = config.PAUSE_SECONDS if pause is None else pause
    now = now or datetime.now(timezone.utc)
    today = now.date().isoformat()

    old = load(SCORES_FILE, {})
    if old.get("sample"):
        old = {}   # first real run: drop the sample data
    history = load(HISTORY_FILE, {"calls": []})
    if history.get("sample"):
        history = {"calls": []}
    snapshots = load(SNAPSHOT_FILE, {})
    cache = load(FUNDAMENTALS_FILE, {})
    score_hist = load(SCORE_HISTORY_FILE, {})
    old_by_symbol = {s["symbol"]: s for s in old.get("stocks", [])}
    old_by_symbol |= {r["symbol"]: r for r in old.get("recommended", []) if r["symbol"] not in old_by_symbol}

    def previous(sym):
        """Last update's score and rating; older files stored just the score."""
        prev = snapshots.get(sym)
        if prev is None or isinstance(prev, dict):
            return prev
        return {"adjusted": prev, "rating": old_by_symbol.get(sym, {}).get("rating")}

    # ----- Benchmarks -----
    notes, failed = [], []
    try:
        bench = {**with_retry(fetch_benchmark, config.BENCHMARK), "name": config.BENCHMARK_NAME}
    except Exception as e:
        print(f"Benchmark {config.BENCHMARK}: {e}", file=sys.stderr)
        bench = old.get("benchmark")
        notes.append(f"Couldn't refresh the {config.BENCHMARK_NAME}; relative strength uses the last value.")
    us_bench = None
    if getattr(config, "US_BENCHMARK", None):
        try:
            us_bench = {**with_retry(fetch_benchmark, config.US_BENCHMARK), "name": config.US_BENCHMARK_NAME}
        except Exception as e:
            print(f"Benchmark {config.US_BENCHMARK}: {e}", file=sys.stderr)
            us_bench = old.get("us_benchmark")
    fx = None
    if getattr(config, "FX_SYMBOL", None):
        try:
            fx = with_retry(fetch_benchmark, config.FX_SYMBOL)
        except Exception as e:
            print(f"Exchange rate {config.FX_SYMBOL}: {e}", file=sys.stderr)

    def bench_for(m):
        """US-dollar stocks are compared with the S&P 500, the rest with the TSX."""
        return us_bench if (m.get("currency") == "USD" and us_bench) else bench

    # ----- Pass 1: fetch everything -----
    all_syms = tickers()
    etf_syms = list(getattr(config, "ETF_HOLDINGS", []))
    held_set = set(config.HOLDINGS) | set(etf_syms)
    due = due_for_refresh([s for s, _ in all_syms] + etf_syms, cache, held_set, now)
    fetched, adjusted, cache_fallbacks = {}, {}, []
    for sym, group in all_syms:
        try:
            m = fetch_with_cache(fetch_stock, sym, cache, sym in due, now)
            fetched[sym] = (m, group)
            if m.get("adj_closes"):
                adjusted[sym] = m["adj_closes"]
            if m.get("_cache_fallback") and group != "discover":
                cache_fallbacks.append(sym)
        except Exception as e:
            print(f"{sym}: {e}", file=sys.stderr)
            if group != "discover":   # a missed discovery stock just isn't considered this run
                failed.append(sym)
        if pause:
            time.sleep(pause)

    old_etfs = {e["symbol"]: e for e in old.get("etfs", [])}
    etfs = []
    for sym in etf_syms:
        try:
            m = fetch_with_cache(fetch_stock, sym, cache, sym in due, now, etf=True)
            if m.get("adj_closes"):
                adjusted[sym] = m["adj_closes"]
            etfs.append(etf_record(m))
        except Exception as e:
            print(f"{sym}: {e}", file=sys.stderr)
            failed.append(sym)
            if sym in old_etfs:
                etfs.append({**old_etfs[sym], "stale": True})
        if pause:
            time.sleep(pause)

    # ----- Pass 2: score, with sector peers known -----
    peers = sector_peers([m for m, _ in fetched.values()])
    cdrs = getattr(config, "CDR_HOLDINGS", {})
    stocks, prices, unscored, discovered = [], {}, [], []
    for sym, group in all_syms:
        held = group == "held"
        if sym not in fetched:
            prev = old_by_symbol.get(sym)
            if prev and group != "discover":
                stocks.append({**prev, "held": held, "stale": True})
            continue
        m, _ = fetched[sym]
        try:
            rec = score_stock(m, bench_for(m), held, previous(sym),
                              peers.get(m.get("sector")) if pe_of(m) is not None else None)
        except NotEnoughData as e:
            if group == "discover":
                continue
            print(f"{sym}: not enough data for {e}", file=sys.stderr)
            unscored.append({"symbol": sym, "name": m.get("name") or sym, "held": held,
                             "price": m.get("price"), "currency": m.get("currency"),
                             "missing": str(e), "news": m.get("news") or [],
                             "next_earnings": m.get("next_earnings"),
                             "ex_dividend_date": m.get("ex_dividend_date")})
            continue
        if sym in cdrs:
            rec["cdr"] = cdrs[sym]
            try:
                cp = with_retry(fetch_prices, cdrs[sym])
                rec["cdr_price"], rec["cdr_day_change"] = cp.get("price"), cp.get("day_change")
            except Exception as e:
                print(f"{cdrs[sym]}: {e}", file=sys.stderr)
                rec["cdr_price"] = old_by_symbol.get(sym, {}).get("cdr_price")
        (discovered if group == "discover" else stocks).append(rec)
        prices[sym] = rec["price"]
    for e in etfs:
        if not e.get("stale"):
            prices[e["symbol"]] = e["price"]

    if failed:
        kept = [s["symbol"] for s in stocks if s.get("stale")] + [e["symbol"] for e in etfs if e.get("stale")]
        notes.append(f"Couldn't refresh {', '.join(failed)} from Yahoo this run."
                     + (f" Showing the last data for {', '.join(kept)}." if kept else ""))
    if cache_fallbacks:
        notes.append(f"Company data for {', '.join(cache_fallbacks)} couldn't be refreshed; "
                     "prices are current, the rest is from the last good update.")

    if not any(not s.get("stale") for s in stocks) and not unscored:
        # Nothing came back at all (Yahoo down or blocking): keep the files as they are.
        print("No stock data came back from Yahoo; leaving the existing data in place.", file=sys.stderr)
        return {"stocks": [], "failed": failed}

    stocks.sort(key=lambda s: s["adjusted"], reverse=True)
    bench_price = (bench or {}).get("price")

    # ----- Recommendations -----
    heavy = heavy_sectors([s for s in stocks if s["held"]], etfs)
    watch_syms = {s["symbol"] for s in stocks if not s["held"]}
    old_since = {r["symbol"]: r.get("recommended_since") for r in old.get("recommended", [])}
    recommended = [{**s, "source": "watchlist" if s["symbol"] in watch_syms else "new",
                    "recommended_since": old_since.get(s["symbol"]) or today}
                   for s in pick_recommendations(stocks + discovered, heavy)]

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
        "market": market_strip(bench, us_bench, fx, stocks + discovered),
        "settings": {
            "weights": config.WEIGHTS,
            "max_risk_penalty": config.MAX_RISK_PENALTY,
            "held_buy_more": config.HELD_BUY_MORE, "held_hold": config.HELD_HOLD,
            "watch_buy": config.WATCH_BUY, "borderline": config.BORDERLINE,
            "grade_after_days": config.GRADE_AFTER_DAYS,
            "recommend_count": getattr(config, "RECOMMEND_COUNT", 6),
            "recommend_per_sector": getattr(config, "RECOMMEND_PER_SECTOR", 2),
            "recommend_max_risk": getattr(config, "RECOMMEND_MAX_RISK", None),
            "discovery_count": len(getattr(config, "DISCOVERY", [])),
            "rating_buffer": getattr(config, "RATING_BUFFER", 0),
            "grade_benchmark_name": getattr(config, "GRADE_BENCHMARK_NAME", {}),
            "watchlist": list(config.WATCHLIST),
            "holdings": list(config.HOLDINGS), "etf_holdings": etf_syms,
        },
        "heavy_sectors": sorted(heavy),
        "notes": sorted(set(notes)),
        "failed": failed,
        "changes": what_changed(stocks, recommended, old, previous),
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
    save(FUNDAMENTALS_FILE, cache, indent=None)
    save(SCORE_HISTORY_FILE, update_score_history(score_hist, stocks + discovered, today), indent=None)
    print(f"Scored {len(stocks) - len([s for s in stocks if s.get('stale')])} stock(s), "
          f"{len(unscored)} without enough data, {len(failed)} failed, graded {n} call result(s). "
          f"Checked {len(discovered)} discovery stock(s); recommending {len(recommended)}. "
          f"Refreshed company data for {len(due)} of {len(all_syms) + len(etf_syms)}.")
    return out


if __name__ == "__main__":
    out = run()
    if not out["stocks"] and not out.get("unscored"):
        sys.exit("No stocks could be scored. Yahoo may be blocking or down; try again later.")
