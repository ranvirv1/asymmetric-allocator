"""Weekly run — the standalone entry point (manual or scheduled).

  weekly_run.py                 -> refresh data, build today's book, write+open reports/latest.html
  weekly_run.py 2026-06-19      -> run for a specific date
  weekly_run.py noopen          -> don't auto-open browser (used by the scheduled task)
  weekly_run.py norefresh       -> skip the data refresh (fast re-run off cache)
  weekly_run.py snapshot        -> also bank this week's estimate snapshot (spec §8.8)
  weekly_run.py research        -> also embed the backtest panel
  weekly_run.py ermrs           -> add ERM to scoring (DEFAULT IS RS-ONLY — ERM failed the
                                   backtest ablation: it cut CAGR 34%->16%. Opt-in only.)

Writes a dated copy AND reports/latest.html (what the desktop shortcut points at).
"""
from __future__ import annotations

import sys
import webbrowser

import pandas as pd

from allocator import backtest, pipeline, report, universe, weekly
from allocator.config import REPORTS_DIR, load_config

FLAGS = {"noopen", "norefresh", "research", "ermrs", "snapshot", "returns", "safe", "early",
         "nogpt", "claudelog", "top5", "top10", "top15"}


def main() -> None:
    args = sys.argv[1:]
    flags = {a for a in args if a in FLAGS}
    date_args = [a for a in args if a not in FLAGS]
    as_of = date_args[0] if date_args else pd.Timestamp("today").normalize().strftime("%Y-%m-%d")
    # Signal: RS-only is VALIDATED (ERM hurt OOS, spec §6). `early` = EXPERIMENTAL emerging-momentum
    # (short-window + acceleration + volume + breakout); `ermrs` adds the estimate-revision signal.
    if "early" in flags:
        active = ("EARLY",)
    elif "ermrs" in flags:
        active = ("ERM", "RS")
    else:
        active = ("RS",)
    cfg = load_config()
    # mode dial: `returns` = full deploy (higher CAGR); `safe`/`early` keep the regime cash sleeve.
    if "returns" in flags:
        cfg.setdefault("live", {})["use_regime_gate"] = False
    elif "safe" in flags or "early" in flags:
        cfg.setdefault("live", {})["use_regime_gate"] = True
    # concentration dial: top5 / top10 / top15 picks.
    for _n in (5, 10, 15):
        if f"top{_n}" in flags:
            cfg.setdefault("cuts", {})["max_anchors"] = _n
            break

    if "norefresh" not in flags:
        tickers = universe.candidate_set(pd.Timestamp(as_of))["ticker"].tolist()
        print(f"Refreshing prices + macro for {len(tickers)} names (this takes a few min) ...", flush=True)
        stats = weekly.refresh_live_data(tickers)
        print(f"  prices refreshed: ok={stats['ok']} miss={stats['miss']}", flush=True)

    print(f"Building book for {as_of} (signals: {'+'.join(active)}) ...", flush=True)
    result = pipeline.run_live(as_of, cfg, active=active)

    # Safety guard: if the universe came back degenerate the price feed is incomplete
    # (provider rate-limited / cache wiped) — abort rather than overwrite latest.html with a
    # broken 1-name book. The previous good report stays in place.
    n_uni = len(result["universe"].members)
    if n_uni < 50:
        print(f"ABORT: only {n_uni} names have price data — the data provider looks rate-limited. "
              f"Keeping the previous report (latest.html unchanged). Try again later.", flush=True)
        sys.exit(2)

    reg, alloc = result["regime"], result["allocation"]
    print(f"  {reg.verdict} | deploy {(1-alloc.cash_weight)*100:.0f}% | "
          f"{len(result['buckets'].anchors)} anchors, {len(result['buckets'].satellites)} satellites", flush=True)

    diff = weekly.diff_vs_prev(result)
    weekly.save_run(result)
    if diff.get("is_initial"):
        print("  (first run — no prior book to diff)", flush=True)
    else:
        print(f"  changes vs {diff['prev_date']}: {len(diff['buys'])} buys, "
              f"{len(diff['sells'])} sells, {len(diff['changes'])} adjusts", flush=True)

    if "snapshot" in flags:
        snap_tickers = result["universe"].members["ticker"].tolist()
        print(f"Banking estimate snapshot for {len(snap_tickers)} names (spec §8.8) ...", flush=True)
        snap = weekly.take_snapshot(snap_tickers, pd.Timestamp(as_of))
        print(f"  snapshot: {snap['saved']} names -> {snap['path']}", flush=True)

    bt_out = backtest.run_suite(cfg, suite=backtest.rs_suite()) if "research" in flags else None

    # Weekly auto-roll: close the live Claude round and open a fresh one from today's anchors.
    if "claudelog" in flags:
        try:
            roll = weekly.roll_claude_round(result, pd.Timestamp(as_of))
            if roll.get("rolled"):
                print(f"  Claude round rolled: #{roll['round_id']} {roll['tickers']}", flush=True)
            else:
                print(f"  Claude round not rolled ({roll.get('reason')})", flush=True)
        except Exception as e:
            print(f"  (Claude auto-log skipped: {e})", flush=True)

    gpt_results = None
    if "nogpt" not in flags:
        try:
            from allocator import gpt_benchmark
            gpt_results = gpt_benchmark.run_comparison()
            print(f"  GPT benchmark: scored {len(gpt_results)} pick rounds", flush=True)
        except Exception as e:  # never let the benchmark break the report
            print(f"  (GPT benchmark skipped: {e})", flush=True)

    report.render_dashboard(result, diff=diff, backtest=bt_out, next_run="Mon 07:00",
                            gpt_comparison=gpt_results)
    latest = report.render_dashboard(result, diff=diff, backtest=bt_out, next_run="Mon 07:00",
                                     out_path=REPORTS_DIR / "latest.html", gpt_comparison=gpt_results)
    print(f"\nReport -> {latest}", flush=True)
    if "noopen" not in flags:
        webbrowser.open(latest.as_uri())


if __name__ == "__main__":
    main()
