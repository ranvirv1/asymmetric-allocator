"""Prospero-style market signals from free data (yfinance): Net Options Sentiment + analyst
Upside/Downside. Transparent analogues — we show the formula rather than a black box.

  net_options_sentiment(ticker) -> 0-100. Call-share of open interest + volume across near-term
      expiries (count-based, averaging standing positions and today's flow). 80+ = call-heavy
      (bets up), 20- = put-heavy (bets down), 50 = divided. Mirrors Prospero's described NOS.
      (Count-based, not premium-$-weighted: $-weighting overweights deep-ITM calls' intrinsic
      value, which isn't a fresh directional bet — it skews high-priced names bullish.)
  target_signals(ticker, price) -> implied upside/downside from analyst price targets.

Honest limits vs Prospero: free options data is delayed and reflects ALL participants (we can't
isolate 'institutional'); analyst targets are consensus, not ML. Decision-support, not a crystal ball.
"""
from __future__ import annotations

import time
import warnings
from typing import Any

import pandas as pd

from . import cache

warnings.filterwarnings("ignore", module="yfinance")

_NOS_TTL = 1800   # 30 min
_TGT_TTL = 6 * 3600
_last = 0.0


def _throttle(gap: float = 0.2) -> None:
    global _last
    d = time.time() - _last
    if d < gap:
        time.sleep(gap - d)
    _last = time.time()


def _yf(ticker: str):
    import logging

    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return yf.Ticker(ticker)


def net_options_sentiment(ticker: str, max_days: int = 45, use_cache: bool = True) -> dict[str, Any]:
    """0-100 net options sentiment ($-weighted call vs put open interest) over near-term expiries."""
    ident = f"{ticker}|nos|{max_days}"
    if use_cache:
        c = cache.get_json("options", ident, max_age_sec=_NOS_TTL)
        if c is not None:
            return c
    out: dict[str, Any] = {"nos": None}
    try:
        t = _yf(ticker)
        _throttle()
        exps = list(t.options or [])
        if not exps:
            return out
        today = pd.Timestamp.now().normalize()
        call_oi = put_oi = call_vol = put_vol = 0.0
        used = 0
        for e in exps:
            if (pd.Timestamp(e) - today).days > max_days or used >= 5:
                break
            _throttle()
            oc = t.option_chain(e)
            for df, is_call in ((oc.calls, True), (oc.puts, False)):
                if df is None or df.empty:
                    continue
                oi = float(df["openInterest"].fillna(0).sum())
                vol = float(df["volume"].fillna(0).sum())
                if is_call:
                    call_oi += oi; call_vol += vol
                else:
                    put_oi += oi; put_vol += vol
            used += 1
        oi_tot, vol_tot = call_oi + put_oi, call_vol + put_vol
        if oi_tot > 0:
            oi_share = call_oi / oi_tot
            vol_share = (call_vol / vol_tot) if vol_tot > 0 else oi_share
            out = {
                "nos": round(100.0 * 0.5 * (oi_share + vol_share), 1),
                "pc_oi": round(put_oi / max(call_oi, 1), 2),
                "pc_vol": round(put_vol / max(call_vol, 1), 2),
                "expiries_used": used,
            }
    except Exception:
        out = {"nos": None}
    if use_cache and out.get("nos") is not None:
        cache.put_json("options", ident, out)
    return out


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _downside_momentum(ticker: str, price: float | None) -> float | None:
    """0-100: weak/negative price momentum. ~0 near the 52-wk high, rises as it falls below."""
    from . import prices
    try:
        df = prices.history(ticker)
        if df.empty or not price:
            return None
        high52 = float(df["close"].tail(252).max())
        below = (high52 - price) / high52 if high52 > 0 else 0.0
        return round(_clamp(below * 200, 0, 100), 0)  # at high -> 0; 50% below -> 100
    except Exception:
        return None


