"""M7 — Risk & exit rules (spec §3). Pre-commit the exit BEFORE entry so winners don't
round-trip (the OKLO +250% -> flat lesson). These are INSTRUCTIONS for R, not auto-orders.

Per name, at allocation time:
  - Hard stop:   close below entry - stop_atr x ATR  (thesis invalidation).
  - Trim ladder: take 1/3 at +trim1, another 1/3 at +trim2, let a runner ride.
  - Trailing:    once in profit, trail at trail_atr x ATR.
  - Catalyst-slip flag: dated CAT events get a 'de-rate on slip' warning (the TTWO lesson).
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from .config import DATA_DIR, load_config
from .data import prices


@lru_cache(maxsize=1)
def _catalysts() -> dict[str, dict]:
    try:
        df = pd.read_csv(DATA_DIR / "catalysts.csv", comment="#")
    except FileNotFoundError:
        return {}
    out = {}
    for r in df.itertuples():
        out.setdefault(str(r.ticker).upper(), {"kind": r.kind, "event_date": str(r.event_date),
                                               "note": getattr(r, "note", "")})
    return out


def _atr_abs(ticker: str, as_of: pd.Timestamp, entry: float) -> float:
    df = prices.fetch_ohlcv(ticker, end=as_of.strftime("%Y-%m-%d"))
    if df.empty or len(df) < 20:
        return float("nan")
    atrp = prices.atr_pct(df).iloc[-1]
    return float(atrp) * entry if pd.notna(atrp) else float("nan")


def attach_exits(alloc, cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    ex = cfg["exits"]
    cats = _catalysts()
    rows = alloc.rows.copy()
    if rows.empty:
        return rows

    recs = []
    for r in rows.itertuples():
        entry = r.price_usd
        atr_abs = _atr_abs(r.ticker, alloc.as_of, entry) if entry and entry > 0 else float("nan")
        stop = entry - ex["stop_atr"] * atr_abs if pd.notna(atr_abs) else float("nan")
        cat = cats.get(r.ticker)
        recs.append({
            "ticker": r.ticker,
            "stop_price": round(stop, 2) if pd.notna(stop) else None,
            "stop_pct": round((stop / entry - 1) * 100, 1) if (pd.notna(stop) and entry) else None,
            "trim1_price": round(entry * (1 + ex["trim1_at"]), 2) if entry else None,
            "trim2_price": round(entry * (1 + ex["trim2_at"]), 2) if entry else None,
            "trail_rule": f"once +{int(ex['trim1_at']*100)}%, trail {ex['trail_atr']}x ATR",
            "catalyst": (f"{cat['kind']} {cat['event_date']} - DE-RATE ON SLIP" if cat else ""),
        })
    ex_df = pd.DataFrame(recs)
    return rows.merge(ex_df, on="ticker", how="left")
