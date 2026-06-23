"""M8 — Walk-forward backtester (the whole point: signal vs hindsight, spec §3/§6/§8.4).

Monthly rebalance, point-in-time at every step: at date t we build the universe, regime,
and scores using ONLY data timestamped <= t, hold to t+1, and charge transaction costs.

This is the go/no-go gate (§8.4): if ERM+RS alone don't beat the S&P out-of-sample, stop and
rethink rather than piling on factors. The ablation suite measures what each rule is worth.

Honesty protocol (§6) enforced here:
  - delisted names are in the universe (survivorship) — results are an UPPER BOUND, banner printed.
  - metrics lead with MEDIAN + MAX DRAWDOWN, not mean.
  - ERM uses point-in-time dated grade actions; deep-history ERM coverage is partial (RS-only
    is the fully-clean baseline). RS is point-in-time clean from prices.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import regime, scoring, universe
from .config import load_config
from .data import prices

INDEX = "^SPX"
TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# Strategy definitions (the ablation suite)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Strategy:
    name: str
    active: tuple[str, ...]   # sub-scores used, e.g. ("RS",) or ("ERM", "RS")
    top_n: int = 15
    weighting: str = "score"  # "score" | "equal"
    use_regime: bool = True   # apply regime budget (cash sleeve + COMPRESSION de-risk)


def default_suite() -> list[Strategy]:
    return [
        Strategy("ERM+RS (regime)", ("ERM", "RS"), use_regime=True),
        Strategy("RS-only (regime)", ("RS",), use_regime=True),
        Strategy("ERM+RS (no regime)", ("ERM", "RS"), use_regime=False),
        Strategy("RS equal-wt (no regime)", ("RS",), weighting="equal", use_regime=False),
    ]


def rs_suite() -> list[Strategy]:
    """RS-only ablations — no FMP calls (use when ERM grade data isn't available / quota-blocked).
    Isolates the regime-gate and weighting effects on the price signal alone."""
    return [
        Strategy("RS-only (regime)", ("RS",), use_regime=True),
        Strategy("RS-only (no regime)", ("RS",), use_regime=False),
        Strategy("RS equal-wt (no regime)", ("RS",), weighting="equal", use_regime=False),
    ]


# ---------------------------------------------------------------------------
# Date / price helpers
# ---------------------------------------------------------------------------

def rebalance_dates(start: str, end: str) -> list[pd.Timestamp]:
    """Month-end dates snapped to the last S&P trading day on/before each month-end."""
    idx = prices.fetch_ohlcv(INDEX, start=start, end=end)
    if idx.empty:
        return []
    trading = idx.index
    out = []
    for me in pd.date_range(start, end, freq="ME"):
        prior = trading[trading <= me]
        if len(prior):
            out.append(prior[-1])
    return sorted(set(out))


def _price_at(close: pd.Series, t: pd.Timestamp) -> float | None:
    s = close[close.index <= t]
    return float(s.iloc[-1]) if len(s) else None


# ---------------------------------------------------------------------------
# Portfolio construction at a single rebalance date
# ---------------------------------------------------------------------------

def target_weights(
    as_of: pd.Timestamp, tickers: list[str], strat: Strategy, cfg: dict, verdict: str, budget: dict
) -> pd.Series:
    scored = scoring.score_universe(as_of, tickers, verdict, cfg, active=strat.active)
    if scored.empty:
        return pd.Series(dtype=float)
    top = scored.head(strat.top_n)
    if strat.weighting == "score":
        raw = top["winner_score"].clip(lower=0.0)
        w = raw / raw.sum() if raw.sum() > 0 else pd.Series(1.0 / len(top), index=top.index)
    else:
        w = pd.Series(1.0 / len(top), index=top.index)

    cap = cfg["caps"]["anchor_max"]                # hard per-name cap (20%)
    w = w.clip(upper=cap)
    w = w / w.sum()                                # renormalise within equity sleeve

    equity_frac = 1.0
    if strat.use_regime:                           # rest of book sits in cash
        equity_frac = float(budget["anchor"]) + float(budget["satellite"])
    return (w * equity_frac).rename(None)


# ---------------------------------------------------------------------------
# Run one strategy over the walk-forward
# ---------------------------------------------------------------------------

def run_strategy(
    strat: Strategy,
    dates: list[pd.Timestamp],
    cfg: dict,
    tickers_by_date: dict[pd.Timestamp, list[str]],
    regimes: dict[pd.Timestamp, "regime.RegimeResult"],
    closes: dict[str, pd.Series],
) -> dict:
    costs = cfg.get("costs_bps", 8) / 1e4
    equity = 1.0
    eq_curve = {dates[0]: equity}
    period_rets: list[float] = []
    turnovers: list[float] = []
    weights_by_date: dict[pd.Timestamp, pd.Series] = {}
    prev_w = pd.Series(dtype=float)

    for i in range(len(dates) - 1):
        t, t_next = dates[i], dates[i + 1]
        reg = regimes[t]
        w = target_weights(t, tickers_by_date[t], strat, cfg, reg.verdict, reg.budget)
        weights_by_date[t] = w

        # turnover vs last period's target (two-way), charged as cost
        all_names = prev_w.index.union(w.index)
        turn = float((w.reindex(all_names, fill_value=0) - prev_w.reindex(all_names, fill_value=0)).abs().sum())
        turnovers.append(turn)

        # realised holding-period return, point-in-time from prices
        port_ret = 0.0
        for tkr, wt in w.items():
            s = closes.get(tkr)
            if s is None:
                continue
            p0, p1 = _price_at(s, t), _price_at(s, t_next)
            if p0 and p1 and p0 > 0:
                port_ret += wt * (p1 / p0 - 1.0)
        port_ret -= turn * costs

        equity *= (1.0 + port_ret)
        eq_curve[t_next] = equity
        period_rets.append(port_ret)
        prev_w = w

    eq = pd.Series(eq_curve).sort_index()
    rets = pd.Series(period_rets, index=dates[1:len(period_rets) + 1])
    return {
        "strategy": strat,
        "equity": eq,
        "returns": rets,
        "avg_turnover": float(np.mean(turnovers)) if turnovers else 0.0,
        "weights_by_date": weights_by_date,
    }


def benchmark(dates: list[pd.Timestamp], closes: dict[str, pd.Series]) -> dict:
    spx = closes[INDEX]
    eq = {}
    base = _price_at(spx, dates[0])
    for d in dates:
        p = _price_at(spx, d)
        eq[d] = (p / base) if (p and base) else np.nan
    eqs = pd.Series(eq).sort_index()
    return {"strategy": Strategy("S&P 500 (buy & hold)", ()), "equity": eqs,
            "returns": eqs.pct_change().dropna(), "avg_turnover": 0.0, "weights_by_date": {}}


# ---------------------------------------------------------------------------
# Metrics — median + max drawdown FIRST (spec §6)
# ---------------------------------------------------------------------------

def metrics(eq: pd.Series, rets: pd.Series, periods_per_year: int = 12) -> dict:
    eq = eq.dropna()
    if len(eq) < 2:
        return {}
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1.0
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1.0 if years > 0 else np.nan

    roll_max = eq.cummax()
    max_dd = float((eq / roll_max - 1.0).min())

    annual = eq.resample("YE").last().pct_change().dropna()
    downside = rets[rets < 0]
    sortino = (rets.mean() / downside.std() * np.sqrt(periods_per_year)) if len(downside) and downside.std() else np.nan
    sharpe = (rets.mean() / rets.std() * np.sqrt(periods_per_year)) if rets.std() else np.nan

    return {
        "median_annual": float(annual.median()) if len(annual) else np.nan,
        "max_drawdown": max_dd,
        "cagr": float(cagr),
        "mean_annual": float(annual.mean()) if len(annual) else np.nan,
        "total_return": float(total),
        "vol_annual": float(rets.std() * np.sqrt(periods_per_year)),
        "sortino": float(sortino) if sortino == sortino else np.nan,
        "sharpe": float(sharpe) if sharpe == sharpe else np.nan,
        "hit_rate": float((rets > 0).mean()),
        "annual_returns": annual,
    }


def catch_rate(result: dict, dates: list[pd.Timestamp], closes: dict[str, pd.Series],
               tickers_by_date: dict, top_k: int = 10) -> pd.DataFrame:
    """Of each year's actual top-`top_k` performers, how many did the strategy already HOLD
    at that year's first rebalance — i.e. before the move (spec §3 catch-rate test)."""
    wbd = result["weights_by_date"]
    rows = []
    for year in sorted({d.year for d in dates}):
        ydates = [d for d in dates if d.year == year]
        if len(ydates) < 2:
            continue
        t0, t1 = ydates[0], ydates[-1]
        univ = tickers_by_date.get(t0, [])
        perf = {}
        for tkr in univ:
            s = closes.get(tkr)
            if s is None:
                continue
            p0, p1 = _price_at(s, t0), _price_at(s, t1)
            if p0 and p1 and p0 > 0:
                perf[tkr] = p1 / p0 - 1.0
        if not perf:
            continue
        winners = [t for t, _ in sorted(perf.items(), key=lambda kv: kv[1], reverse=True)[:top_k]]
        held = set(wbd.get(t0, pd.Series(dtype=float)).index)
        caught = [w for w in winners if w in held]
        rows.append({"year": year, "caught": len(caught), "of": len(winners),
                     "catch_rate": len(caught) / len(winners), "names": ",".join(caught)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def caveat_banner(survivorship_note: str) -> str:
    return (
        "\n" + "!" * 72 + "\n"
        "HONESTY BANNER (spec §6/§7):\n"
        "  * Universe = seed + delisted overlay, NOT true point-in-time membership →\n"
        "    SURVIVORSHIP BIAS remains; treat returns as an UPPER BOUND.\n"
        "  * RS is point-in-time clean (prices). ERM uses dated grade actions (point-in-time)\n"
        "    but coverage is partial pre-2023 → RS-only is the fully-clean baseline.\n"
        "  * Costs " + "modelled; cash sleeve earns 0% (conservative). Not financial advice.\n"
        + "!" * 72
    )


def run_suite(cfg: dict | None = None, suite: list[Strategy] | None = None) -> dict:
    cfg = cfg or load_config()
    bt = cfg["backtest"]
    suite = suite or default_suite()
    dates = rebalance_dates(bt["start"], bt["end"])
    if len(dates) < 6:
        raise RuntimeError("Not enough rebalance dates / price data for the backtest window.")

    # Preload all candidate closes once (in-memory), incl. the index.
    cand = set([INDEX])
    for d in dates:
        cand |= set(universe.candidate_set(d)["ticker"])
    closes: dict[str, pd.Series] = {}
    for tkr in cand:
        h = prices.history(tkr)
        if not h.empty:
            closes[tkr] = h["close"]

    # Build universe + regime once per date (shared across strategies).
    tickers_by_date: dict[pd.Timestamp, list[str]] = {}
    regimes: dict[pd.Timestamp, regime.RegimeResult] = {}
    for d in dates:
        u = universe.build_universe(d, cfg, with_mktcap=False)
        tk = u.members["ticker"].tolist()
        tickers_by_date[d] = tk
        regimes[d] = regime.compute_regime(d, cfg, breadth_tickers=tk)

    results = {bench["strategy"].name: bench for bench in [benchmark(dates, closes)]}
    for strat in suite:
        results[strat.name] = run_strategy(strat, dates, cfg, tickers_by_date, regimes, closes)

    return {"dates": dates, "results": results, "closes": closes,
            "tickers_by_date": tickers_by_date, "regimes": regimes, "cfg": cfg}
