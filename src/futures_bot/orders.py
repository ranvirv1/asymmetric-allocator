"""Order management — bracket orders, fill tracking, trailing stops (§3).

Every trade is placed as a bracket order (entry + stop + target) so the stop fires
broker-side even if the bot disconnects.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

from .signals import Direction


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    STOPPED = "STOPPED"
    TARGET_HIT = "TARGET_HIT"
    TIME_STOPPED = "TIME_STOPPED"
    TRAILING_STOPPED = "TRAILING_STOPPED"
    KILLED = "KILLED"


@dataclass
class BracketOrder:
    order_id: str
    instrument: str
    direction: Direction
    contracts: int
    entry_price: float
    stop_price: float
    target_price: float
    status: OrderStatus = OrderStatus.PENDING
    timestamp: pd.Timestamp = field(default_factory=pd.Timestamp.now)
    signal_condition: str = ""

    @staticmethod
    def create(instrument: str, direction: Direction, contracts: int,
               entry: float, stop: float, target: float,
               condition: str = "") -> BracketOrder:
        return BracketOrder(
            order_id=str(uuid.uuid4())[:12],
            instrument=instrument, direction=direction, contracts=contracts,
            entry_price=entry, stop_price=stop, target_price=target,
            signal_condition=condition,
        )


@dataclass
class Trade:
    trade_id: str
    order: BracketOrder
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    status: TradeStatus = TradeStatus.OPEN
    pnl: float = 0.0
    pnl_ticks: float = 0.0
    bars_held: int = 0
    trailing_stop: float | None = None
    peak_favourable: float | None = None

    @staticmethod
    def from_fill(order: BracketOrder, fill_price: float,
                  fill_time: pd.Timestamp) -> Trade:
        return Trade(
            trade_id=str(uuid.uuid4())[:12],
            order=order, entry_time=fill_time, entry_price=fill_price,
            peak_favourable=fill_price,
        )

    def update_bar(self, bar: pd.Series, tick_size: float, tick_value: float,
                   cfg: dict) -> TradeStatus | None:
        """Process a new bar. Returns the new status if the trade closed, else None."""
        self.bars_held += 1
        high, low, close = bar["high"], bar["low"], bar["close"]
        exits = cfg["exits"]

        direction = self.order.direction
        is_long = direction == Direction.LONG

        # Update peak favourable excursion
        if is_long:
            if high > (self.peak_favourable or self.entry_price):
                self.peak_favourable = high
        else:
            if low < (self.peak_favourable or self.entry_price):
                self.peak_favourable = low

        # --- Trailing stop activation and update ---
        if exits.get("use_trailing", False) and self.peak_favourable is not None:
            atr = bar.get("atr", 0)
            activation = exits["trail_activation_atr"] * atr if atr else 0
            trail_dist = exits["trail_atr_mult"] * atr if atr else 0

            if is_long:
                if self.peak_favourable - self.entry_price >= activation:
                    new_trail = self.peak_favourable - trail_dist
                    if self.trailing_stop is None or new_trail > self.trailing_stop:
                        self.trailing_stop = new_trail
            else:
                if self.entry_price - self.peak_favourable >= activation:
                    new_trail = self.peak_favourable + trail_dist
                    if self.trailing_stop is None or new_trail < self.trailing_stop:
                        self.trailing_stop = new_trail

        # --- Check exits in priority order ---
        # 1. Stop-loss
        if is_long and low <= self.order.stop_price:
            return self._close(self.order.stop_price, bar, tick_size, tick_value, TradeStatus.STOPPED)
        if not is_long and high >= self.order.stop_price:
            return self._close(self.order.stop_price, bar, tick_size, tick_value, TradeStatus.STOPPED)

        # 2. Trailing stop
        if self.trailing_stop is not None:
            if is_long and low <= self.trailing_stop:
                return self._close(self.trailing_stop, bar, tick_size, tick_value, TradeStatus.TRAILING_STOPPED)
            if not is_long and high >= self.trailing_stop:
                return self._close(self.trailing_stop, bar, tick_size, tick_value, TradeStatus.TRAILING_STOPPED)

        # 3. Profit target
        if is_long and high >= self.order.target_price:
            return self._close(self.order.target_price, bar, tick_size, tick_value, TradeStatus.TARGET_HIT)
        if not is_long and low <= self.order.target_price:
            return self._close(self.order.target_price, bar, tick_size, tick_value, TradeStatus.TARGET_HIT)

        # 4. Time-stop
        time_stop_bars = exits.get("time_stop_bars", 30)
        if self.bars_held >= time_stop_bars:
            return self._close(close, bar, tick_size, tick_value, TradeStatus.TIME_STOPPED)

        return None

    def _close(self, price: float, bar: pd.Series, tick_size: float,
               tick_value: float, status: TradeStatus) -> TradeStatus:
        self.exit_price = price
        ts = bar.name if isinstance(bar.name, pd.Timestamp) else pd.Timestamp.now()
        self.exit_time = ts
        self.status = status
        is_long = self.order.direction == Direction.LONG
        if is_long:
            self.pnl_ticks = (price - self.entry_price) / tick_size
        else:
            self.pnl_ticks = (self.entry_price - price) / tick_size
        self.pnl = self.pnl_ticks * tick_value * self.order.contracts
        return status

    def force_close(self, price: float, timestamp: pd.Timestamp, tick_size: float,
                    tick_value: float) -> None:
        """Kill switch — flatten immediately."""
        self.exit_price = price
        self.exit_time = timestamp
        self.status = TradeStatus.KILLED
        is_long = self.order.direction == Direction.LONG
        if is_long:
            self.pnl_ticks = (price - self.entry_price) / tick_size
        else:
            self.pnl_ticks = (self.entry_price - price) / tick_size
        self.pnl = self.pnl_ticks * tick_value * self.order.contracts
