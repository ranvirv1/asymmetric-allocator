"""Cache inventory: files, bytes, and age per namespace in data/cache (respects DATA_DIR).

Run:  python .claude/skills/allocator-diagnostics-and-tooling/scripts/cache_stats.py
Needs only the repo install (no keys, no network). Empty cache exits cleanly.
"""
from __future__ import annotations

import time
from collections import defaultdict

from allocator.config import CACHE_DIR


def main() -> None:
    if not CACHE_DIR.exists():
        print(f"cache dir does not exist yet: {CACHE_DIR}")
        print("(nothing has been fetched — run scripts/fetch_universe.py to bootstrap)")
        return
    stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "bytes": 0, "oldest": None, "newest": None})
    for p in CACHE_DIR.iterdir():
        if not p.is_file() or "__" not in p.name:
            continue
        ns = p.name.split("__", 1)[0]
        st = p.stat()
        s = stats[ns]
        s["n"] += 1
        s["bytes"] += st.st_size
        s["oldest"] = st.st_mtime if s["oldest"] is None else min(s["oldest"], st.st_mtime)
        s["newest"] = st.st_mtime if s["newest"] is None else max(s["newest"], st.st_mtime)
    if not stats:
        print(f"cache dir {CACHE_DIR} exists but is empty.")
        return
    now = time.time()
    print(f"cache: {CACHE_DIR}")
    print(f"{'namespace':<14}{'files':>7}{'MB':>9}{'oldest(d)':>11}{'newest(d)':>11}")
    for ns in sorted(stats):
        s = stats[ns]
        print(f"{ns:<14}{s['n']:>7}{s['bytes']/1e6:>9.1f}"
              f"{(now - s['oldest'])/86400:>11.1f}{(now - s['newest'])/86400:>11.1f}")
    neg = stats.get("prices_neg", {}).get("n", 0)
    if neg:
        print(f"\nNOTE: {neg} prices_neg entries = names that returned NO data recently "
              f"(6h TTL). Many of these after a run usually means the provider rate-limited; "
              f"scripts/refresh_prices.py clears them and refills.")


if __name__ == "__main__":
    main()
