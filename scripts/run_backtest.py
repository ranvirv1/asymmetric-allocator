"""M8 walk-forward backtest — the go/no-go gate (spec §8.4).

Run:  $env:PYTHONUTF8=1; .venv\\Scripts\\python.exe scripts\\run_backtest.py
First run fills the grade/price cache (a few min, some FMP quota); later runs are fast.
"""
from __future__ import annotations

import sys

import pandas as pd

from allocator import backtest
from allocator.config import load_config


def pct(x) -> str:
    return f"{x*100:+.1f}%" if isinstance(x, float) and x == x else "  n/a"


def main() -> None:
    cfg = load_config()
    rs_only = "rs" in sys.argv[1:]
    suite = backtest.rs_suite() if rs_only else backtest.default_suite()
    lead = suite[0].name  # strategy used for the catch-rate report
    if rs_only:
        print("[RS-only suite — ERM deferred: FMP grade data unavailable / quota-blocked]")
    out = backtest.run_suite(cfg, suite=suite)
    results, dates = out["results"], out["dates"]
    print(f"\nWalk-forward: {dates[0].date()} -> {dates[-1].date()}  ({len(dates)} monthly rebalances)")

    # --- headline metrics table: MEDIAN + MAX DRAWDOWN first (spec §6) ---
    print("\n" + "=" * 92)
    print(f"{'strategy':<26}{'medANN':>9}{'maxDD':>9}{'CAGR':>9}{'meanANN':>9}"
          f"{'vol':>8}{'Sortino':>9}{'hit':>7}{'turn':>7}")
    print("-" * 92)
    met = {}
    for name, res in results.items():
        m = backtest.metrics(res["equity"], res["returns"])
        met[name] = m
        if not m:
            continue
        print(f"{name:<26}{pct(m['median_annual']):>9}{pct(m['max_drawdown']):>9}"
              f"{pct(m['cagr']):>9}{pct(m['mean_annual']):>9}{pct(m['vol_annual']):>8}"
              f"{m['sortino']:>9.2f}{pct(m['hit_rate']):>7}{res['avg_turnover']:>7.2f}")

    # --- ablation deltas vs benchmark (spec §3 ablation suite) ---
    bench = "S&P 500 (buy & hold)"
    if bench in met and met[bench]:
        bcagr = met[bench]["cagr"]
        print("\nABLATION — CAGR delta vs S&P (what each rule is worth):")
        for name, m in met.items():
            if name == bench or not m:
                continue
            print(f"  {name:<26} {pct(m['cagr']-bcagr)} CAGR   (maxDD {pct(m['max_drawdown'])})")

    # --- per-year returns ---
    print("\nPER-YEAR RETURNS:")
    yr_tbl = {}
    for name, m in met.items():
        if m and isinstance(m.get("annual_returns"), pd.Series):
            yr_tbl[name] = m["annual_returns"]
    if yr_tbl:
        df = pd.DataFrame(yr_tbl)
        df.index = [d.year for d in df.index]
        for yr, row in df.iterrows():
            cells = "  ".join(f"{n[:10]}:{pct(v)}" for n, v in row.items())
            print(f"  {yr}: {cells}")

    # --- catch-rate for the lead strategy ---
    if lead in results:
        print(f"\nCATCH-RATE — did '{lead}' hold each year's top-10 movers BEFORE the move?")
        cr = backtest.catch_rate(results[lead], dates, out["closes"], out["tickers_by_date"])
        for _, r in cr.iterrows():
            print(f"  {int(r['year'])}: {int(r['caught'])}/{int(r['of'])}  ({r['catch_rate']*100:.0f}%)  {r['names']}")

    print(backtest.caveat_banner(""))


if __name__ == "__main__":
    main()
