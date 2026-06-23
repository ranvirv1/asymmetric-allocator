"""Compare Asymmetric Allocator picks against published ChatGPT stock picks.

Loads dated ChatGPT pick lists from data/gpt_picks.csv, computes weighted returns
for each round using the same price infrastructure, and compares against what
the allocator would have held over the same periods.

Rounds with a blank end_date are treated as LIVE — returns are computed to today.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA_DIR
from .data import prices

GPT_PICKS_PATH = DATA_DIR / "gpt_picks.csv"


@dataclass
class RoundResult:
    round_id: int
    round_name: str
    source: str
    pub_date: pd.Timestamp
    end_date: pd.Timestamp
    tickers: list[str]
    weights: dict[str, float]
    gpt_return: float
    allocator_return: float | None
    spx_return: float
    gpt_per_stock: dict[str, float]
    allocator_holdings: list[str] | None
    is_live: bool = False


def load_gpt_picks() -> pd.DataFrame:
    df = pd.read_csv(GPT_PICKS_PATH)
    df["pub_date"] = pd.to_datetime(df["pub_date"])
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
    return df


def _price_at(close: pd.Series, t: pd.Timestamp) -> float | None:
    s = close[close.index <= t]
    return float(s.iloc[-1]) if len(s) else None


def _period_return(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    df = prices.history(ticker)
    if df.empty:
        return None
    c = df["close"]
    p0, p1 = _price_at(c, start), _price_at(c, end)
    if p0 and p1 and p0 > 0:
        return p1 / p0 - 1.0
    return None


def _resolve_end(end_raw) -> tuple[pd.Timestamp, bool]:
    """Return (end_date, is_live). Blank/NaT end_date means live — use today."""
    if pd.isna(end_raw):
        return pd.Timestamp.now().normalize(), True
    return pd.Timestamp(end_raw), False


def score_round(round_df: pd.DataFrame) -> RoundResult:
    """Score a single round of GPT picks vs S&P 500."""
    row0 = round_df.iloc[0]
    pub = pd.Timestamp(row0["pub_date"])
    end, is_live = _resolve_end(row0["end_date"])

    tickers = round_df["ticker"].tolist()
    weights = dict(zip(round_df["ticker"], round_df["weight"]))

    gpt_ret = 0.0
    per_stock: dict[str, float] = {}
    total_w = 0.0
    for t, w in weights.items():
        r = _period_return(t, pub, end)
        if r is not None:
            gpt_ret += w * r
            per_stock[t] = r
            total_w += w
    if total_w > 0 and total_w < 0.99:
        gpt_ret /= total_w

    spx_ret = _period_return("^SPX", pub, end) or 0.0

    return RoundResult(
        round_id=int(row0["round_id"]),
        round_name=str(row0["round_name"]),
        source=str(row0["source"]),
        pub_date=pub,
        end_date=end,
        tickers=tickers,
        weights=weights,
        gpt_return=gpt_ret,
        allocator_return=None,
        spx_return=spx_ret,
        gpt_per_stock=per_stock,
        allocator_holdings=None,
        is_live=is_live,
    )


def _allocator_return_for_period(
    pub: pd.Timestamp, end: pd.Timestamp, cfg: dict | None = None,
) -> tuple[float | None, list[str] | None]:
    """Run the allocator as-of pub_date and compute its portfolio return to end_date."""
    try:
        from . import pipeline
        result = pipeline.run_live(as_of=pub, cfg=cfg)
        rows = result["allocation_rows"]
        if rows.empty:
            return None, None

        holdings = rows["ticker"].tolist()
        port_ret = 0.0
        total_w = 0.0
        for r in rows.itertuples():
            ret = _period_return(r.ticker, pub, end)
            if ret is not None:
                port_ret += r.target_weight * ret
                total_w += r.target_weight
        if total_w > 0:
            port_ret /= total_w
        return port_ret, holdings
    except Exception:
        return None, None


def run_comparison(
    include_allocator: bool = True, cfg: dict | None = None,
) -> list[RoundResult]:
    """Score all published GPT pick rounds and optionally compare against the allocator."""
    picks = load_gpt_picks()
    results = []

    for rid, group in picks.groupby("round_id"):
        rr = score_round(group)

        if include_allocator:
            alloc_ret, alloc_hold = _allocator_return_for_period(
                rr.pub_date, rr.end_date, cfg,
            )
            rr.allocator_return = alloc_ret
            rr.allocator_holdings = alloc_hold

        results.append(rr)

    return sorted(results, key=lambda r: r.pub_date)


def summary_table(results: list[RoundResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "round": r.round_name,
            "period": f"{r.pub_date.date()} → {r.end_date.date()}",
            "live": r.is_live,
            "gpt_return": r.gpt_return,
            "allocator_return": r.allocator_return,
            "spx_return": r.spx_return,
            "gpt_vs_spx": r.gpt_return - r.spx_return,
            "alloc_vs_spx": (r.allocator_return - r.spx_return) if r.allocator_return is not None else None,
            "alloc_vs_gpt": (r.allocator_return - r.gpt_return) if r.allocator_return is not None else None,
            "gpt_picks": ", ".join(r.tickers),
            "source": r.source,
        })
    return pd.DataFrame(rows)


def cumulative_comparison(results: list[RoundResult]) -> dict[str, float]:
    """Chain the per-round returns into a cumulative growth factor for each strategy."""
    gpt_eq = 1.0
    alloc_eq = 1.0
    spx_eq = 1.0
    alloc_available = False

    for r in results:
        gpt_eq *= (1 + r.gpt_return)
        spx_eq *= (1 + r.spx_return)
        if r.allocator_return is not None:
            alloc_eq *= (1 + r.allocator_return)
            alloc_available = True

    out = {
        "gpt_cumulative": gpt_eq - 1,
        "spx_cumulative": spx_eq - 1,
    }
    if alloc_available:
        out["allocator_cumulative"] = alloc_eq - 1
    return out


def render_comparison_html(results: list[RoundResult]) -> str:
    """Render an HTML section for the dashboard showing GPT vs Allocator vs S&P."""
    if not results:
        return ""

    live_results = [r for r in results if r.is_live]
    closed_results = [r for r in results if not r.is_live]

    cumul = cumulative_comparison(results)
    has_alloc = any(r.allocator_return is not None for r in results)

    def _pct(v: float | None) -> str:
        if v is None:
            return '<span class="muted">n/a</span>'
        cls = "green" if v >= 0 else "red"
        return f'<span class="{cls}">{v * 100:+.1f}%</span>'

    def _delta(v: float | None) -> str:
        if v is None:
            return '<span class="muted">—</span>'
        cls = "green" if v >= 0 else "red"
        return f'<span class="{cls}">{v * 100:+.1f}pp</span>'

    alloc_th = "<th>allocator</th><th>alloc vs GPT</th>" if has_alloc else ""

    def _row_html(r: RoundResult) -> str:
        alloc_td = ""
        if has_alloc:
            delta = (r.allocator_return - r.gpt_return) if r.allocator_return is not None else None
            alloc_td = f"<td>{_pct(r.allocator_return)}</td><td>{_delta(delta)}</td>"

        best_stock = max(r.gpt_per_stock.items(), key=lambda x: x[1]) if r.gpt_per_stock else ("—", 0)
        worst_stock = min(r.gpt_per_stock.items(), key=lambda x: x[1]) if r.gpt_per_stock else ("—", 0)

        live_badge = ' <span class="green" style="font-size:9px">&#9679; LIVE</span>' if r.is_live else ""
        end_label = "today" if r.is_live else str(r.end_date.date())
        days = (r.end_date - r.pub_date).days

        return (
            f'<tr>'
            f'<td class="l" style="font-size:11px">{r.round_name}{live_badge}</td>'
            f'<td class="muted" style="font-size:11px">{r.pub_date.date()} &rarr; {end_label}'
            f' <span style="font-size:9px">({days}d)</span></td>'
            f'<td>{_pct(r.gpt_return)}</td>'
            f'<td>{_pct(r.spx_return)}</td>'
            f'<td>{_delta(r.gpt_return - r.spx_return)}</td>'
            f'{alloc_td}'
            f'<td class="l muted" style="font-size:10px">'
            f'best: {best_stock[0]} {best_stock[1]*100:+.0f}% / worst: {worst_stock[0]} {worst_stock[1]*100:+.0f}%</td>'
            f'</tr>'
        )

    rows_html = [_row_html(r) for r in results]

    alloc_summary = ""
    if "allocator_cumulative" in cumul:
        alloc_summary = (
            f' &middot; Allocator <b>{_pct(cumul["allocator_cumulative"])}</b>'
            f' ({_delta(cumul["allocator_cumulative"] - cumul["gpt_cumulative"])} vs GPT)'
        )

    live_count = len(live_results)
    live_note = f' &middot; <span class="green">{live_count} live</span>' if live_count else ""

    source_text = (
        'Source: published ChatGPT picks from Finbold / Quartz (equal or stated weights), '
        'plus your own forward picks logged via <span class="muted">log_gpt_picks.py</span>. '
        'Returns are total price return, no dividends. Not a controlled experiment &mdash; '
        'ChatGPT picks vary by prompt, date, and model version.'
    )

    return (
        '<h2>ChatGPT picks vs Asymmetric Allocator</h2>'
        f'<div class="edge" style="margin-bottom:8px">'
        f'Cumulative (chained): ChatGPT {_pct(cumul["gpt_cumulative"])}'
        f' &middot; S&amp;P 500 {_pct(cumul["spx_cumulative"])}'
        f'{alloc_summary}{live_note}'
        f'</div>'
        f'<table><tr>'
        f'<th class="l">round</th><th class="l">period</th>'
        f'<th>GPT return</th><th>S&amp;P 500</th><th>GPT vs S&amp;P</th>'
        f'{alloc_th}'
        f'<th class="l">stock detail</th>'
        f'</tr>'
        + "".join(rows_html)
        + '</table>'
        f'<div class="edge" style="margin-top:6px">{source_text}</div>'
    )


# ---------------------------------------------------------------------------
# CLI helper: log new GPT picks to the CSV
# ---------------------------------------------------------------------------

def log_picks(
    tickers: list[str],
    weights: list[float] | None = None,
    name: str | None = None,
    pub_date: str | None = None,
) -> dict:
    """Append a new round of GPT picks to gpt_picks.csv.

    Args:
        tickers:  list of ticker symbols, e.g. ["NVDA", "AAPL", "MSFT"]
        weights:  optional list of weights (same length as tickers). Defaults to equal.
        name:     round label, e.g. "ChatGPT Jul 2026". Auto-generated if omitted.
        pub_date: YYYY-MM-DD string. Defaults to today.

    Returns:
        dict with round_id, name, pub_date, tickers, weights.
    """
    tickers = [t.strip().upper() for t in tickers]
    n = len(tickers)
    if weights is None:
        weights = [round(1.0 / n, 4)] * n
    if len(weights) != n:
        raise ValueError(f"Got {n} tickers but {len(weights)} weights")
    wsum = sum(weights)
    if abs(wsum - 1.0) > 0.02:
        raise ValueError(f"Weights sum to {wsum:.3f}, expected ~1.0")

    today = pd.Timestamp.now().normalize()
    pub = pd.Timestamp(pub_date) if pub_date else today

    existing = load_gpt_picks()
    next_id = int(existing["round_id"].max()) + 1 if not existing.empty else 1

    if name is None:
        name = f"ChatGPT {pub.strftime('%b %Y')}"

    rows = []
    for ticker, weight in zip(tickers, weights):
        rows.append({
            "round_id": next_id,
            "round_name": name,
            "source": "manual",
            "pub_date": str(pub.date()),
            "end_date": "",
            "ticker": ticker,
            "weight": weight,
        })

    with open(GPT_PICKS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["round_id", "round_name", "source",
                                                "pub_date", "end_date", "ticker", "weight"])
        for row in rows:
            writer.writerow(row)

    return {
        "round_id": next_id,
        "name": name,
        "pub_date": str(pub.date()),
        "tickers": tickers,
        "weights": weights,
    }


def close_round(round_id: int, end_date: str | None = None) -> None:
    """Close a live round by setting its end_date (defaults to today)."""
    end = end_date or str(pd.Timestamp.now().normalize().date())
    df = load_gpt_picks()
    mask = df["round_id"] == round_id
    if not mask.any():
        raise ValueError(f"No round with id {round_id}")
    df.loc[mask, "end_date"] = end
    df.to_csv(GPT_PICKS_PATH, index=False)
