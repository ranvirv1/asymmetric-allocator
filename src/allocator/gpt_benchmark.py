"""Compare AI stock picks: Claude vs ChatGPT vs S&P 500.

Loads dated pick lists from data/ai_picks.csv (model column: "chatgpt" or "claude"),
computes weighted returns using the same price infrastructure, and renders a
head-to-head comparison on the dashboard.

Rounds with a blank end_date are LIVE — returns computed to today.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass

import pandas as pd

from .config import DATA_DIR
from .data import prices

PICKS_PATH = DATA_DIR / "ai_picks.csv"
GPT_PICKS_PATH = PICKS_PATH  # back-compat alias


@dataclass
class RoundResult:
    round_id: int
    model: str
    round_name: str
    source: str
    pub_date: pd.Timestamp
    end_date: pd.Timestamp
    tickers: list[str]
    weights: dict[str, float]
    portfolio_return: float
    spx_return: float
    per_stock: dict[str, float]
    is_live: bool = False


def load_picks(model: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(PICKS_PATH)
    df["pub_date"] = pd.to_datetime(df["pub_date"])
    df["end_date"] = pd.to_datetime(df["end_date"], errors="coerce")
    if "model" not in df.columns:
        df["model"] = "chatgpt"
    if model:
        df = df[df["model"] == model]
    return df


load_gpt_picks = load_picks  # back-compat


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
    if pd.isna(end_raw):
        return pd.Timestamp.now().normalize(), True
    return pd.Timestamp(end_raw), False


def score_round(round_df: pd.DataFrame) -> RoundResult:
    row0 = round_df.iloc[0]
    pub = pd.Timestamp(row0["pub_date"])
    end, is_live = _resolve_end(row0["end_date"])

    tickers = round_df["ticker"].tolist()
    weights = dict(zip(round_df["ticker"], round_df["weight"]))

    port_ret = 0.0
    per_stock: dict[str, float] = {}
    total_w = 0.0
    for t, w in weights.items():
        r = _period_return(t, pub, end)
        if r is not None:
            port_ret += w * r
            per_stock[t] = r
            total_w += w
    if total_w > 0 and total_w < 0.99:
        port_ret /= total_w

    spx_ret = _period_return("^SPX", pub, end) or 0.0

    return RoundResult(
        round_id=int(row0["round_id"]),
        model=str(row0.get("model", "chatgpt")),
        round_name=str(row0["round_name"]),
        source=str(row0["source"]),
        pub_date=pub,
        end_date=end,
        tickers=tickers,
        weights=weights,
        portfolio_return=port_ret,
        spx_return=spx_ret,
        per_stock=per_stock,
        is_live=is_live,
    )


def run_comparison(
    model: str | None = None, include_allocator: bool = False, cfg: dict | None = None,
) -> list[RoundResult]:
    """Score all pick rounds, optionally filtered by model."""
    picks = load_picks(model)
    results = []
    for rid, group in picks.groupby("round_id"):
        results.append(score_round(group))
    return sorted(results, key=lambda r: r.pub_date)


def summary_table(results: list[RoundResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        rows.append({
            "model": r.model,
            "round": r.round_name,
            "period": f"{r.pub_date.date()} -> {r.end_date.date()}",
            "live": r.is_live,
            "return": r.portfolio_return,
            "spx_return": r.spx_return,
            "vs_spx": r.portfolio_return - r.spx_return,
            "picks": ", ".join(r.tickers),
            "source": r.source,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Head-to-head: pair Claude and GPT rounds that share the same pub_date
# ---------------------------------------------------------------------------

@dataclass
class MatchupResult:
    pub_date: pd.Timestamp
    end_date: pd.Timestamp
    is_live: bool
    days: int
    claude: RoundResult | None
    chatgpt: RoundResult | None
    spx_return: float
    claude_return: float | None
    chatgpt_return: float | None


def pair_rounds(results: list[RoundResult]) -> list[MatchupResult]:
    """Group rounds by pub_date and pair Claude vs GPT for head-to-head."""
    by_date: dict[str, dict[str, RoundResult]] = {}
    for r in results:
        key = str(r.pub_date.date())
        by_date.setdefault(key, {})[r.model] = r

    matchups = []
    for key in sorted(by_date):
        group = by_date[key]
        claude = group.get("claude")
        gpt = group.get("chatgpt")
        ref = claude or gpt
        matchups.append(MatchupResult(
            pub_date=ref.pub_date,
            end_date=ref.end_date,
            is_live=ref.is_live,
            days=(ref.end_date - ref.pub_date).days,
            claude=claude,
            chatgpt=gpt,
            spx_return=ref.spx_return,
            claude_return=claude.portfolio_return if claude else None,
            chatgpt_return=gpt.portfolio_return if gpt else None,
        ))
    return matchups


def render_comparison_html(results: list[RoundResult]) -> str:
    """Render an HTML section: Claude vs GPT vs S&P head-to-head."""
    if not results:
        return ""

    has_claude = any(r.model == "claude" for r in results)
    has_gpt = any(r.model == "chatgpt" for r in results)
    matchups = pair_rounds(results) if (has_claude and has_gpt) else []

    def _pct(v: float | None) -> str:
        if v is None:
            return '<span class="muted">n/a</span>'
        cls = "green" if v >= 0 else "red"
        return f'<span class="{cls}">{v * 100:+.1f}%</span>'

    def _delta(v: float | None) -> str:
        if v is None:
            return '<span class="muted">-</span>'
        cls = "green" if v >= 0 else "red"
        return f'<span class="{cls}">{v * 100:+.1f}pp</span>'

    # If we have matchups (both models), render head-to-head table
    if matchups:
        return _render_head_to_head(matchups, results, _pct, _delta)

    # Otherwise render single-model table (original style)
    return _render_single_model(results, _pct, _delta)


def _render_head_to_head(matchups, results, _pct, _delta) -> str:
    claude_results = [r for r in results if r.model == "claude"]
    gpt_results = [r for r in results if r.model == "chatgpt"]

    def _cumul(rs):
        eq = 1.0
        for r in sorted(rs, key=lambda x: x.pub_date):
            eq *= (1 + r.portfolio_return)
        return eq - 1

    claude_cum = _cumul(claude_results) if claude_results else None
    gpt_cum = _cumul(gpt_results) if gpt_results else None
    spx_cum = _cumul(gpt_results)  # SPX same for both

    live_count = sum(1 for m in matchups if m.is_live)

    rows_html = []
    claude_wins = gpt_wins = 0
    for m in matchups:
        live_badge = ' <span class="green" style="font-size:9px">&#9679; LIVE</span>' if m.is_live else ""
        end_label = "today" if m.is_live else str(m.end_date.date())

        # Determine winner
        winner = ""
        if m.claude_return is not None and m.chatgpt_return is not None:
            diff = m.claude_return - m.chatgpt_return
            if diff > 0.001:
                winner = '<span class="blue">Claude</span>'
                claude_wins += 1
            elif diff < -0.001:
                winner = '<span class="amber">GPT</span>'
                gpt_wins += 1
            else:
                winner = '<span class="muted">tie</span>'

        # Stock detail for whichever side exists
        detail_parts = []
        if m.claude and m.claude.per_stock:
            best = max(m.claude.per_stock.items(), key=lambda x: x[1])
            detail_parts.append(f'C best: {best[0]} {best[1]*100:+.0f}%')
        if m.chatgpt and m.chatgpt.per_stock:
            best = max(m.chatgpt.per_stock.items(), key=lambda x: x[1])
            detail_parts.append(f'G best: {best[0]} {best[1]*100:+.0f}%')

        claude_name = m.claude.round_name if m.claude else ""
        gpt_name = m.chatgpt.round_name if m.chatgpt else ""
        label = claude_name or gpt_name

        rows_html.append(
            f'<tr>'
            f'<td class="muted" style="font-size:11px">{m.pub_date.date()} &rarr; {end_label}'
            f' <span style="font-size:9px">({m.days}d)</span>{live_badge}</td>'
            f'<td>{_pct(m.claude_return)}</td>'
            f'<td>{_pct(m.chatgpt_return)}</td>'
            f'<td>{_pct(m.spx_return)}</td>'
            f'<td>{winner}</td>'
            f'<td class="l muted" style="font-size:10px">{" / ".join(detail_parts)}</td>'
            f'</tr>'
        )

    # Unmatched rounds (only one model has picks for that date)
    matched_dates = {str(m.pub_date.date()) for m in matchups}
    unmatched = [r for r in results if str(r.pub_date.date()) not in matched_dates]
    for r in sorted(unmatched, key=lambda x: x.pub_date):
        live_badge = ' <span class="green" style="font-size:9px">&#9679; LIVE</span>' if r.is_live else ""
        end_label = "today" if r.is_live else str(r.end_date.date())
        days = (r.end_date - r.pub_date).days
        model_label = "Claude" if r.model == "claude" else "GPT"
        c_val = _pct(r.portfolio_return) if r.model == "claude" else '<span class="muted">-</span>'
        g_val = _pct(r.portfolio_return) if r.model == "chatgpt" else '<span class="muted">-</span>'

        rows_html.append(
            f'<tr>'
            f'<td class="muted" style="font-size:11px">{r.pub_date.date()} &rarr; {end_label}'
            f' <span style="font-size:9px">({days}d)</span>{live_badge}</td>'
            f'<td>{c_val}</td>'
            f'<td>{g_val}</td>'
            f'<td>{_pct(r.spx_return)}</td>'
            f'<td class="muted" style="font-size:10px">{model_label} only</td>'
            f'<td class="l muted" style="font-size:10px">{r.round_name}</td>'
            f'</tr>'
        )

    live_note = f' &middot; <span class="green">{live_count} live</span>' if live_count else ""
    record = f'Claude {claude_wins} &ndash; {gpt_wins} GPT' if (claude_wins + gpt_wins) else ""

    return (
        '<h2>Claude vs ChatGPT &mdash; AI stock pick showdown</h2>'
        f'<div class="edge" style="margin-bottom:8px">'
        f'Cumulative: <span class="blue">Claude</span> {_pct(claude_cum)}'
        f' &middot; <span class="amber">ChatGPT</span> {_pct(gpt_cum)}'
        f' &middot; S&amp;P 500 {_pct(spx_cum)}'
        f'{" &middot; Record: " + record if record else ""}'
        f'{live_note}'
        f'</div>'
        f'<table><tr>'
        f'<th class="l">period</th>'
        f'<th><span class="blue">Claude</span></th>'
        f'<th><span class="amber">ChatGPT</span></th>'
        f'<th>S&amp;P 500</th>'
        f'<th>winner</th>'
        f'<th class="l">detail</th>'
        f'</tr>'
        + "".join(rows_html)
        + '</table>'
        '<div class="edge" style="margin-top:6px">'
        'Both models asked the same prompt: &ldquo;pick your top S&amp;P 500 stocks for the next month.&rdquo; '
        'Equal weight unless stated. Returns are total price return, no dividends. '
        'Log picks with <span class="muted">python log_picks.py --claude</span> / '
        '<span class="muted">--chatgpt</span>.</div>'
    )


def _render_single_model(results, _pct, _delta) -> str:
    """Fallback: one model only (before the other is logged)."""
    model_name = results[0].model.title() if results else "AI"

    eq = 1.0
    spx_eq = 1.0
    for r in sorted(results, key=lambda x: x.pub_date):
        eq *= (1 + r.portfolio_return)
        spx_eq *= (1 + r.spx_return)

    live_count = sum(1 for r in results if r.is_live)
    live_note = f' &middot; <span class="green">{live_count} live</span>' if live_count else ""

    rows_html = []
    for r in results:
        best = max(r.per_stock.items(), key=lambda x: x[1]) if r.per_stock else ("--", 0)
        worst = min(r.per_stock.items(), key=lambda x: x[1]) if r.per_stock else ("--", 0)
        live_badge = ' <span class="green" style="font-size:9px">&#9679; LIVE</span>' if r.is_live else ""
        end_label = "today" if r.is_live else str(r.end_date.date())
        days = (r.end_date - r.pub_date).days

        rows_html.append(
            f'<tr>'
            f'<td class="l" style="font-size:11px">{r.round_name}{live_badge}</td>'
            f'<td class="muted" style="font-size:11px">{r.pub_date.date()} &rarr; {end_label}'
            f' <span style="font-size:9px">({days}d)</span></td>'
            f'<td>{_pct(r.portfolio_return)}</td>'
            f'<td>{_pct(r.spx_return)}</td>'
            f'<td>{_delta(r.portfolio_return - r.spx_return)}</td>'
            f'<td class="l muted" style="font-size:10px">'
            f'best: {best[0]} {best[1]*100:+.0f}% / worst: {worst[0]} {worst[1]*100:+.0f}%</td>'
            f'</tr>'
        )

    return (
        f'<h2>{model_name} picks vs S&amp;P 500</h2>'
        f'<div class="edge" style="margin-bottom:8px">'
        f'Cumulative: {model_name} {_pct(eq - 1)}'
        f' &middot; S&amp;P 500 {_pct(spx_eq - 1)}'
        f'{live_note}'
        f'</div>'
        f'<table><tr>'
        f'<th class="l">round</th><th class="l">period</th>'
        f'<th>{model_name}</th><th>S&amp;P 500</th><th>vs S&amp;P</th>'
        f'<th class="l">stock detail</th>'
        f'</tr>'
        + "".join(rows_html)
        + '</table>'
    )


# ---------------------------------------------------------------------------
# CLI helpers: log picks for any model
# ---------------------------------------------------------------------------

def log_picks(
    tickers: list[str],
    weights: list[float] | None = None,
    model: str = "chatgpt",
    name: str | None = None,
    pub_date: str | None = None,
    source: str = "manual",
) -> dict:
    """Append a new round of picks to ai_picks.csv."""
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

    existing = load_picks()
    next_id = int(existing["round_id"].max()) + 1 if not existing.empty else 1

    label = model.title()
    if name is None:
        name = f"{label} {pub.strftime('%b %Y')}"

    rows = []
    for ticker, weight in zip(tickers, weights):
        rows.append({
            "round_id": next_id,
            "model": model,
            "round_name": name,
            "source": source,
            "pub_date": str(pub.date()),
            "end_date": "",
            "ticker": ticker,
            "weight": weight,
        })

    with open(PICKS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "round_id", "model", "round_name", "source",
            "pub_date", "end_date", "ticker", "weight",
        ])
        for row in rows:
            writer.writerow(row)

    return {
        "round_id": next_id,
        "model": model,
        "name": name,
        "pub_date": str(pub.date()),
        "tickers": tickers,
        "weights": weights,
    }


def close_round(round_id: int, end_date: str | None = None) -> None:
    """Close a live round by setting its end_date."""
    end = end_date or str(pd.Timestamp.now().normalize().date())
    df = load_picks()
    mask = df["round_id"] == round_id
    if not mask.any():
        raise ValueError(f"No round with id {round_id}")
    df.loc[mask, "end_date"] = end
    df.to_csv(PICKS_PATH, index=False)
