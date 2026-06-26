"""Run the ES/NQ futures backtest + walk-forward validation.

Usage:
    python scripts/run_futures_backtest.py [ES|NQ|both] [--walk-forward]

Validates against §4 performance gates and §5 testing criteria.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from futures_bot.backtest import print_report, run_backtest, walk_forward
from futures_bot.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


def main():
    parser = argparse.ArgumentParser(description="ES/NQ Futures Backtest")
    parser.add_argument("instrument", nargs="?", default="both",
                        choices=["ES", "NQ", "both"])
    parser.add_argument("--walk-forward", "-wf", action="store_true",
                        help="Run walk-forward validation (§5)")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    instruments = ["ES", "NQ"] if args.instrument == "both" else [args.instrument]

    for inst in instruments:
        print(f"\n{'='*60}")
        print(f"  Backtesting {inst}")
        print(f"{'='*60}\n")

        try:
            if args.walk_forward:
                results = walk_forward(inst, cfg)
                if not results:
                    print(f"  No walk-forward results for {inst} (missing data?)")
                    continue
                for r in results:
                    print(print_report(r))

                combined_pnl = sum(r.total_pnl for r in results)
                combined_trades = sum(r.total_trades for r in results)
                all_passed = all(r.gates_passed for r in results)
                print(f"\n  Walk-Forward Summary ({inst}):")
                print(f"    Windows:      {len(results)}")
                print(f"    Total Trades: {combined_trades}")
                print(f"    Combined P&L: ${combined_pnl:,.2f}")
                print(f"    All Gates:    {'PASSED' if all_passed else 'FAILED'}")
            else:
                result = run_backtest(inst, cfg)
                print(print_report(result))

                csv_path = result.trades  # trades are in-memory
                print(f"\n  Logged {len(result.trades)} trades")

        except FileNotFoundError as e:
            print(f"\n  {e}")
            print(f"  Place OHLCV data in data/futures/{inst}.csv")
            print(f"  Expected columns: datetime,open,high,low,close,volume")


if __name__ == "__main__":
    main()
