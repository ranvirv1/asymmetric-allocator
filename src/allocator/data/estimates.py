"""Analyst estimates / revisions for the ERM signal (spec §3 ERM, §4, §8.8).

Source = yfinance (free, no daily cap, richest fields) — chosen over FMP's 250/day free tier.
Unofficial, so the forward-snapshot job banks the data weekly into our own store (data/
snapshots/) — once banked it's ours even if Yahoo breaks.

Two products:
  dated_grades(ticker)  — point-in-time analyst actions (from .upgrades_downgrades, dated) →
                          drives the ERM sub-score for any as-of date (backtest + live).
  snapshot(ticker)      — current consensus + revision counts (eps_trend / eps_revisions /
                          recommendations) → banked weekly to build a TRUE point-in-time
                          estimate-revision series for a clean ERM backtest a year out.
"""
from __future__ import annotations

import time
import warnings
from typing import Any

import pandas as pd

from . import cache

warnings.filterwarnings("ignore", module="yfinance")

_MEM: dict[str, Any] = {}
_FAIL = object()
_last = 0.0
_MIN_INTERVAL = 0.2


def _throttle() -> None:
    global _last
    gap = time.time() - _last
    if gap < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - gap)
    _last = time.time()


def reset_memory() -> None:
    """Drop the in-memory grade cache so a fresh weekly run re-pulls current analyst actions."""
    _MEM.clear()


def _ticker(symbol: str):
    import yfinance as yf
    import logging
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return yf.Ticker(symbol)


def dated_grades(ticker: str, use_cache: bool = True) -> list[dict[str, Any]]:
    """Dated analyst actions [{date, action, newGrade, previousGrade}], newest first.
    Point-in-time: callers filter to actions <= as_of. Cached permanently per ticker
    (history doesn't change); empty results negative-cached for the run only."""
    ident = f"{ticker}|grades"
    if use_cache:
        if ident in _MEM:
            return [] if _MEM[ident] is _FAIL else _MEM[ident]
        cached = cache.get_json("yf_grades", ident)
        if cached is not None:
            _MEM[ident] = cached
            return cached
    _throttle()
    try:
        df = _ticker(ticker).upgrades_downgrades
    except Exception:
        df = None
    if df is None or len(df) == 0:
        _MEM[ident] = _FAIL
        return []
    df = df.reset_index()
    cols = {c.lower(): c for c in df.columns}
    dcol = cols.get("gradedate") or cols.get("date") or df.columns[0]
    out = []
    for _, r in df.iterrows():
        try:
            d = pd.Timestamp(r[dcol])
        except Exception:
            continue
        out.append({
            "date": str(d.date()),
            "action": str(r.get(cols.get("action", ""), "") or "").strip().lower(),
            "newGrade": r.get(cols.get("tograde", ""), "") or "",
            "previousGrade": r.get(cols.get("fromgrade", ""), "") or "",
        })
    if use_cache and out:
        cache.put_json("yf_grades", ident, out)
        _MEM[ident] = out
    elif not out:
        _MEM[ident] = _FAIL
    return out


def _row(df, period: str, col: str):
    try:
        if df is not None and period in df.index and col in df.columns:
            v = df.loc[period, col]
            return float(v) if pd.notna(v) else None
    except Exception:
        pass
    return None


def _attr(t, name):
    try:
        return getattr(t, name)
    except Exception:
        return None


def snapshot(ticker: str) -> dict[str, Any]:
    """Current consensus + revision counts for one name — the weekly point-in-time row.
    Best-effort: each field is fetched independently, so one missing field doesn't drop the
    row. Returns {} only if the ticker yields nothing at all."""
    _throttle()
    try:
        t = _ticker(ticker)
    except Exception:
        return {}
    trend, rev, est, rec = _attr(t, "eps_trend"), _attr(t, "eps_revisions"), \
        _attr(t, "earnings_estimate"), _attr(t, "recommendations")
    if all(x is None for x in (trend, rev, est, rec)):
        return {}
    rec0 = {}
    try:
        if rec is not None and len(rec):
            r0 = rec.iloc[0]
            rec0 = {k: int(r0[k]) for k in ("strongBuy", "buy", "hold", "sell", "strongSell") if k in r0}
    except Exception:
        rec0 = {}
    return {
        "ticker": ticker,
        "eps_0y": _row(est, "0y", "avg"),
        "eps_1y": _row(est, "+1y", "avg"),
        "eps_1y_growth": _row(est, "+1y", "growth"),
        "eps_1y_now": _row(trend, "+1y", "current"),
        "eps_1y_30d": _row(trend, "+1y", "30daysAgo"),
        "eps_1y_90d": _row(trend, "+1y", "90daysAgo"),
        "up_30d": _row(rev, "+1y", "upLast30days"),
        "down_30d": _row(rev, "+1y", "downLast30days"),
        "up_7d": _row(rev, "0y", "upLast7days"),
        "down_7d": _row(rev, "0y", "downLast7Days"),
        **{f"rec_{k}": v for k, v in rec0.items()},
    }
