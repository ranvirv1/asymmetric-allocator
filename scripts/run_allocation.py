"""Generate a live allocation + house-style dashboard (M1->M7 -> M9).

Run:  $env:PYTHONUTF8=1; .venv\\Scripts\\python.exe scripts\\run_allocation.py [YYYY-MM-DD]
Add 'research' to also embed the walk-forward backtest:  ... run_allocation.py 2026-06-19 research
"""
from __future__ import annotations

import sys

import pandas as pd

from allocator import backtest, pipeline, report
from allocator.config import load_config


def main() -> None:
    args = [a for a in sys.argv[1:]]
    research = "research" in args
    use_erm = "ermrs" in args  # opt-in; FMP free tier is rate-limited, so default is RS-only
    date_args = [a for a in args if a not in ("research", "ermrs")]
    as_of = date_args[0] if date_args else pd.Timestamp("today").normalize().strftime("%Y-%m-%d")
    active = ("ERM", "RS") if use_erm else ("RS",)

    cfg = load_config()
    print(f"Building live allocation for {as_of}  (signals: {'+'.join(active)}) ...", flush=True)
    result = pipeline.run_live(as_of, cfg, active=active)
    reg = result["regime"]
    alloc = result["allocation"]
    print(f"  regime: {reg.verdict} (score {reg.regime_score:+.2f})  "
          f"budget {reg.budget['anchor']:.0%}/{reg.budget['satellite']:.0%}/{reg.budget['cash']:.0%}", flush=True)
    print(f"  anchors {len(result['buckets'].anchors)} | satellites {len(result['buckets'].satellites)} "
          f"| watch {len(result['buckets'].watch)} | invested {(1-alloc.cash_weight)*100:.0f}%", flush=True)

    bt_out = None
    if research:
        print("  running walk-forward backtest for research panel ...", flush=True)
        bt_out = backtest.run_suite(cfg, suite=backtest.rs_suite())

    path = report.render_dashboard(result, backtest=bt_out)
    print(f"\nDashboard -> {path}", flush=True)

    # Console summary of the two lists
    rows = result["allocation_rows"]
    if not rows.empty:
        print("\nALLOCATION:")
        for r in rows.itertuples():
            dw = " *" if getattr(r, "designed_winner", False) else ""
            print(f"  {r.bucket:<10} {r.ticker:<6} {r.target_weight*100:5.1f}%  "
                  f"GBP {r.gbp_amount:7,.0f}  {r.shares:>4} sh @ ${r.price_usd:,.2f}  "
                  f"stop {getattr(r,'stop_price','n/a')}{dw}")


if __name__ == "__main__":
    main()
