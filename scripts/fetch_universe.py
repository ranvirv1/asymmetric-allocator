"""Fetch the blended universe (S&P 500 ∪ Nasdaq-100 ∪ TSM) and bulk-fill the price cache.

Run:  $env:PYTHONUTF8=1; .venv\\Scripts\\python.exe scripts\\fetch_universe.py
A mechanical index-membership universe (not hand-picked). yfinance batch-downloads in chunks;
partial coverage is fine (re-run fills the rest).
"""
from __future__ import annotations

import time

from allocator.data import constituents, prices


def main() -> None:
    print("Fetching S&P 500 + Nasdaq-100 + TSM from Wikipedia...", flush=True)
    df = constituents.refresh_members_csv()
    tickers = df["ticker"].tolist()
    by_index = df["index"].value_counts().to_dict() if "index" in df else {}
    print(f"  got {len(tickers)} names -> {constituents.MEMBERS_CSV}", flush=True)
    print(f"  by source: {by_index} | sample: {tickers[:8]}", flush=True)

    print("\nBulk-fetching price histories via yfinance (chunked)...", flush=True)
    t0 = time.time()
    stats = prices.prefetch(tickers, chunk=40)
    print(f"  ok={stats['ok']}  miss={stats['miss']}  already_cached={stats['cached']}"
          f"  in {time.time()-t0:.0f}s", flush=True)

    # final coverage check
    have = sum(1 for t in tickers if not prices.history(t).empty)
    print(f"\nPrice coverage: {have}/{len(tickers)} names "
          f"({have/len(tickers)*100:.0f}%) now have data.", flush=True)
    if have < len(tickers):
        print("  (re-run this script after a few minutes to fill the rest — yfinance rate-limits)",
              flush=True)


if __name__ == "__main__":
    main()