def breakout_scores(ticker: str, price: float | None, rs_score: float | None = None) -> dict[str, Any]:
    """Prospero-style Upside/Downside Breakout, 0-100 each, INDEPENDENT. Each averages the
    components it can compute:
      Upside   = call-options demand (NOS) + analyst mean-target upside + price momentum (RS).
      Downside = put-options demand (100-NOS) + analyst low-target downside + weak momentum.
    80+ = strong signal, 20- = weak. A name can be high (or low) on both (wide-spread / volatile)."""
    nos = net_options_sentiment(ticker).get("nos")
    tg = target_signals(ticker, price)
    up_imp, dn_imp = tg.get("upside_pct"), tg.get("downside_pct")
    up: list[float] = []
    dn: list[float] = []
    if nos is not None:
        up.append(nos)
        dn.append(100 - nos)
    if up_imp is not None:
        up.append(_clamp(50 + up_imp * 100, 0, 100))     # +50% target upside -> 100, 0% -> 50
    if dn_imp is not None:
        dn.append(_clamp(-dn_imp * 200, 0, 100))          # -50% low-target -> 100 (tail risk)
    if rs_score is not None and rs_score == rs_score:
        up.append(float(rs_score))                        # RS momentum percentile
    md = _downside_momentum(ticker, price)
    if md is not None:
        dn.append(md)
    return {
        "upside": round(sum(up) / len(up)) if up else None,
        "downside": round(sum(dn) / len(dn)) if dn else None,
        "nos": nos,
    }


def short_pressure(ticker: str, price: float | None = None, use_cache: bool = True) -> dict[str, Any]:
    """0-100 short-pressure INTENSITY (direction-agnostic). High = lots of short interest and/or
    a squeeze brewing (heavy shorts + RISING price). Not inherently bearish: high + rising = bullish
    squeeze fuel; high + falling = shorts winning. Short interest is reported bi-monthly (lagged)."""
    ident = f"{ticker}|short"
    if use_cache:
        c = cache.get_json("options", ident, max_age_sec=_TGT_TTL)
        if c is not None:
            return c
    out: dict[str, Any] = {}
    try:
        t = _yf(ticker)
        _throttle()
        info = t.info or {}
        spf = info.get("shortPercentOfFloat")
        dtc = info.get("shortRatio")
        if spf is None and dtc is None:
            return out
        spf, dtc = float(spf or 0), float(dtc or 0)
        intensity = 0.6 * _clamp(spf / 0.15, 0, 1) + 0.4 * _clamp(dtc / 8.0, 0, 1)
        from . import prices
        mom = 0.0
        df = prices.history(ticker)
        if not df.empty:
            r = prices.trailing_return(df["close"], 1).iloc[-1]
            mom = float(r) if r == r else 0.0
        amp = 1.0 + 0.5 * _clamp(mom / 0.20, 0, 1)         # rising price amplifies (squeeze)
        out = {
            "short_pressure": round(_clamp(intensity * 100 * amp, 0, 100)),
            "short_pct_float": round(spf * 100, 1), "days_to_cover": round(dtc, 1),
            "squeeze": mom > 0.03 and spf > 0.05,           # heavy shorts + rising = squeeze setup
        }
    except Exception:
        out = {}
    if use_cache and out.get("short_pressure") is not None:
        cache.put_json("options", ident, out)
    return out


def stock_signals(ticker: str, price: float | None, rs_score: float | None = None) -> dict[str, Any]:
    """All Prospero-style ratings for one name in a single dict (0-100 each where available).
    dark_pool is None — free real-time dark-pool % isn't available (needs a paid / lagged feed)."""
    b = breakout_scores(ticker, price, rs_score)
    sp = short_pressure(ticker, price)
    return {
        "nos": b.get("nos"),
        "upside": b.get("upside"),
        "downside": b.get("downside"),
        "short_pressure": sp.get("short_pressure"),
        "squeeze": sp.get("squeeze", False),
        "short_pct_float": sp.get("short_pct_float"),
        "dark_pool": None,
    }


def target_signals(ticker: str, price: float | None = None, use_cache: bool = True) -> dict[str, Any]:
    """Implied upside/downside from analyst price targets (mean = upside, low = downside floor)."""
    ident = f"{ticker}|targets"
    if use_cache:
        c = cache.get_json("options", ident, max_age_sec=_TGT_TTL)
        if c is not None:
            return c
    out: dict[str, Any] = {}
    try:
        t = _yf(ticker)
        _throttle()
        pt = t.analyst_price_targets or {}
        cur = float(pt.get("current") or price or 0) or None
        mean, low, high = pt.get("mean"), pt.get("low"), pt.get("high")
        out = {
            "current": cur, "target_mean": mean, "target_low": low, "target_high": high,
            "upside_pct": (float(mean) / cur - 1.0) if (mean and cur) else None,
            "downside_pct": (float(low) / cur - 1.0) if (low and cur) else None,
        }
    except Exception:
        out = {}
    if use_cache and out.get("upside_pct") is not None:
        cache.put_json("options", ident, out)
    return out
