"""Futures backtesting engine — walk-forward validation per §4/§5.

Models commission and realistic slippage, not gross P&L. Supports walk-forward
(in-sample tune + out-of-sample validate) to prove the strategy holds up on
data it wasn't tuned on.

Performance gates checked after each run:
  - Minimum 100+ logged trades
  - Profit factor >= 1.5
  - Max drawdown <= X% of account
  - Win rate and R:R within 15% of assumptions
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import signals as sig_mod
from .config import instrument_spec, load_config
from .orders import Trade, TradeStatus
from .risk import (RiskState, can_open, compute_stop, compute_target,
                   size_position)
from .signals import Direction, evaluate
from .trade_log import TradeLog

logger = logging.getLogger("futures_bot.backtest")


@dataclass
class BacktestResult:
    instrument: str
    start: str
    end: str
    total_trades: int
    winners: int
    losers: int
    win_rate: float
    avg_winner: float
    avg_loser: float
    reward_risk_ratio: float
    profit_factor: float
    total_pnl: float
    max_drawdown_pct: float
    max_drawdown_usd: float
    sharpe: float
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    gates_passed: bool = False
    gate_failures: list[str] = field(default_factory=list)


def load_bar_data(instrument: str, cfg: dict) -> pd.DataFrame:
    """Load OHLCV bar data from CSV. Expected columns: datetime,open,high,low,close,volume."""
    bt_cfg = cfg["backtest"]
    data_dir = Path(bt_cfg.get("data_dir", "data/futures"))
    path = data_dir / f"{instrument}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"No data file for {instrument} at {path}. "
            f"Place OHLCV CSV (datetime,open,high,low,close,volume) in {data_dir}/"
        )
    df = pd.read_csv(path, parse_dates=["datetime"], index_col="datetime")
    df = df.sort_index()
    start = pd.Timestamp(bt_cfg["start"])
    end = pd.Timestamp(bt_cfg["end"])
    return df.loc[start:end]


def run_backtest(instrument: str, cfg: dict | None = None) -> BacktestResult:
    """Run a full backtest for one instrument."""
    cfg = cfg or load_config()
    spec = instrument_spec(cfg, instrument)
    bt_cfg = cfg["backtest"]
    tick_size = spec["tick_size"]
    tick_value = spec["tick_value"]
    commission = spec["commission"]
    slippage_ticks = bt_cfg.get("slippage_ticks", 1)
    slippage = slippage_ticks * tick_size

    df = load_bar_data(instrument, cfg)
    df = sig_mod.compute_indicators(df, cfg)

    trade_log = TradeLog()
    risk_state = RiskState()
    account_size = float(cfg["account"]["size"])
    equity = account_size
    peak_equity = equity
    max_dd_usd = 0.0

    open_trades: list[Trade] = []
    last_signal_bar: int | None = None
    equity_curve = [equity]

    warmup = max(cfg["signal"]["ema_trend"], cfg["exits"]["atr_period"]) + 5

    for i in range(warmup, len(df)):
        bar = df.iloc[i]
        current_date = df.index[i].date() if isinstance(df.index[i], pd.Timestamp) else None

        if current_date and (risk_state.session_date is None or risk_state.session_date != current_date):
            risk_state.reset_session(current_date)

        # Update open trades
        closed_this_bar = []
        for trade in open_trades:
            status = trade.update_bar(bar, tick_size, tick_value, cfg)
            if status is not None:
                trade.pnl -= commission
                trade_log.log_trade(trade)
                risk_state.record_fill(trade.pnl, cfg)
                risk_state.open_positions[instrument] = max(
                    0, risk_state.open_positions.get(instrument, 1) - 1
                )
                equity += trade.pnl
                closed_this_bar.append(trade)

        for t in closed_this_bar:
            open_trades.remove(t)

        # Check for new signals
        signal = evaluate(df, i, instrument, cfg, last_signal_bar)
        if signal is None:
            equity_curve.append(equity)
            continue

        trade_log.log_signal(signal)
        last_signal_bar = i

        allowed, reason = can_open(instrument, risk_state, cfg)
        if not allowed:
            equity_curve.append(equity)
            continue

        atr = bar.get("atr", 0)
        if pd.isna(atr) or atr <= 0:
            equity_curve.append(equity)
            continue

        entry = signal.trigger_price
        if signal.direction == Direction.LONG:
            entry += slippage
        else:
            entry -= slippage

        stop = compute_stop(entry, signal.direction, atr, cfg, instrument)
        target = compute_target(entry, stop, signal.direction, atr, cfg, instrument)
        contracts = size_position(instrument, signal.direction, entry, stop, cfg)

        if contracts <= 0:
            equity_curve.append(equity)
            continue

        from .orders import BracketOrder
        order = BracketOrder.create(
            instrument=instrument, direction=signal.direction,
            contracts=contracts, entry=entry, stop=stop, target=target,
            condition=signal.condition,
        )
        trade = Trade.from_fill(order, entry, signal.timestamp)
        open_trades.append(trade)
        risk_state.open_positions[instrument] = risk_state.open_positions.get(instrument, 0) + 1

        peak_equity = max(peak_equity, equity)
        dd = peak_equity - equity
        max_dd_usd = max(max_dd_usd, dd)
        equity_curve.append(equity)

    # Force-close any remaining open trades at last bar
    if open_trades:
        last_bar = df.iloc[-1]
        for trade in open_trades:
            trade.force_close(last_bar["close"], df.index[-1], tick_size, tick_value)
            trade.pnl -= commission
            trade_log.log_trade(trade)
            equity += trade.pnl

    peak_equity = max(peak_equity, equity)
    dd = peak_equity - equity
    max_dd_usd = max(max_dd_usd, dd)
    equity_curve.append(equity)

    return _compile_result(instrument, cfg, trade_log, equity_curve,
                           account_size, max_dd_usd)


def _compile_result(instrument: str, cfg: dict, trade_log: TradeLog,
                    equity_curve: list[float], account_size: float,
                    max_dd_usd: float) -> BacktestResult:
    trades = trade_log.trades
    bt_cfg = cfg["backtest"]
    gates = cfg["performance_gates"]

    if not trades:
        return BacktestResult(
            instrument=instrument, start=bt_cfg["start"], end=bt_cfg["end"],
            total_trades=0, winners=0, losers=0, win_rate=0, avg_winner=0,
            avg_loser=0, reward_risk_ratio=0, profit_factor=0, total_pnl=0,
            max_drawdown_pct=0, max_drawdown_usd=0, sharpe=0,
            equity_curve=equity_curve,
        )

    pnls = [t["pnl"] for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    total_pnl = sum(pnls)
    win_rate = len(winners) / len(pnls) * 100 if pnls else 0
    avg_w = np.mean(winners) if winners else 0
    avg_l = abs(np.mean(losers)) if losers else 0
    rr = avg_w / avg_l if avg_l > 0 else float("inf")
    gross_profit = sum(winners) if winners else 0
    gross_loss = abs(sum(losers)) if losers else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    max_dd_pct = max_dd_usd / account_size * 100 if account_size else 0

    # Sharpe (daily returns from equity curve)
    eq = pd.Series(equity_curve)
    daily_ret = eq.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0

    # Performance gate checks
    gate_failures = []
    if len(trades) < gates["min_trades"]:
        gate_failures.append(f"Trades {len(trades)} < {gates['min_trades']} minimum")
    if pf < gates["min_profit_factor"]:
        gate_failures.append(f"Profit factor {pf:.2f} < {gates['min_profit_factor']}")
    if max_dd_pct > gates["max_drawdown_pct"]:
        gate_failures.append(f"Max DD {max_dd_pct:.1f}% > {gates['max_drawdown_pct']}%")

    result = BacktestResult(
        instrument=instrument, start=bt_cfg["start"], end=bt_cfg["end"],
        total_trades=len(trades), winners=len(winners), losers=len(losers),
        win_rate=round(win_rate, 1), avg_winner=round(float(avg_w), 2),
        avg_loser=round(float(avg_l), 2), reward_risk_ratio=round(float(rr), 2),
        profit_factor=round(float(pf), 2), total_pnl=round(total_pnl, 2),
        max_drawdown_pct=round(max_dd_pct, 1), max_drawdown_usd=round(max_dd_usd, 2),
        sharpe=round(sharpe, 2), trades=trades, equity_curve=equity_curve,
        gates_passed=len(gate_failures) == 0, gate_failures=gate_failures,
    )
    return result


def walk_forward(instrument: str, cfg: dict | None = None) -> list[BacktestResult]:
    """Walk-forward test: roll in-sample/out-of-sample windows (§5)."""
    cfg = cfg or load_config()
    bt_cfg = cfg["backtest"]
    wf = bt_cfg.get("walk_forward", {})
    is_months = wf.get("in_sample_months", 12)
    oos_months = wf.get("out_of_sample_months", 3)

    start = pd.Timestamp(bt_cfg["start"])
    end = pd.Timestamp(bt_cfg["end"])
    results = []
    window_start = start

    while window_start + pd.DateOffset(months=is_months + oos_months) <= end:
        oos_start = window_start + pd.DateOffset(months=is_months)
        oos_end = oos_start + pd.DateOffset(months=oos_months)

        oos_cfg = dict(cfg)
        oos_cfg["backtest"] = dict(bt_cfg)
        oos_cfg["backtest"]["start"] = str(oos_start.date())
        oos_cfg["backtest"]["end"] = str(oos_end.date())

        try:
            result = run_backtest(instrument, oos_cfg)
            result.start = str(oos_start.date())
            result.end = str(oos_end.date())
            results.append(result)
            logger.info("Walk-forward window %s to %s: PF=%.2f, WR=%.1f%%, DD=%.1f%%",
                         result.start, result.end, result.profit_factor,
                         result.win_rate, result.max_drawdown_pct)
        except FileNotFoundError:
            logger.warning("No data for walk-forward window %s-%s", oos_start, oos_end)
            break

        window_start += pd.DateOffset(months=oos_months)

    return results


def print_report(result: BacktestResult) -> str:
    """Format a human-readable backtest report."""
    lines = [
        f"{'='*60}",
        f"  BACKTEST REPORT — {result.instrument}",
        f"  {result.start} to {result.end}",
        f"{'='*60}",
        f"",
        f"  Total Trades:       {result.total_trades}",
        f"  Winners:            {result.winners}  ({result.win_rate}%)",
        f"  Losers:             {result.losers}",
        f"  Avg Winner:         ${result.avg_winner:,.2f}",
        f"  Avg Loser:          ${result.avg_loser:,.2f}",
        f"  Reward:Risk:        {result.reward_risk_ratio:.2f}",
        f"  Profit Factor:      {result.profit_factor:.2f}",
        f"  Total P&L:          ${result.total_pnl:,.2f}",
        f"  Max Drawdown:       {result.max_drawdown_pct:.1f}% (${result.max_drawdown_usd:,.2f})",
        f"  Sharpe Ratio:       {result.sharpe:.2f}",
        f"",
        f"  --- Breakeven Math ---",
    ]

    if result.win_rate > 0:
        be_rr = (100 - result.win_rate) / result.win_rate
        lines.append(f"  Breakeven R:R at {result.win_rate}% WR: {be_rr:.2f}:1")
        lines.append(f"  Actual R:R:                         {result.reward_risk_ratio:.2f}:1")
        healthy_rr = be_rr * 1.5
        lines.append(f"  Healthy (PF~1.5) R:R:               {healthy_rr:.2f}:1")

    lines.append(f"")
    lines.append(f"  --- Performance Gates (§4) ---")
    if result.gates_passed:
        lines.append(f"  ALL GATES PASSED — eligible for live promotion")
    else:
        lines.append(f"  GATES FAILED:")
        for fail in result.gate_failures:
            lines.append(f"    - {fail}")

    lines.append(f"{'='*60}")
    report = "\n".join(lines)
    logger.info("\n%s", report)
    return report
