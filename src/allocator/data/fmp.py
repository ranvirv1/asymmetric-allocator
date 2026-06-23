"""FMP wrapper — analyst estimates, targets, grades, profiles (spec §4).

Confirmed-open endpoints: price-target-consensus, analyst grades (upgrades/downgrades),
profile. Powers the ERM signal (estimate-revision momentum) and supplies sector/industry/
market-cap for the universe.

NOTE (spec §4, §7): the free tier returns CURRENT consensus, not as-of-date. So ERM is
only point-in-time honest from the moment the forward-snapshot DB starts banking it
(milestone 8). For deep history the backtest leans on RS (price) momentum, which IS clean.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import requests

from ..config import load_keys
from . import cache

_STABLE = "https://financialmodelingprep.com/stable"
_V3 = "https://financialmodelingprep.com/api/v3"
_SESSION = requests.Session()

# Cache TTLs (seconds). Current-consensus data refreshes; profiles change slowly.
_TTL_CONSENSUS = 6 * 3600
_TTL_PROFILE = 7 * 24 * 3600


_MEM: dict[str, Any] = {}  # in-memory memo — keeps a backtest from re-reading disk per month
_FAIL = object()           # sentinel: a fetch that failed this run (429/402/etc.) — don't retry


def _get(url: str, params: dict[str, Any], ttl: float, ns: str) -> Any:
    """Cached GET. On a rate-limit/quota error (429/402) returns None and memoises the
    failure FOR THIS RUN ONLY (in-memory, not disk) — so a backtest attempts each symbol
    at most once instead of re-hitting the limit on every rebalance date, while a later run
    (after the quota resets) re-tries. Successes are cached to disk permanently.
    """
    key = load_keys().require("fmp")
    ident = f"{url}|{sorted(params.items())}"
    if ident in _MEM:
        v = _MEM[ident]
        return None if v is _FAIL else v
    cached = cache.get_json(ns, ident, max_age_sec=ttl)
    if cached is not None:
        _MEM[ident] = cached
        return cached
    params = {**params, "apikey": key}
    try:
        r = _SESSION.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException:
        _MEM[ident] = _FAIL
        return None
    cache.put_json(ns, ident, data)
    _MEM[ident] = data
    return data


def profile(symbol: str) -> dict[str, Any]:
    """Company profile: sector, industry, mktCap, beta, price. Empty dict if unknown."""
    data = _get(f"{_STABLE}/profile", {"symbol": symbol}, _TTL_PROFILE, "fmp_profile")
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}


def price_target_consensus(symbol: str) -> dict[str, Any]:
    """Consensus target (high/low/median/consensus). Input to ERM/EXP."""
    data = _get(
        f"{_STABLE}/price-target-consensus", {"symbol": symbol}, _TTL_CONSENSUS, "fmp_ptc"
    )
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else {}


def analyst_grades(symbol: str, limit: int = 100) -> list[dict[str, Any]]:
    """Recent analyst grade actions (upgrades/downgrades) — the up-vs-down count for ERM."""
    data = _get(
        f"{_STABLE}/grades", {"symbol": symbol, "limit": limit}, _TTL_CONSENSUS, "fmp_grades"
    )
    return data if isinstance(data, list) else []


def analyst_estimates(symbol: str, period: str = "annual", limit: int = 8) -> list[dict[str, Any]]:
    """Forward EPS/revenue consensus estimates — the core ERM raw input."""
    data = _get(
        f"{_STABLE}/analyst-estimates",
        {"symbol": symbol, "period": period, "limit": limit},
        _TTL_CONSENSUS,
        "fmp_estimates",
    )
    return data if isinstance(data, list) else []


def sp500_constituents() -> list[dict[str, Any]]:
    """Current S&P 500 membership — a free constituent list for universe seeding (M1)."""
    data = _get(f"{_STABLE}/sp500-constituent", {}, _TTL_PROFILE, "fmp_sp500")
    return data if isinstance(data, list) else []


def historical_prices(symbol: str) -> pd.DataFrame:
    """Full daily OHLCV history as a stooq-shaped frame (DatetimeIndex; open/high/low/
    close/volume). Robust primary price source when an FMP key is present — no bot
    challenge. Returns empty if the endpoint is gated on the current plan (caller then
    falls back to stooq/yfinance).
    """
    data = _get(
        f"{_STABLE}/historical-price-eod/full", {"symbol": symbol}, _TTL_PROFILE, "fmp_hist"
    )
    rows = data.get("historical") if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    out = df[keep].astype(float)
    out.index.name = "Date"
    return out
