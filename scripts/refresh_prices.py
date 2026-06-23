"""Recover/refill the price cache (non-destructive). Clears stale 'no data' markers and
batch-fetches any missing names, keeping everything already cached.

Run:  $env:PYTHONUTF8=1; .venv\\Scripts\\python.exe scripts\\refresh_prices.py
"""
from __future__ import annotations

import pandas as pd

from allocator import universe
from allocator.data import cache, prices

cand = universe.candidate_set(pd.Timestamp("today").normalize())["ticker"].tolist()
cand += ["^SPX"]
print(f"clearing stale negative cache; refilling up to {len(cand)} names ...", flush=True)
cache.clear("prices_neg")
prices.reset_memory()
stats = prices.prefetch([t for t in cand if t != "^SPX"])
cache.invalidate("prices", "^SPX|full")
prices.history("^SPX")
have = sum(1 for t in cand if not prices.history(t).empty)
print(f"prefetch ok={stats['ok']} miss={stats['miss']} cached={stats['cached']}", flush=True)
print(f"coverage now: {have}/{len(cand)} names have price data", flush=True)
