"""Diff two saved book records (reports/history/alloc_<date>.json) — or list what exists.

Run:  python .claude/skills/allocator-diagnostics-and-tooling/scripts/book_diff.py            # list runs
      python ... book_diff.py 2026-06-19 2026-06-26                                            # diff two
Reads only local JSON; no keys, no network.
"""
from __future__ import annotations

import json
import sys

from allocator.weekly import HIST_DIR


def load(date: str) -> dict:
    p = HIST_DIR / f"alloc_{date}.json"
    if not p.exists():
        sys.exit(f"no record: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    if not HIST_DIR.exists() or not any(HIST_DIR.glob("alloc_*.json")):
        print(f"no book history yet in {HIST_DIR} — run scripts/weekly_run.py to create one.")
        return
    runs = sorted(f.stem.replace("alloc_", "") for f in HIST_DIR.glob("alloc_*.json"))
    if len(sys.argv) < 3:
        print("saved runs:")
        for r in runs:
            rec = load(r)
            print(f"  {r}  {rec['regime']:<12} {len(rec['positions'])} positions")
        print("\nusage: book_diff.py <date_a> <date_b>")
        return
    a, b = load(sys.argv[1]), load(sys.argv[2])
    pa, pb = a["positions"], b["positions"]
    print(f"{a['as_of']} ({a['regime']})  ->  {b['as_of']} ({b['regime']})")
    for t in sorted(set(pb) - set(pa)):
        print(f"  + BUY   {t:<7} {pb[t]['weight']*100:5.1f}%  £{pb[t]['gbp']:,.0f}  [{pb[t]['bucket']}]")
    for t in sorted(set(pa) - set(pb)):
        print(f"  - SELL  {t:<7} was {pa[t]['weight']*100:5.1f}%  £{pa[t]['gbp']:,.0f}")
    for t in sorted(set(pa) & set(pb)):
        dw = pb[t]["weight"] - pa[t]["weight"]
        if abs(dw) >= 0.005:
            print(f"  ~ {'ADD ' if dw > 0 else 'TRIM'}  {t:<7} {dw*100:+5.1f}pt")
    wa, wb = sum(p["weight"] for p in pa.values()), sum(p["weight"] for p in pb.values())
    print(f"deployed: {wa*100:.0f}% -> {wb*100:.0f}%")


if __name__ == "__main__":
    main()
