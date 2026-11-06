"""
Scores each stock on four lenses (0-10), then rates it.

Trend     Price momentum and strength against the TSX: position vs the 50- and
          200-day averages, 12-month return vs the benchmark, 52-week range.
GARP      Growth at a reasonable price: PEG, forward P/E and expected EPS growth.
Quality   ROE, profit margin, debt, free cash flow and earnings consistency.
          Banks and insurers skip debt and free cash flow (see config).
Dividend  Dividend growth, payout ratio and years of increases. "n/a" for
          non-payers, whose weight moves to the other three lenses.

Each lens adds up points from the measures it can find, then scales to 10, so a
missing number doesn't count as a zero. A lens needs at least two measures; a
stock is only rated when Trend, GARP and Quality all have enough data.

The composite is then reduced by up to MAX_RISK_PENALTY for medium-risk flags:
high volatility, stretched valuation, no earnings, heavy debt, very small size.
"""

from . import config


class NotEnoughData(ValueError):
    """Yahoo didn't return enough numbers to fill Trend, GARP and Quality."""


# ---------- Helpers ----------
def lin(x, x0, x1, y0, y1):
    """Linear map of x from [x0, x1] to [y0, y1], clamped. Works for falling scales too."""
    if x1 == x0:
        return y1
    t = (x - x0) / (x1 - x0)
    t = max(0.0, min(1.0, t))
    return y0 + t * (y1 - y0)


def pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def signed(x, d=1):
    return f"{'+' if x >= 0 else '−'}{abs(x) * 100:.{d}f}%"


def money(x):
    return f"${x:,.2f}"


def finish(parts, min_parts):
    """parts: list of (points, max_points, note). Scales the points found to 0-10."""
    if len(parts) < min_parts:
        return None, [p[2] for p in parts]
    got = sum(p[0] for p in parts)
    possible = sum(p[1] for p in parts)
    return round(10 * got / possible, 1), [p[2] for p in parts]


def is_financial(m):
    return m.get("sector") in config.FINANCIAL_SECTORS


def is_utility(m):
    return m.get("sector") in config.UTILITY_SECTORS


def eps_cagr(history):
    """Annual EPS growth across the reported years, when every year was profitable."""
    if len(history) < 3 or any(v <= 0 for v in history):
        return None
    years = len(history) - 1
    return (history[-1] / history[0]) ** (1 / years) - 1


# ---------- Lenses ----------
def trend_lens(m, bench):
    parts = []
    p, ma50, ma200 = m.get("price"), m.get("ma50"), m.get("ma200")
    if p and ma200:
        d = p / ma200 - 1
        parts.append((lin(d, -0.10, 0.05, 0, 2.5), 2.5,
                      f"{signed(d)} vs. the 200-day average ({money(ma200)})"))
    if p and ma50:
        d = p / ma50 - 1
        parts.append((lin(d, -0.05, 0.03, 0, 2.0), 2.0,
                      f"{signed(d)} vs. the 50-day average ({money(ma50)})"))
    if ma50 and ma200:
        up = ma50 > ma200
        parts.append((1.5 if up else 0.0, 1.5,
                      "50-day average above the 200-day" if up else "50-day average below the 200-day"))
    r, b = m.get("return_12m"), (bench or {}).get("return_12m")
    if r is not None and b is not None:
        rs = r - b
        parts.append((lin(rs, -0.25, 0.30, 0, 3.0), 3.0,
                      f"12-month return {signed(r)} vs. {signed(b)} for the {config.BENCHMARK_NAME}"))
    lo, hi = m.get("low52"), m.get("high52")
    if p and lo and hi and hi > lo:
        pos = (p - lo) / (hi - lo)
        parts.append((lin(pos, 0, 1, 0, 1.0), 1.0,
                      f"{pct(pos, 0)} of the way up its 52-week range ({money(lo)}–{money(hi)})"))
    return finish(parts, 2)


def garp_lens(m):
    teps, feps = m.get("trailing_eps"), m.get("forward_eps")
    if (teps is None or teps <= 0) and (feps is None or feps <= 0):
        return 1.0, ["No earnings yet, so growth-at-a-reasonable-price can't be measured; scored 1"]
    parts = []
    peg = m.get("peg")
    if peg is not None and peg > 0:
        parts.append((lin(peg, 3.0, 0.8, 0, 4.0), 4.0, f"PEG {peg:.2f}"))
    fpe, tpe = m.get("forward_pe"), m.get("trailing_pe")
    if fpe is not None and fpe > 0:
        parts.append((lin(fpe, 30, 10, 0, 3.0), 3.0, f"Forward P/E {fpe:.1f}"))
    elif tpe is not None and tpe > 0:
        parts.append((lin(tpe, 35, 12, 0, 3.0), 3.0, f"Trailing P/E {tpe:.1f} (no forward estimate)"))
    g, label = m.get("eps_growth_next"), "expected EPS growth next year"
    if g is None:
        g, label = eps_cagr(m.get("eps_history") or []), "EPS growth per year, last reported years"
    if g is None:
        g, label = m.get("earnings_growth_q"), "EPS growth, latest quarter vs. a year ago"
    if g is not None:
        parts.append((lin(g, 0, 0.20, 0, 3.0), 3.0, f"{signed(g)} {label}"))
    return finish(parts, 2)


