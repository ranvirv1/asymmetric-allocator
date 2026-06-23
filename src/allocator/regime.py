"""M2 — Regime gate (the master switch, spec §2).

Classifies the macro regime → sets the risk budget (anchor/satellite/cash) and the tilt,
BEFORE any stock scoring matters. This is the lesson from the ARKK study: one −67% year
erases three good ones, so the regime decides how much beta you're allowed to hold.

Inputs (all free): FRED rates/spreads/VIX + S&P 500 trend + universe breadth.
Each input is z-scored against its own trailing history as of date t (point-in-time), then
combined into a Regime Score. A faithful rule layer (spec §2 triggers) maps to the verdict.

Output: RegimeResult{regime_score, verdict, budget, tilt_weights, components, notes}.
  No high-beta satellite sizing in COMPRESSION, full stop (enforced downstream in M6).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import load_config
from .data import fred, prices

VERDICTS = ("RISK_ON", "MIXED", "COMPRESSION")
FRED_START = "2014-01-01"  # fixed early start: one fetch per series, ample z-score history


@dataclass
class RegimeResult:
    as_of: pd.Timestamp
    regime_score: float
    verdict: str
    budget: dict[str, float]
    tilt_weights: dict[str, float]
    components: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _zscore_at(series: pd.Series, as_of: pd.Timestamp, lookback_days: int = 756) -> float:
    """z-score of the latest value (<= as_of) vs the trailing `lookback_days` window.
    Point-in-time: uses only history up to as_of. NaN if insufficient data."""
    s = series[series.index <= as_of].dropna()
    if len(s) < 30:
        return float("nan")
    window = s.tail(lookback_days)
    mu, sd = window.mean(), window.std()
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float((s.iloc[-1] - mu) / sd)


def _level_at(series: pd.Series, as_of: pd.Timestamp) -> float:
    s = series[series.index <= as_of].dropna()
    return float(s.iloc[-1]) if len(s) else float("nan")


def _change(series: pd.Series, as_of: pd.Timestamp, days: int) -> float:
    s = series[series.index <= as_of].dropna()
    if len(s) < days + 1:
        return float("nan")
    return float(s.iloc[-1] - s.iloc[-1 - days])


def _breadth(as_of: pd.Timestamp, tickers: list[str]) -> float:
    """% of supplied names trading above their own 200-day MA as of t."""
    above = 0
    counted = 0
    for t in tickers:
        df = prices.fetch_ohlcv(t, end=as_of.strftime("%Y-%m-%d"))
        if df.empty or len(df) < 200:
            continue
        sma200 = df["close"].rolling(200).mean().iloc[-1]
        if np.isnan(sma200):
            continue
        counted += 1
        if df["close"].iloc[-1] > sma200:
            above += 1
    return above / counted if counted else float("nan")


def compute_regime(
    as_of: str | pd.Timestamp,
    cfg: dict | None = None,
    breadth_tickers: list[str] | None = None,
) -> RegimeResult:
    cfg = cfg or load_config()
    as_of = pd.Timestamp(as_of)
    start = (as_of - pd.Timedelta(days=1500)).strftime("%Y-%m-%d")
    notes: list[str] = []

    # --- FRED inputs (need key) --- fixed start so a backtest fetches each series ONCE
    # (the z-score/trailing helpers filter to <= as_of, so extra history is harmless).
    fstart = FRED_START
    dff = fred.fetch_named("fed_funds", start=fstart)
    ust10 = fred.fetch_named("ust10y", start=fstart)
    ust2 = fred.fetch_named("ust2y", start=fstart)
    credit = fred.fetch_named("credit_spread", start=fstart)
    vix = fred.fetch_named("vix", start=fstart)

    # --- Trend (S&P 500, no key) ---
    spx = prices.fetch_ohlcv("^SPX", start=start, end=as_of.strftime("%Y-%m-%d"))
    spx_close = spx["close"] if not spx.empty else pd.Series(dtype=float)

    comp: dict[str, float] = {}

    # Trend: price vs 200dma, and 6-month return
    below_200 = False
    if not spx_close.empty and len(spx_close) >= 200:
        sma200 = spx_close.rolling(200).mean().iloc[-1]
        last = spx_close.iloc[-1]
        comp["spx_vs_200dma"] = float(last / sma200 - 1.0)
        below_200 = last < sma200
        comp["spx_6m_ret"] = float(prices.trailing_return(spx_close, 6).iloc[-1])
    else:
        notes.append("S&P 500 trend unavailable (price source returned no data).")

    # Monetary: rising rates = risk-off (sign-flipped so + = risk-on)
    comp["fed_funds_3mo_chg"] = -_change(dff, as_of, 63) if not dff.empty else float("nan")
    comp["ust10y_50d_trend"] = -_change(ust10, as_of, 50) if not ust10.empty else float("nan")
    if not ust10.empty and not ust2.empty:
        comp["curve_2s10s"] = _level_at(ust10, as_of) - _level_at(ust2, as_of)

    # Stress: credit-spread level (z) & 1-mo change; VIX vs 1-yr median
    cs_level_z = _zscore_at(credit, as_of) if not credit.empty else float("nan")
    cs_chg_1mo = _change(credit, as_of, 21) if not credit.empty else float("nan")
    comp["credit_spread_level_z"] = cs_level_z
    comp["credit_spread_1mo_chg"] = cs_chg_1mo
    if not vix.empty:
        vix_now = _level_at(vix, as_of)
        vix_med = vix[vix.index <= as_of].tail(252).median()
        comp["vix_vs_1yr_median"] = float(vix_now / vix_med - 1.0) if vix_med else float("nan")

    # Breadth: % universe above own 200dma
    breadth = _breadth(as_of, breadth_tickers) if breadth_tickers else float("nan")
    comp["breadth_above_200dma"] = breadth

    # --- Composite Regime Score: sign-oriented z-scores, + = risk-on ---
    oriented = {
        "spx_vs_200dma": comp.get("spx_vs_200dma"),
        "spx_6m_ret": comp.get("spx_6m_ret"),
        "fed_funds_3mo_chg": comp.get("fed_funds_3mo_chg"),
        "ust10y_50d_trend": comp.get("ust10y_50d_trend"),
        "curve_2s10s": comp.get("curve_2s10s"),
        "credit_spread_level_z": -cs_level_z if not np.isnan(cs_level_z) else None,
        "credit_spread_1mo_chg": -cs_chg_1mo if not np.isnan(cs_chg_1mo) else None,
        "vix_vs_1yr_median": -comp["vix_vs_1yr_median"] if not np.isnan(comp.get("vix_vs_1yr_median", float("nan"))) else None,
        "breadth_above_200dma": (breadth - 0.5) if not np.isnan(breadth) else None,
    }
    vals = [v for v in oriented.values() if v is not None and not np.isnan(v)]
    # standardise to comparable scale via tanh of each (bounded), then average
    regime_score = float(np.mean([np.tanh(v) for v in vals])) if vals else float("nan")

    # --- Rule layer (spec §2 triggers) ---
    rcfg = cfg.get("regime", {})
    breadth_riskon = rcfg.get("breadth_riskon", 0.55)
    # "Widening fast" = a SUSTAINED move: 21-day change, z-scored vs its own history, >1.5σ.
    # (The daily change is too noisy — one volatile day would false-trigger COMPRESSION.)
    cs_chg21_z = _zscore_at(credit.diff(21), as_of) if not credit.empty else float("nan")
    spreads_widening_fast = (not np.isnan(cs_chg21_z)) and cs_chg21_z > 1.5
    spreads_tight = (np.isnan(cs_level_z) or cs_level_z < 0.5) and not spreads_widening_fast
    trend_up = comp.get("spx_vs_200dma", -1) > 0 and comp.get("spx_6m_ret", -1) > 0
    breadth_ok = np.isnan(breadth) or breadth >= breadth_riskon

    if below_200 or spreads_widening_fast:
        verdict = "COMPRESSION"
        notes.append("COMPRESSION trigger: " + ("below 200dma. " if below_200 else "") +
                     ("credit spreads widening fast. " if spreads_widening_fast else ""))
    elif trend_up and spreads_tight and breadth_ok:
        verdict = "RISK_ON"
    else:
        verdict = "MIXED"

    budget = cfg["regime_budgets"][verdict]
    tilt = cfg["regime_modifiers"].get(verdict, {})

    return RegimeResult(
        as_of=as_of,
        regime_score=regime_score,
        verdict=verdict,
        budget=budget,
        tilt_weights=tilt,
        components=comp,
        notes=notes,
    )
