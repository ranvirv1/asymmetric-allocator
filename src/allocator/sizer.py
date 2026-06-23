"""M6 — Position sizer (spec §3/§5/§6). Buckets -> target weights -> £ allocation.

  Anchors    : score-weighted within the anchor budget, hard cap 20%/name.
  Satellites : VOL-SCALED (weight proportional to 1/ATR%) so a 90%-vol lottery ticket isn't
               sized like a utility; cap 2-5%/name, collectively <= satellite budget; the top
               1-2 by ERM are tagged 'designed winners' (allowed the top of the range).
  Overlay    : quarter-Kelly tilt mapped from WinnerScore, but caps + budget always dominate.

Guardrails (spec §6): never >20% one name; satellites never collectively > satellite_total_max;
cash floor rises in COMPRESSION (comes from the regime budget). Output is INSTRUCTIONS for R —
not auto-orders.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import load_config
from .data import prices


@dataclass
class Allocation:
    as_of: pd.Timestamp
    rows: pd.DataFrame          # ticker, bucket, target_weight, gbp_amount, shares, price, atr_pct, designed_winner
    cash_weight: float
    book_gbp: float
    notes: list[str]


def _atr_pct(ticker: str, as_of: pd.Timestamp) -> float:
    df = prices.fetch_ohlcv(ticker, end=as_of.strftime("%Y-%m-%d"))
    if df.empty or len(df) < 20:
        return float("nan")
    v = prices.atr_pct(df).iloc[-1]
    return float(v) if pd.notna(v) else float("nan")


def _kelly_tilt(score: pd.Series, kelly_fraction: float) -> pd.Series:
    """Map WinnerScore -> implied edge in [-1, 1], apply fractional Kelly as a bounded tilt."""
    edge = (score - 50.0) / 50.0
    return (1.0 + kelly_fraction * edge).clip(lower=0.5, upper=1.5)


def _size_sleeve(df: pd.DataFrame, budget: float, per_cap: float, weights_raw: pd.Series,
                 kelly_fraction: float) -> pd.Series:
    if df.empty or budget <= 0:
        return pd.Series(dtype=float)
    w = weights_raw.reindex(df.index).fillna(0.0)
    w = w * _kelly_tilt(df["winner_score"], kelly_fraction)
    if w.sum() <= 0:
        return pd.Series(dtype=float)
    w = w / w.sum() * budget
    # iterative cap so the capped mass redistributes within the sleeve, staying <= budget
    for _ in range(6):
        over = w > per_cap
        if not over.any():
            break
        excess = (w[over] - per_cap).sum()
        w[over] = per_cap
        room = w[~over]
        if room.sum() <= 0:
            break
        w[~over] = room + excess * room / room.sum()
    return w


def size_allocation(buckets, regime_result, as_of, cfg: dict | None = None,
                    book_gbp: float | None = None) -> Allocation:
    cfg = cfg or load_config()
    as_of = pd.Timestamp(as_of)
    book_gbp = book_gbp or float(cfg.get("book_size_gbp", 10000))
    caps = cfg["caps"]
    budget = regime_result.budget
    kf = float(cfg.get("kelly_fraction", 0.25))
    fx = float(cfg.get("fx_gbp_usd", 1.27))
    use_gate = cfg.get("live", {}).get("use_regime_gate", True)
    notes: list[str] = []

    s = buckets.satellites.copy()
    a = buckets.anchors

    # Budget per sleeve. Two fixes vs the naive split:
    #  - no regime gate -> deploy the WHOLE book into anchors (max-return mode).
    #  - regime gate but NO satellites found (RS-only) -> fold the idle satellite budget into
    #    anchors instead of leaving it in cash (this was a real ~40% cash-drag bug).
    if not use_gate:
        anchor_budget, sat_budget = 1.0, 0.0
        notes.append("Regime gate OFF — fully deployed into anchors (max-return mode).")
    else:
        anchor_budget = float(budget["anchor"])
        sat_budget = min(float(budget["satellite"]), caps["satellite_total_max"])
        if s.empty:
            anchor_budget += float(budget["satellite"])
            sat_budget = 0.0
            notes.append("No satellites this period — satellite budget deployed into anchors.")

    # ANCHORS — score-weighted
    a_w = _size_sleeve(a, anchor_budget, caps["anchor_max"],
                       a["winner_score"].clip(lower=0) if not a.empty else pd.Series(dtype=float), kf)

    # SATELLITES — vol-scaled (1/ATR%)
    sat_atr = {}
    if not s.empty and sat_budget > 0:
        sat_atr = {t: _atr_pct(t, as_of) for t in s.index}
        atrp = pd.Series(sat_atr).reindex(s.index)
        inv_vol = (1.0 / atrp.replace(0, np.nan)).fillna(0.0)
        s_w = _size_sleeve(s, sat_budget, caps["satellite_max"], inv_vol, kf)
    else:
        s_w = pd.Series(dtype=float)

    # designed winners: top 1-2 satellites by ERM (fallback WinnerScore)
    designed = set()
    if not s.empty:
        rank_by = s["ERM"] if "ERM" in s and s["ERM"].notna().any() else s["winner_score"]
        designed = set(rank_by.sort_values(ascending=False).head(2).index)

    rows = []
    for bucket, w, atr_map in [("ANCHOR", a_w, {}), ("SATELLITE", s_w, sat_atr)]:
        for tkr, wt in w.items():
            if wt <= 0:
                continue
            px_df = prices.fetch_ohlcv(tkr, end=as_of.strftime("%Y-%m-%d"))
            price = float(px_df["close"].iloc[-1]) if not px_df.empty else float("nan")
            gbp = wt * book_gbp
            # IBKR supports fractional shares — essential for a small book in $300+ names.
            shares = round(gbp * fx / price, 4) if price and price > 0 else 0.0
            rows.append({
                "ticker": tkr, "bucket": bucket, "target_weight": round(float(wt), 4),
                "gbp_amount": round(gbp, 2), "shares": shares, "price_usd": round(price, 2),
                "atr_pct": round(atr_map.get(tkr, float("nan")), 4) if atr_map else np.nan,
                "designed_winner": tkr in designed,
            })

    alloc = pd.DataFrame(rows)
    invested = float(alloc["target_weight"].sum()) if not alloc.empty else 0.0
    cash_w = max(0.0, 1.0 - invested)
    notes.append(f"FX GBP->USD {fx} (config); shares approximate. Cash floor from regime = {budget['cash']:.0%}.")
    notes.append("Decision-support only — these are instructions to review and place manually (spec §7).")
    return Allocation(as_of=as_of, rows=alloc, cash_weight=cash_w, book_gbp=book_gbp, notes=notes)