def quality_lens(m):
    parts = []
    roe = m.get("roe")
    if roe is not None:
        parts.append((lin(roe, 0.05, 0.25, 0, 3.0), 3.0, f"Return on equity {pct(roe)}"))
    pm = m.get("profit_margin")
    if pm is not None:
        parts.append((lin(pm, 0, 0.35, 0, 2.0), 2.0, f"Profit margin {pct(pm)}"))
    if not is_financial(m):
        de, util = m.get("debt_to_equity"), is_utility(m)
        if de is not None:
            hi, lo = (300, 100) if util else (200, 50)
            parts.append((lin(de, hi, lo, 0, 2.0), 2.0,
                          f"Debt-to-equity {de / 100:.2f}" + (" (utility scale)" if util else "")))
        fy = m.get("fcf_yield")
        if fy is not None and not util:
            parts.append((lin(fy, -0.02, 0.04, 0, 2.0), 2.0, f"Free cash flow yield {signed(fy)}"))
    eh = m.get("eps_history") or []
    if len(eh) >= 3:
        if any(v <= 0 for v in eh):
            parts.append((0.0, 1.0, f"A loss in at least one of the last {len(eh)} years"))
        else:
            rises = sum(1 for a, b in zip(eh, eh[1:]) if b > a)
            parts.append((rises / (len(eh) - 1), 1.0,
                          f"EPS rose in {rises} of the last {len(eh) - 1} years"))
    return finish(parts, 2)


def dividend_lens(m):
    rate = m.get("dividend_rate")
    if not rate:
        return None, ["Pays no dividend"]
    parts = []
    g, label = m.get("dividend_cagr_5y"), "dividend growth per year over 5 years"
    if g is None:
        g, label = m.get("dividend_growth_1y"), "dividend growth over the last year"
    if g is not None:
        parts.append((lin(g, 0, 0.15, 0, 4.0), 4.0, f"{signed(g)} {label}"))
    po = m.get("payout_ratio")
    if po is not None and po > 0:
        parts.append((lin(po, 0.90, 0.50, 0, 3.0), 3.0, f"Payout ratio {pct(po, 0)} of earnings"))
    yrs = m.get("dividend_years_raised") or 0
    parts.append((lin(yrs, 0, 25, 0, 3.0), 3.0,
                  f"{yrs} straight calendar year{'s' if yrs != 1 else ''} of increases"))
    score, notes = finish(parts, 2)
    if m.get("dividend_yield"):
        notes.insert(0, f"Yield {pct(m['dividend_yield'], 2)}")
    return score, notes


def risk_flags(m):
    flags = []
    beta, vol = m.get("beta"), m.get("volatility")
    if beta is not None and beta > 1.5:
        flags.append((0.5, f"High beta ({beta:.2f}): moves much more than the market"))
    elif beta is not None and beta > 1.2:
        flags.append((0.25, f"Above-market beta ({beta:.2f})"))
    if vol is not None and vol > 0.45:
        flags.append((0.5, f"Very volatile ({pct(vol, 0)} a year)"))
    elif vol is not None and vol > 0.35:
        flags.append((0.25, f"Volatile ({pct(vol, 0)} a year)"))
    teps = m.get("trailing_eps")
    if teps is not None and teps <= 0:
        flags.append((0.5, "Not profitable over the last 12 months"))
    else:
        fpe, tpe = m.get("forward_pe"), m.get("trailing_pe")
        if (fpe and fpe > 30) or (tpe and tpe > 40):
            flags.append((0.5, f"Stretched valuation (forward P/E {fpe:.1f})" if fpe
                          else f"Stretched valuation (P/E {tpe:.1f})"))
    de = m.get("debt_to_equity")
    if not is_financial(m) and de is not None and de > (300 if is_utility(m) else 200):
        flags.append((0.5, f"Heavy debt (debt-to-equity {de / 100:.2f})"))
    cap = m.get("market_cap")
    if cap is not None and cap < 5e8:
        flags.append((0.25, f"Small company (market value about ${cap / 1e6:,.0f}M)"))
    penalty = min(config.MAX_RISK_PENALTY, sum(f[0] for f in flags))
    return round(penalty, 2), [f[1] for f in flags]


