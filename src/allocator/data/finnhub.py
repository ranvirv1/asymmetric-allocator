"""Finnhub wrapper — fundamentals backup (FI) and catalysts/earnings dates (CAT).

Used where FMP statement endpoints are gated (spec §4). Free tier.
"""
from __future__ import annotations

from typing import Any

import requests

from ..config import load_keys
from . import cache

_BASE = "https://finnhub.io/api/v1"
_SESSION = requests.Session()
_TTL = 12 * 3600


def _get(path: str, params: dict[str, Any], ns: str, ttl: float = _TTL) -> Any:
    key = load_keys().require("finnhub")
    ident = f"{path}|{sorted(params.items())}"
    cached = cache.get_json(ns, ident, max_age_sec=ttl)
    if cached is not None:
        return cached
    params = {**params, "token": key}
    r = _SESSION.get(f"{_BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    cache.put_json(ns, ident, data)
    return data


def basic_financials(symbol: str) -> dict[str, Any]:
    """Margins, growth, valuation metrics — FI sub-score backup."""
    return _get("/stock/metric", {"symbol": symbol, "metric": "all"}, "fh_metric")


def earnings_calendar(symbol: str, frm: str, to: str) -> list[dict[str, Any]]:
    """Upcoming/known earnings dates — the dated-catalyst input for CAT + slippage flags."""
    data = _get(
        "/calendar/earnings", {"symbol": symbol, "from": frm, "to": to}, "fh_earn"
    )
    if isinstance(data, dict):
        return data.get("earningsCalendar", [])
    return []


def company_profile(symbol: str) -> dict[str, Any]:
    """profile2 — sector/industry/mktcap backup when FMP profile is unavailable."""
    return _get("/stock/profile2", {"symbol": symbol}, "fh_profile")
