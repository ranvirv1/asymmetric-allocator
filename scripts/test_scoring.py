"""M4 scoring verification (spec §8.3 test):
top scorers in Dec-2022 should include 2023 winners; Dec-2023 include 2024 winners.
Also reports ERM coverage (does FMP grade history reach back to the as-of date?).

Run:  .venv\\Scripts\\python.exe scripts\\test_scoring.py
"""
from __future__ import annotations

from allocator import regime, scoring, universe
from allocator.config import load_config

CASES = [
    ("2022-12-30", "2023 winners", ["NVDA", "META", "AMD", "PLTR", "CRM", "TSM", "AVGO"]),
    ("2023-12-29", "2024 winners", ["NVDA", "VST", "PLTR", "AVGO", "GEV", "CEG", "AMZN"]),
]


def main() -> None:
    cfg = load_config()
    for as_of, label, winners in CASES:
        uni = universe.build_universe(as_of, cfg, with_mktcap=False)
        tickers = uni.members["ticker"].tolist()
        verdict = regime.compute_regime(as_of, cfg, breadth_tickers=tickers).verdict
        scored = scoring.score_universe(as_of, tickers, verdict, cfg)

        covered = int(scored["erm_covered"].sum()) if "erm_covered" in scored else 0
        print("\n" + "=" * 68)
        print(f"as of {as_of}  | regime {verdict} | weights {scored.attrs['weights']}")
        print(f"ERM coverage: {covered}/{len(scored)} names had FMP grade actions in window")
        print("=" * 68)
        print(f"{'rank':<5}{'ticker':<8}{'winner':>8}{'ERM':>7}{'RS':>7}")
        for i, (tkr, row) in enumerate(scored.head(15).iterrows(), 1):
            erm = f"{row['ERM']:.0f}" if "ERM" in row and row["ERM"] == row["ERM"] else "  -"
            rs = f"{row['RS']:.0f}" if "RS" in row and row["RS"] == row["RS"] else "  -"
            print(f"{i:<5}{tkr:<8}{row['winner_score']:>8.1f}{erm:>7}{rs:>7}")

        top10 = list(scored.head(10).index)
        hits = [w for w in winners if w in top10]
        print(f"\n  known {label} in TOP 10: {hits or 'NONE'}  "
              f"({len(hits)}/{len([w for w in winners if w in tickers])} of those in universe)")


if __name__ == "__main__":
    main()
