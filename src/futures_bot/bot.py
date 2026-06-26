"""Main bot orchestrator — ties signals, risk, execution, and session management together.

This is the top-level loop. In live mode it processes bars as they arrive. In backtest
mode it delegates to backtest.py. Includes the manual kill switch (§6).
"""
from __future__ import annotations

import logging
import signal as os_signal
import sys
from datetime import datetime

import pandas as pd

from . import alerts, session
from .config import instrument_spec, load_config
from .execution import NinjaTraderBridge
from .orders import BracketOrder, Trade
from .risk import (RiskState, can_open, compute_stop, compute_target,
                   size_position)
from .signals import Direction, Signal, compute_indicators, evaluate
from .trade_log import TradeLog

logger = logging.getLogger("futures_bot")


class FuturesBot:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_config()
        self.instruments = list(self.cfg["instruments"].keys())
        self.bridge = NinjaTraderBridge(self.cfg)
        self.trade_log = TradeLog()
        self.risk_state = RiskState()
        self.open_trades: dict[str, Trade] = {}
        self.last_signal_bar: dict[str, int | None] = {i: None for i in self.instruments}
        self._killed = False

        os_signal.signal(os_signal.SIGINT, self._kill_handler)
        os_signal.signal(os_signal.SIGTERM, self._kill_handler)

    def start(self) -> None:
        logger.info("Starting ES/NQ Futures Bot — instruments: %s", self.instruments)
        self.bridge.connect()
        alerts.send_alert("Bot started — monitoring for signals", self.cfg)

    def kill(self) -> None:
        """Manual kill switch (§6): flatten all positions and halt immediately."""
        logger.warning("KILL SWITCH ACTIVATED — flattening all positions")
        self._killed = True

        for instrument, trade in list(self.open_trades.items()):
            trade.force_close(
                trade.entry_price, pd.Timestamp.now(),
                instrument_spec(self.cfg, instrument)["tick_size"],
                instrument_spec(self.cfg, instrument)["tick_value"],
            )
            self.trade_log.log_trade(trade)
            self.risk_state.record_fill(trade.pnl, self.cfg)

        self.bridge.flatten_all()
        self.open_trades.clear()
        self.risk_state.halted = True
        self.risk_state.halt_reason = "Manual kill switch"

        alerts.send_alert("KILL SWITCH — all positions flattened, bot halted", self.cfg, "error")
        summary = self.trade_log.daily_summary()
        alerts.send_daily_summary(summary, self.cfg)
        self.trade_log.export_csv()

    def process_bar(self, instrument: str, bar: pd.Series, bar_index: int,
                    df: pd.DataFrame) -> None:
        """Process a single bar for one instrument. Called by the data feed or backtest."""
        if self._killed:
            return

        now = bar.name if isinstance(bar.name, pd.Timestamp) else datetime.now()
        current_date = now.date() if hasattr(now, "date") else now

        if self.risk_state.session_date is None or self.risk_state.session_date != current_date:
            self.risk_state.reset_session(current_date)

        sess = session.check_session(now if isinstance(now, datetime) else datetime.now(), self.cfg)
        if not sess.can_enter and instrument not in self.open_trades:
            return

        spec = instrument_spec(self.cfg, instrument)
        tick_size = spec["tick_size"]
        tick_value = spec["tick_value"]

        # Update existing open trade
        if instrument in self.open_trades:
            trade = self.open_trades[instrument]
            status = trade.update_bar(bar, tick_size, tick_value, self.cfg)
            if status is not None:
                trade.pnl -= spec["commission"]
                self.trade_log.log_trade(trade)
                self.risk_state.record_fill(trade.pnl, self.cfg)
                self.risk_state.open_positions[instrument] = max(
                    0, self.risk_state.open_positions.get(instrument, 1) - 1
                )
                del self.open_trades[instrument]

                fill_msg = (f"{instrument} {trade.order.direction.value} "
                            f"{trade.status.value} {trade.order.contracts}ct "
                            f"@ {trade.entry_price:.2f} -> {trade.exit_price:.2f} "
                            f"P&L=${trade.pnl:.2f}")
                alerts.send_fill_alert(fill_msg, self.cfg)
                return

        if not sess.can_enter:
            return

        # Check for new signal
        signal = evaluate(df, bar_index, instrument, self.cfg,
                          self.last_signal_bar.get(instrument))
        if signal is None:
            return

        self.trade_log.log_signal(signal)
        self.last_signal_bar[instrument] = bar_index

        allowed, reason = can_open(instrument, self.risk_state, self.cfg)
        if not allowed:
            logger.info("Signal rejected: %s", reason)
            return

        atr = bar.get("atr", 0)
        if pd.isna(atr) or atr <= 0:
            return

        entry = signal.trigger_price
        stop = compute_stop(entry, signal.direction, atr, self.cfg, instrument)
        target = compute_target(entry, stop, signal.direction, atr, self.cfg, instrument)
        contracts = size_position(instrument, signal.direction, entry, stop, self.cfg)

        if contracts <= 0:
            logger.info("Position size = 0 contracts — trade skipped")
            return

        order = BracketOrder.create(
            instrument=instrument, direction=signal.direction,
            contracts=contracts, entry=entry, stop=stop, target=target,
            condition=signal.condition,
        )

        result = self.bridge.submit_bracket(order)
        logger.info("Order submitted: %s", result)

        trade = Trade.from_fill(order, entry, signal.timestamp)
        self.open_trades[instrument] = trade
        self.risk_state.open_positions[instrument] = (
            self.risk_state.open_positions.get(instrument, 0) + 1
        )

        fill_msg = (f"{instrument} {signal.direction.value} ENTRY "
                    f"{contracts}ct @ {entry:.2f} | stop={stop:.2f} target={target:.2f} "
                    f"| {signal.condition}")
        alerts.send_fill_alert(fill_msg, self.cfg)

    def end_of_day(self) -> None:
        """Daily wrap-up: summary, CSV export, alerts."""
        summary = self.trade_log.daily_summary()
        alerts.send_daily_summary(summary, self.cfg)
        self.trade_log.export_csv()
        logger.info("End of day — %s", summary)

    def _kill_handler(self, signum, frame) -> None:
        self.kill()
        sys.exit(0)
