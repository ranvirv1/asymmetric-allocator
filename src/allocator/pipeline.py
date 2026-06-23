"""Live pipeline — M1 -> M2 -> M4 -> M5 -> M6 -> M7 for a single date (spec §2 'Live mode').

Produces the ranked, risk-budgeted allocation R reviews and places manually. Emits a dict the
M9 reporter renders into the house-style dashboard.
"""
from __future__ import annotations

import pandas as pd

from . import classifier, exits, regime, scoring, sizer, universe
from .config import load_config


def run_live(as_of: str | pd.Timestamp, cfg: dict | None = None,
             active: tuple[str, ...] = ("ERM", "RS")) -> dict:
    cfg = cfg or load_config()
    as_of = pd.Timestamp(as_of)

    uni = universe.build_universe(as_of, cfg, with_mktcap=False)
    tickers = uni.members["ticker"].tolist()
    reg = regime.compute_regime(as_of, cfg, breadth_tickers=tickers)
    scored = scoring.score_universe(as_of, tickers, reg.verdict, cfg, active=active)
    buckets = classifier.classify(scored, uni.members, cfg)
    alloc = sizer.size_allocation(buckets, reg, as_of, cfg)
    alloc_rows = exits.attach_exits(alloc, cfg)

    return {
        "as_of": as_of,
        "universe": uni,
        "regime": reg,
        "scored": scored,
        "buckets": buckets,
        "allocation": alloc,
        "allocation_rows": alloc_rows,
        "cfg": cfg,
    }