# ---------- Rating ----------
def weights_for(has_dividend):
    w = dict(config.WEIGHTS)
    if not has_dividend:
        k = 1 / (1 - w["dividend"])
        w = {"trend": w["trend"] * k, "garp": w["garp"] * k, "quality": w["quality"] * k, "dividend": 0.0}
    return w


def thresholds(held):
    return [config.HELD_HOLD, config.HELD_BUY_MORE] if held else [config.WATCH_BUY]


def rate(score, held):
    if held:
        if score >= config.HELD_BUY_MORE:
            return "Buy more"
        return "Hold" if score >= config.HELD_HOLD else "Sell"
    return "Buy" if score >= config.WATCH_BUY else "Don't buy"


def triggers(m, lenses, adjusted, held):
    """Two or three observable things that would move the rating."""
    out = []
    ups = [t for t in thresholds(held) if t > adjusted]
    downs = [t for t in thresholds(held) if t <= adjusted]
    if ups:
        nxt = min(ups)
        out.append(f"Needs {nxt - adjusted:.2f} more points to reach {rate(nxt, held)}.")
    if downs:
        floor = max(downs)
        out.append(f"Drops to {rate(floor - 0.01, held)} if it loses {adjusted - floor + 0.01:.2f} points.")

    p, ma200, fpe, po = m.get("price"), m.get("ma200"), m.get("forward_pe"), m.get("payout_ratio")
    if p and ma200:
        out.append(f"A move {'above' if p < ma200 else 'below'} the 200-day average ({money(ma200)}) "
                   f"would {'lift' if p < ma200 else 'cut'} Trend.")
    if fpe and fpe > 20:
        out.append(f"Forward P/E falling below 20 (now {fpe:.1f}) would lift GARP.")
    if po and po > 0.8 and lenses["dividend"] is not None:
        out.append(f"Payout ratio back under 80% (now {pct(po, 0)}) would lift the dividend score.")
    if m.get("next_earnings"):
        out.append(f"Next earnings report: {m['next_earnings'][:10]}.")
    return out[:4]


def score_stock(m, bench, held, previous_adjusted=None):
    t, t_notes = trend_lens(m, bench)
    g, g_notes = garp_lens(m)
    q, q_notes = quality_lens(m)
    d, d_notes = dividend_lens(m)
    lenses = {"trend": t, "garp": g, "quality": q, "dividend": d}

    missing = [k for k in ("trend", "garp", "quality") if lenses[k] is None]
    if missing:
        names = {"trend": "Trend", "garp": "GARP", "quality": "Quality"}
        raise NotEnoughData(", ".join(names[k] for k in missing))
    w = weights_for(d is not None)
    used = {k: w[k] for k, v in lenses.items() if v is not None and w[k] > 0}
    total_w = sum(used.values())
    composite = sum(lenses[k] * used[k] for k in used) / total_w

    penalty, risk_reasons = risk_flags(m)
    adjusted = round(composite - penalty, 2)
    rating = rate(adjusted, held)
    border = any(abs(adjusted - th) <= config.BORDERLINE for th in thresholds(held))

    change = round(adjusted - previous_adjusted, 2) if previous_adjusted is not None else None
    reasons = []
    if change is not None and abs(change) >= 0.25:
        reasons.append({"type": "move" if change > 0 else "caution",
                        "text": f"Score {'up' if change > 0 else 'down'} {abs(change):.2f} since the last update"})
    reasons += [{"type": "caution", "text": r} for r in risk_reasons]

    return {
        "symbol": m["symbol"],
        "name": m["name"],
        "held": held,
        "sector": m.get("sector"),
        "currency": m.get("currency"),
        "financial_currency": m.get("financial_currency"),
        "price": m.get("price"),
        "day_change": m.get("day_change"),
        "lenses": lenses,
        "notes": {"trend": t_notes, "garp": g_notes, "quality": q_notes, "dividend": d_notes},
        "weights": {k: round(v / total_w, 4) for k, v in used.items()},
        "composite": round(composite, 2),
        "risk_penalty": penalty,
        "adjusted": adjusted,
        "rating": rating,
        "borderline": border,
        "score_change": change,
        "reasons": reasons,
        "triggers": triggers(m, lenses, adjusted, held),
        "metrics": {k: m.get(k) for k in (
            "ma50", "ma200", "low52", "high52", "return_12m", "volatility", "beta", "market_cap",
            "forward_pe", "trailing_pe", "peg", "eps_growth_next", "roe", "profit_margin",
            "debt_to_equity", "fcf_yield", "dividend_yield", "payout_ratio", "dividend_cagr_5y",
            "dividend_years_raised", "target_price", "analyst_rating", "analyst_count")},
        "next_earnings": m.get("next_earnings"),
        "news": m.get("news") or [],
        "chart": m.get("chart") or [],
    }
