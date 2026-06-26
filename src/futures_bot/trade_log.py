"""Trade logging — full audit trail, CSV export, daily P&L summary (§6).

Every fill, every error, and every signal is logged with timestamp, instrument,
direction, trigger price, and the condition that fired it.
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import DATA_DIR
from .orders import Trade, TradeStatus
from .signals import Signal

logger = logging.getLogger("futures_bot.trade_log")

LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

_TRADE_FIELDS = [
    "trade_id", "order_id", "instrument", "direction", "contracts",
    "entry_time", "entry_price", "exit_time", "exit_price",
    "stop_price", "target_price", "status", "pnl", "pnl_ticks",
    "bars_held", "signal_condition",
]


class TradeLog:
    def __init__(self, log_dir: Path | None = None):
        self.log_dir = log_dir or LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.trades: list[dict] = []
        self.signals: list[dict] = []
        self.errors: list[dict] = []

    def log_signal(self, signal: Signal) -> None:
        entry = {
            "timestamp": str(signal.timestamp),
            "instrument": signal.instrument,
            "direction": signal.direction.value,
            "trigger_price": signal.trigger_price,
            "condition": signal.condition,
            "bar_index": signal.bar_index,
        }
        self.signals.append(entry)
        logger.info("SIGNAL %s %s @ %.2f | %s",
                     signal.instrument, signal.direction.value,
                     signal.trigger_price, signal.condition)

    def log_trade(self, trade: Trade) -> None:
        entry = {
            "trade_id": trade.trade_id,
            "order_id": trade.order.order_id,
            "instrument": trade.order.instrument,
            "direction": trade.order.direction.value,
            "contracts": trade.order.contracts,
            "entry_time": str(trade.entry_time),
            "entry_price": trade.entry_price,
            "exit_time": str(trade.exit_time) if trade.exit_time else "",
            "exit_price": trade.exit_price or 0,
            "stop_price": trade.order.stop_price,
            "target_price": trade.order.target_price,
            "status": trade.status.value,
            "pnl": round(trade.pnl, 2),
            "pnl_ticks": round(trade.pnl_ticks, 2),
            "bars_held": trade.bars_held,
            "signal_condition": trade.order.signal_condition,
        }
        self.trades.append(entry)
        logger.info("TRADE %s %s %s %d @ %.2f -> %.2f  P&L=$%.2f (%s)",
                     trade.order.instrument, trade.order.direction.value,
                     trade.status.value, trade.order.contracts,
                     trade.entry_price, trade.exit_price or 0,
                     trade.pnl, trade.order.signal_condition)

    def log_error(self, msg: str, context: dict | None = None) -> None:
        entry = {"timestamp": str(datetime.now()), "error": msg, "context": context or {}}
        self.errors.append(entry)
        logger.error("ERROR: %s %s", msg, json.dumps(context or {}))

    def export_csv(self, filename: str | None = None) -> Path:
        fn = filename or f"trades_{date.today().isoformat()}.csv"
        path = self.log_dir / fn
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_TRADE_FIELDS)
            writer.writeheader()
            for t in self.trades:
                writer.writerow({k: t.get(k, "") for k in _TRADE_FIELDS})
        logger.info("Exported %d trades to %s", len(self.trades), path)
        return path

    def daily_summary(self) -> dict:
        if not self.trades:
            return {"trades": 0, "pnl": 0, "winners": 0, "losers": 0}
        df = pd.DataFrame(self.trades)
        closed = df[df["status"] != TradeStatus.OPEN.value]
        total_pnl = closed["pnl"].sum() if not closed.empty else 0
        winners = int((closed["pnl"] > 0).sum()) if not closed.empty else 0
        losers = int((closed["pnl"] < 0).sum()) if not closed.empty else 0
        return {
            "date": str(date.today()),
            "trades": len(closed),
            "pnl": round(total_pnl, 2),
            "winners": winners,
            "losers": losers,
            "win_rate": round(winners / len(closed) * 100, 1) if len(closed) else 0,
            "signals": len(self.signals),
            "errors": len(self.errors),
        }
