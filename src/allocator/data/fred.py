"""FRED wrapper — macro / rates / credit spreads for the regime gate (spec §2, §4).

FRED is the gold-standard free source and is treated as point-in-time clean for the
slow-moving macro series the regime gate uses (fed funds, yields, HY spread, VIX).
"""
from __future__ import annotations

import pandas as pd
import requests

from ..config import load_keys
from . import cache

_BASE = "https://api.stlouisfed.org/fred/series/observations"
_SESSION = requests.Session()

# Series the regime gate reads (spec §2).
SERIES = {
    "fed_funds": "DFF",          # effective federal funds rate
    "ust10y": "DGS10",           # 10Y treasury yield
    "ust2y": "DGS2",             # 2Y treasury yield (for 2s10s)
    # Credit-stress proxy. Spec asked for ICE BofA HY OAS (BAMLH0A0HYM2), but FRED now
    # truncates that series to ~3yr (ICE licensing) — useless for a 2020-2026 backtest.
    # BAA10Y (Moody's Baa - 10Y Treasury) is daily, full history, and moves with HY stress.
    "credit_spread": "BAA10Y",
    "vix": "VIXCLS",             # CBOE VIX
}


_MEM: dict[str, pd.Series] = {}  # in-memory cache — one fetch per series across a backtest


def reset_memory() -> None:
    """Drop the in-memory FRED cache so a fresh run re-pulls current macro data."""
    _MEM.clear()


def fetch_series(
    series_id: str,
    start: str | None = None,
    end: str | None = None,
    use_cache: bool = True,
) -> pd.Series:
    """A single FRED series as a float Series indexed by date (NaNs dropped)."""
    ident = f"{series_id}|{start}|{end}"
    if use_cache:
        if ident in _MEM:
            return _MEM[ident]
        cached = cache.get_df("fred", ident)
        if cached is not None and not cached.empty:
            _MEM[ident] = cached.iloc[:, 0]
            return _MEM[ident]

    key = load_keys().require("fred")
    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
    }
    if start:
        params["observation_start"] = pd.Timestamp(start).strftime("%Y-%m-%d")
    if end:
        params["observation_end"] = pd.Timestamp(end).strftime("%Y-%m-%d")

    r = _SESSION.get(_BASE, params=params, timeout=30)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    if not obs:
        return pd.Series(dtype=float, name=series_id)

    df = pd.DataFrame(obs)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")  # FRED uses "." for missing
    s = df.set_index("date")["value"].dropna()
    s.name = series_id
    if use_cache:
        cache.put_df("fred", ident, s.to_frame())
        _MEM[ident] = s
    return s


def fetch_named(name: str, start: str | None = None, end: str | None = None) -> pd.Series:
    """Fetch by friendly name (keys of SERIES)."""
    return fetch_series(SERIES[name], start, end)
