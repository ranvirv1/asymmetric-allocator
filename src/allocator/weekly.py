"""Weekly run support: refresh live data, persist each run's book, and diff vs last week
so the report can lead with 'what changed' (the actionable bit).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import DATA_DIR, REPORTS_DIR
from .data import cache, estimates, fred, prices

HIST_DIR = REPORTS_DIR / "history"
SNAPSHOT_DIR = DATA_DIR / "snapshots"

# Plain-English action per regime (spec §2 tilts, said the way R can act on).
REGIME_CALL = {
    "RISK_ON": "Lean in — deploy into momentum leaders, keep the cash floor.",
    "MIXED": "Balanced barbell — half-deployed, tilt toward quality.",
    "COMPRESSION": "Defensive — cut beta, raise cash, quality + low-bar only.",
}


def refresh_live_data(tickers: list[str]) -> dict:
    """Re-pull fresh prices (incl. recent days) + current macro + analyst actions before a
    live run. Backtest history doesn't change, but 'today' does — so the weekly run refreshes."""
    prices.reset_memory()
    stats = prices.prefetch(tickers, force=True)
    for ix in ("^SPX",):                       # index refreshes via the single-fetch path
        cache.invalidate("prices", f"{ix}|full")
        prices.history(ix)
    cache.clear("fred")
    fred.reset_memory()
    cache.clear("yf_grades")                   # refresh dated analyst actions for live ERM
    estimates.reset_memory()
    return stats


def take_snapshot(tickers: list[str], as_of: pd.Timestamp) -> dict:
    """Forward-snapshot job (spec §8.8): bank this week's analyst consensus + revision counts
    into data/snapshots/estimates_<date>.csv so a TRUE point-in-time ERM series accumulates
    going forward. Best-effort per name; missing fields are blank."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for t in tickers:
        row = estimates.snapshot(t)
        if row:
            rows.append(row)
    if not rows:
        return {"saved": 0, "path": None}
    df = pd.DataFrame(rows)
    df.insert(0, "snapshot_date", str(pd.Timestamp(as_of).date()))
    path = SNAPSHOT_DIR / f"estimates_{pd.Timestamp(as_of).date()}.csv"
    df.to_csv(path, index=False)
    return {"saved": len(df), "path": str(path)}


def _positions_from_rows(rows: pd.DataFrame) -> dict:
    if rows.empty:
        return {}
    return {r.ticker: {"weight": float(r.target_weight), "gbp": float(r.gbp_amount),
                       "bucket": r.bucket} for r in rows.itertuples()}


def load_prev(before: pd.Timestamp) -> dict | None:
    if not HIST_DIR.exists():
        return None
    files = sorted(HIST_DIR.glob("alloc_*.json"))
    prior = [f for f in files if f.stem.replace("alloc_", "") < str(pd.Timestamp(before).date())]
    return json.loads(prior[-1].read_text(encoding="utf-8")) if prior else None


def save_run(result: dict) -> Path:
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    as_of = pd.Timestamp(result["as_of"])
    rec = {
        "as_of": str(as_of.date()),
        "regime": result["regime"].verdict,
        "positions": _positions_from_rows(result["allocation_rows"]),
    }
    p = HIST_DIR / f"alloc_{as_of.date()}.json"
    p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return p


def diff_vs_prev(result: dict) -> dict:
    """Buys (new), sells (dropped), and weight changes vs the most recent prior run."""
    rows = result["allocation_rows"]
    curr = _positions_from_rows(rows)
    prev = load_prev(pd.Timestamp(result["as_of"]))
    prev_pos = prev["positions"] if prev else {}

    buys = [{"ticker": t, "gbp": curr[t]["gbp"], "bucket": curr[t]["bucket"]}
            for t in curr if t not in prev_pos]
    sells = [{"ticker": t, "gbp": prev_pos[t]["gbp"]} for t in prev_pos if t not in curr]
    changes = []
    for t in curr:
        if t in prev_pos:
            dw = curr[t]["weight"] - prev_pos[t]["weight"]
            if abs(dw) >= 0.005:               # ignore <0.5pt drift
                changes.append({"ticker": t, "delta_weight": dw,
                                "action": "ADD" if dw > 0 else "TRIM"})
    return {
        "prev_date": prev["as_of"] if prev else None,
        "is_initial": prev is None,
        "buys": sorted(buys, key=lambda x: -x["gbp"]),
        "sells": sorted(sells, key=lambda x: -x["gbp"]),
        "changes": sorted(changes, key=lambda x: -abs(x["delta_weight"])),
    }
