"""Risk controls — per-trade sizing, daily loss limits, consecutive-loss pause (§3).

Every check is hard-enforced: the bot cannot open a position that violates these limits.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from .config import instrument_spec
from .signals import Direction


@dataclass
class RiskState:
    """Mutable session-level risk state, reset at each new trading day."""
    session_date: date | None = None
    session_pnl: float = 0.0
    consecutive_losses: int = 0
    open_positions: dict[str, int] = field(default_factory=dict)  # instrument -> count
    halted: bool = False
    halt_reason: str = ""

    def reset_session(self, d: date) -> None:
        self.session_date = d
        self.session_pnl = 0.0
        self.halted = False
        self.halt_reason = ""

    def record_fill(self, pnl: float, cfg: dict) -> None:
        """Update state after a trade closes. Returns nothing but may set halted=True."""
        self.session_pnl += pnl
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        risk_cfg = cfg["risk"]
        acct = float(cfg["account"]["size"])
        daily_limit_pct = risk_cfg["daily_loss_limit_pct"] / 100.0 * acct
        daily_limit_usd = float(risk_cfg["daily_loss_limit_usd"])
        daily_limit = min(daily_limit_pct, daily_limit_usd)
        if self.session_pnl <= -daily_limit:
            self.halted = True
            self.halt_reason = f"Daily loss limit hit: ${self.session_pnl:,.2f} (limit ${daily_limit:,.2f})"

        max_consec = risk_cfg["max_consecutive_losses"]
        if self.consecutive_losses >= max_consec:
            self.halted = True
            self.halt_reason = (
                f"Max consecutive losses ({self.consecutive_losses}) — paused for manual review"
            )


def size_position(instrument: str, direction: Direction, entry: float, stop: float,
                  cfg: dict) -> int:
    """Calculate the number of contracts to trade, respecting per-trade risk limits.

    Returns 0 if the trade would violate risk limits (meaning: do not enter).
    """
    spec = instrument_spec(cfg, instrument)
    risk_cfg = cfg["risk"]
    acct = float(cfg["account"]["size"])

    risk_per_trade_pct = risk_cfg["max_risk_per_trade_pct"] / 100.0 * acct
    risk_per_trade_usd = float(risk_cfg["max_risk_per_trade_usd"])
    max_risk = min(risk_per_trade_pct, risk_per_trade_usd)

    tick_size = spec["tick_size"]
    tick_value = spec["tick_value"]
    stop_distance = abs(entry - stop)
    ticks_at_risk = stop_distance / tick_size
    risk_per_contract = ticks_at_risk * tick_value + spec["commission"]

    if risk_per_contract <= 0:
        return 0

    contracts = int(math.floor(max_risk / risk_per_contract))
    return max(contracts, 0)


def can_open(instrument: str, risk_state: RiskState, cfg: dict) -> tuple[bool, str]:
    """Pre-entry gate: returns (allowed, reason)."""
    if risk_state.halted:
        return False, risk_state.halt_reason

    risk_cfg = cfg["risk"]
    current = risk_state.open_positions.get(instrument, 0)
    if current >= risk_cfg["max_open_positions_per_instrument"]:
        return False, f"Max open positions for {instrument} ({current})"

    total = sum(risk_state.open_positions.values())
    if total >= risk_cfg["max_total_positions"]:
        return False, f"Max total positions ({total})"

    return True, ""


def compute_stop(entry: float, direction: Direction, atr: float, cfg: dict,
                 instrument: str) -> float:
    """Compute the stop-loss price for a new trade."""
    exits = cfg["exits"]
    spec = instrument_spec(cfg, instrument)
    tick_size = spec["tick_size"]

    if exits["stop_mode"] == "atr":
        distance = exits["stop_atr_mult"] * atr
    else:
        distance = exits["stop_fixed_ticks"] * tick_size

    if direction == Direction.LONG:
        return entry - distance
    else:
        return entry + distance


def compute_target(entry: float, stop: float, direction: Direction, atr: float,
                   cfg: dict, instrument: str) -> float:
    """Compute the profit-target price for a new trade."""
    exits = cfg["exits"]
    spec = instrument_spec(cfg, instrument)
    tick_size = spec["tick_size"]

    if exits["target_mode"] == "atr":
        distance = exits["target_atr_mult"] * atr
    elif exits["target_mode"] == "fixed_ticks":
        distance = exits["target_fixed_ticks"] * tick_size
    else:
        stop_distance = abs(entry - stop)
        distance = stop_distance * exits["target_rr_ratio"]

    if direction == Direction.LONG:
        return entry + distance
    else:
        return entry - distance
