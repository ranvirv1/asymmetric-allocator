"""Scalper v2.0 signal engine — every entry fires from one named, testable rule-set.

No discretionary overrides. Each signal logs timestamp, instrument, direction,
trigger price, and the condition that fired it (§3 entry criteria).

The rule-set below is a configurable scalper framework (EMA crossover + RSI + VWAP +
momentum). Replace the logic in `evaluate()` with the exact Pine Script conditions
once the Scalper v2.0 strategy is finalised.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Signal:
    timestamp: pd.Timestamp
    instrument: str
    direction: Direction
    trigger_price: float
    condition: str
    bar_index: int


def compute_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Attach all indicators used by the rule-set to the OHLCV dataframe."""
    sig = cfg["signal"]
    c = df["close"].copy()

    df["ema_fast"] = c.ewm(span=sig["ema_fast"], adjust=False).mean()
    df["ema_slow"] = c.ewm(span=sig["ema_slow"], adjust=False).mean()
    df["ema_trend"] = c.ewm(span=sig["ema_trend"], adjust=False).mean()

    # RSI
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / sig["rsi_period"], adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / sig["rsi_period"], adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)

    # ATR
    atr_period = cfg["exits"]["atr_period"]
    high, low = df["high"], df["low"]
    prev_close = c.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=atr_period, adjust=False).mean()

    # Momentum
    df["momentum"] = c - c.shift(sig["momentum_period"])

    # VWAP (session-based; for backtest approximate as cumulative)
    if "volume" in df.columns and sig.get("use_vwap", True):
        tp = (high + low + c) / 3
        cum_vol = df["volume"].cumsum()
        cum_tp_vol = (tp * df["volume"]).cumsum()
        df["vwap"] = cum_tp_vol / cum_vol.replace(0, np.nan)
    else:
        df["vwap"] = np.nan

    return df


def _crossover(fast: pd.Series, slow: pd.Series, idx: int) -> bool:
    if idx < 1:
        return False
    return fast.iloc[idx] > slow.iloc[idx] and fast.iloc[idx - 1] <= slow.iloc[idx - 1]


def _crossunder(fast: pd.Series, slow: pd.Series, idx: int) -> bool:
    if idx < 1:
        return False
    return fast.iloc[idx] < slow.iloc[idx] and fast.iloc[idx - 1] >= slow.iloc[idx - 1]


def evaluate(df: pd.DataFrame, idx: int, instrument: str, cfg: dict,
             last_signal_bar: int | None = None) -> Signal | None:
    """Evaluate the rule-set at bar `idx`. Returns a Signal or None.

    Dedup: no repeat signal within `dedup_bars` of the last signal (§3).
    """
    sig_cfg = cfg["signal"]
    dedup = sig_cfg.get("dedup_bars", 5)
    if last_signal_bar is not None and (idx - last_signal_bar) < dedup:
        return None

    row = df.iloc[idx]
    close = row["close"]
    ema_fast = row["ema_fast"]
    ema_slow = row["ema_slow"]
    ema_trend = row["ema_trend"]
    rsi = row["rsi"]
    momentum = row["momentum"]
    vwap = row.get("vwap", np.nan)

    if pd.isna(ema_fast) or pd.isna(ema_slow) or pd.isna(ema_trend) or pd.isna(rsi):
        return None

    conditions: list[str] = []

    # --- LONG ---
    long_cross = _crossover(df["ema_fast"], df["ema_slow"], idx)
    long_trend = close > ema_trend
    long_rsi = rsi < sig_cfg["rsi_overbought"]
    long_momentum = pd.notna(momentum) and momentum > 0
    long_vwap = pd.isna(vwap) or close > vwap

    if long_cross and long_trend and long_rsi and long_momentum and long_vwap:
        conditions.append(f"EMA{sig_cfg['ema_fast']}x{sig_cfg['ema_slow']} bullish cross")
        conditions.append(f"above EMA{sig_cfg['ema_trend']} trend")
        if long_vwap and pd.notna(vwap):
            conditions.append("above VWAP")
        conditions.append(f"RSI={rsi:.1f} momentum={momentum:.2f}")
        ts = df.index[idx] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now()
        return Signal(
            timestamp=ts, instrument=instrument, direction=Direction.LONG,
            trigger_price=close, condition=" | ".join(conditions), bar_index=idx,
        )

    # --- SHORT ---
    short_cross = _crossunder(df["ema_fast"], df["ema_slow"], idx)
    short_trend = close < ema_trend
    short_rsi = rsi > sig_cfg["rsi_oversold"]
    short_momentum = pd.notna(momentum) and momentum < 0
    short_vwap = pd.isna(vwap) or close < vwap

    if short_cross and short_trend and short_rsi and short_momentum and short_vwap:
        conditions.append(f"EMA{sig_cfg['ema_fast']}x{sig_cfg['ema_slow']} bearish cross")
        conditions.append(f"below EMA{sig_cfg['ema_trend']} trend")
        if short_vwap and pd.notna(vwap):
            conditions.append("below VWAP")
        conditions.append(f"RSI={rsi:.1f} momentum={momentum:.2f}")
        ts = df.index[idx] if isinstance(df.index, pd.DatetimeIndex) else pd.Timestamp.now()
        return Signal(
            timestamp=ts, instrument=instrument, direction=Direction.SHORT,
            trigger_price=close, condition=" | ".join(conditions), bar_index=idx,
        )

    return None
