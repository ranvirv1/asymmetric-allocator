"""Price-cache coverage for the configured universe — CACHE ONLY, never triggers network.

Reports: how many universe tickers have a cached price frame, the span of last-dates, and
names whose newest bar is stale (> --stale-days, default 7).

Run:  python .claude/skills/allocator-diagnostics-and-tooling/scripts/price_coverage.py [--stale-days N]
"""
from __future__ import annotations

import sys

import pandas as pd

from allocator.config import DATA_DIR
from allocator.data import cache


def universe_tickers() -> list[str]:
    from allocator.config import load_config
    src = load_config().get("universe", {}).get("source", "seed")
    path = DATA_DIR / ("sp500_constituents.csv" if src == "sp500" else "universe_seed.csv")
    if not path.exists():
        path = DATA_DIR / "universe_seed.csv"
    df = pd.read_csv(path, comment="#")
    return df["ticker"].str.strip().str.upper().tolist()


def main() -> None:
    stale_days = 7
    if "--stale-days" in sys.argv:
        stale_days = int(sys.argv[sys.argv.index("--stale-days") + 1])
    tickers = universe_tickers()
    have, missing, last_dates, stale = 0, [], [], []
    today = pd.Timestamp.today().normalize()
    for t in tickers:
        df = cache.get_df("prices", f"{t}|full")   # disk cache only — no fetch
        if df is None or df.empty:
            missing.append(t)
            continue
        have += 1
        last = df.index.max()
        last_dates.append(last)
        if (today - last).days > stale_days:
            stale.append((t, str(last.date())))
    print(f"universe: {len(tickers)} names | cached: {have} "
          f"({have/len(tickers)*100:.0f}%) | missing: {len(missing)}")
    if last_dates:
        print(f"last-bar span: {min(last_dates).date()} .. {max(last_dates).date()}")
    if stale:
        print(f"\nSTALE (> {stale_days}d old) — refresh before a live run "
              f"(weekly_run refreshes automatically unless norefresh):")
        for t, d in stale[:20]:
            print(f"  {t:<7} last bar {d}")
        if len(stale) > 20:
            print(f"  ... and {len(stale)-20} more")
    if missing:
        print(f"\nmissing (first 20): {', '.join(missing[:20])}")
        print("interpretation: pre-IPO/delisted/symbol-miss OR never fetched. "
              "Fill with scripts/refresh_prices.py; >10% missing after a refill = provider trouble.")


if __name__ == "__main__":
    main()
