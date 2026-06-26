"""Entry point for the ES/NQ Futures Trading Bot.

Usage:
    python scripts/run_bot.py                  # live mode (requires NinjaTrader webhook)
    python scripts/run_bot.py --dry-run        # dry run (no live orders)
    python scripts/run_bot.py --paper          # paper trading mode

The bot must clear §4 performance gates before promotion to live capital.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from futures_bot.bot import FuturesBot
from futures_bot.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data/futures/logs/bot.log", mode="a"),
    ],
)


def main():
    parser = argparse.ArgumentParser(description="ES/NQ Futures Trading Bot")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run without submitting live orders")
    parser.add_argument("--paper", action="store_true",
                        help="Paper trading mode — log signals and simulated fills")
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.dry_run or args.paper:
        cfg["execution"]["webhook_url"] = ""
        mode = "PAPER" if args.paper else "DRY RUN"
    else:
        mode = "LIVE"

    print(f"""
╔══════════════════════════════════════════════════════════╗
║       ES/NQ Futures Trading Bot — Scalper v2.0          ║
║                                                         ║
║  Mode:        {mode:<42s} ║
║  Instruments: ES, NQ                                    ║
║  Signal:      {cfg['signal']['name']:<42s} ║
║  Account:     ${cfg['account']['size']:>10,.0f}                            ║
║  Risk/trade:  {cfg['risk']['max_risk_per_trade_pct']}% / ${cfg['risk']['max_risk_per_trade_usd']:,.0f}                          ║
║  Daily limit: {cfg['risk']['daily_loss_limit_pct']}% / ${cfg['risk']['daily_loss_limit_usd']:,.0f}                         ║
║                                                         ║
║  Kill switch: Ctrl+C or SIGTERM                         ║
╚══════════════════════════════════════════════════════════╝
""")

    bot = FuturesBot(cfg)
    bot.start()

    print("Bot is ready. In production, connect a data feed (e.g. NinjaTrader,")
    print("TradingView webhook) to call bot.process_bar() for each new bar.")
    print()
    print("For backtesting, run: python scripts/run_futures_backtest.py")
    print("For the kill switch, press Ctrl+C at any time.")


if __name__ == "__main__":
    main()
