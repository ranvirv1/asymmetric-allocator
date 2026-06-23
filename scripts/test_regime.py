"""M2 regime-gate verification (spec §8 milestone 2 test):
prints COMPRESSION across 2022 and RISK-ON across 2023/2025.

Run:  .venv\\Scripts\\python.exe scripts\\test_regime.py
"""
from __future__ import annotations

from allocator.config import load_config
from allocator import regime, universe

DATES = [
    "2021-12-31",  # late bull
    "2022-03-31", "2022-06-30", "2022-09-30", "2022-12-30",  # bear -> COMPRESSION
    "2023-06-30", "2023-12-29",  # recovery -> RISK_ON
    "2024-06-28",
    "2025-02-28",  # pre tariff-dip, trend intact -> RISK_ON
    "2025-06-02",  # just after the April-2025 drawdown -> borderline
    "2025-09-30",
]


def main() -> None:
    cfg = load_config()
    print(f"{'date':<12}{'verdict':<13}{'score':>7}{'spx/200d':>10}{'6m ret':>9}"
          f"{'CSz':>7}{'CSchg1m':>8}{'breadth':>9}")
    print("-" * 75)
    for d in DATES:
        uni = universe.build_universe(d, cfg, with_mktcap=False)
        tickers = uni.members["ticker"].tolist()
        r = regime.compute_regime(d, cfg, breadth_tickers=tickers)
        c = r.components
        def g(k):
            v = c.get(k)
            return f"{v:+.2f}" if isinstance(v, float) and v == v else "  n/a"
        breadth = c.get("breadth_above_200dma")
        bstr = f"{breadth*100:.0f}%" if isinstance(breadth, float) and breadth == breadth else "n/a"
        print(f"{d:<12}{r.verdict:<13}{r.regime_score:>+7.2f}"
              f"{g('spx_vs_200dma'):>10}{g('spx_6m_ret'):>9}"
              f"{g('credit_spread_level_z'):>7}{g('credit_spread_1mo_chg'):>8}{bstr:>9}")

    print("\nBudgets per verdict (anchor/satellite/cash):")
    for v, b in cfg["regime_budgets"].items():
        print(f"  {v:<12} {b['anchor']:.0%} / {b['satellite']:.0%} / {b['cash']:.0%}")


if __name__ == "__main__":
    main()
