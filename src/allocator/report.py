"""M9 — Reporter. Single-file HTML dashboard in the house aesthetic (spec §3), redesigned
action-first: lead with the regime CALL, then WHAT CHANGED this week, then THE BOOK (what to
deploy, at what stop/trim). Sub-score detail is collapsed to one conviction bar; the backtest
moves to an optional research footer. Opens in any browser — no Claude needed.
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

import pandas as pd

from .config import REPORTS_DIR
from .weekly import REGIME_CALL

_VC = {"RISK_ON": "var(--green)", "MIXED": "var(--amber)", "COMPRESSION": "var(--red)"}

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Instrument+Serif:ital@0;1&display=swap');
:root{--bg:#0a0b0d;--panel:#111317;--line:#1e2128;--ink:#e8e6e1;--muted:#8b8f98;
--green:#3fb950;--red:#f85149;--blue:#58a6ff;--amber:#d29922;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'DM Mono',monospace;font-size:13px;line-height:1.55;padding:30px 34px 70px;max-width:1040px}
h1{font-family:'Instrument Serif',serif;font-style:italic;font-weight:400;font-size:40px;margin:0}
h2{font-family:'Instrument Serif',serif;font-style:italic;font-weight:400;font-size:22px;margin:32px 0 10px}
.sub{color:var(--muted);font-size:12px;margin:2px 0 22px}
.call{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--cv);border-radius:10px;padding:18px 20px;margin-bottom:8px}
.verdict{font-size:24px;font-weight:500;letter-spacing:.5px;color:var(--cv)}
.deploy{display:flex;gap:18px;align-items:center;margin-top:12px;flex-wrap:wrap}
.bigbar{position:relative;height:14px;width:300px;border-radius:5px;overflow:hidden;display:flex}
.chip{display:inline-block;padding:6px 12px;border-radius:6px;margin:0 8px 8px 0;font-size:12.5px}
.buy{background:rgba(63,185,80,.12);color:var(--green);border:1px solid rgba(63,185,80,.3)}
.sell{background:rgba(248,81,73,.12);color:var(--red);border:1px solid rgba(248,81,73,.3)}
.adj{background:rgba(210,153,34,.12);color:var(--amber);border:1px solid rgba(210,153,34,.3)}
table{width:100%;border-collapse:collapse;margin-top:4px}
th{text-align:right;color:var(--muted);font-weight:400;font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;border-bottom:1px solid var(--line);padding:7px 9px}
th:first-child,th.l{text-align:left}
td{padding:9px;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums}
td.l{text-align:left}
.tk{font-weight:500;font-size:14px}
.bar{position:relative;height:7px;width:70px;background:#1a1d24;border-radius:4px;overflow:hidden;display:inline-block;vertical-align:middle}
.bar>span{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--green)}
.muted{color:var(--muted)} .green{color:var(--green)} .red{color:var(--red)} .amber{color:var(--amber)} .blue{color:var(--blue)}
.banner{margin-top:34px;border:1px dashed var(--amber);border-radius:8px;padding:12px 16px;color:var(--amber);font-size:11px;line-height:1.7}
.edge{color:var(--muted);font-size:12px;margin-top:6px}
"""


def _esc(x) -> str:
    return html.escape(str(x))


def _deploy_bar(b: dict) -> str:
    return (f'<div class="bigbar"><span style="width:{b["anchor"]*100:.0f}%;background:var(--green)"></span>'
            f'<span style="width:{b["satellite"]*100:.0f}%;background:var(--blue)"></span>'
            f'<span style="width:{b["cash"]*100:.0f}%;background:#3a3d44"></span></div>')


def _changes_html(diff: dict | None) -> str:
    if diff is None:
        return ""
    if diff.get("is_initial"):
        return '<h2>Changes this week</h2><div class="muted">Initial book — no prior run to compare.</div>'
    chips = []
    for b in diff["buys"]:
        chips.append(f'<span class="chip buy">&#9650; BUY {_esc(b["ticker"])} &middot; &pound;{b["gbp"]:,.0f}</span>')
    for s in diff["sells"]:
        chips.append(f'<span class="chip sell">&#9660; SELL {_esc(s["ticker"])} &middot; was &pound;{s["gbp"]:,.0f}</span>')
    for c in diff["changes"]:
        chips.append(f'<span class="chip adj">{("&#9650; ADD" if c["action"]=="ADD" else "&#9660; TRIM")} '
                     f'{_esc(c["ticker"])} &middot; {c["delta_weight"]*100:+.1f}pt</span>')
    if not chips:
        chips.append('<span class="chip adj">No position changes vs last week.</span>')
    return (f'<h2>Changes this week <span class="muted" style="font-size:13px">vs {diff["prev_date"]}</span></h2>'
            + "".join(chips))


def _book_table(result: dict, bucket: str, quotes: dict | None = None) -> str:
    rows = result["allocation_rows"]
    scored = result["scored"]
    quotes = quotes or {}
    sub = rows[rows["bucket"] == bucket] if not rows.empty else rows
    if sub.empty:
        if bucket == "SATELLITE":
            return '<div class="muted">— none this week (satellites need the ERM signal; currently RS-only) —</div>'
        return '<div class="muted">— none —</div>'

    body = []
    for i, r in enumerate(sub.itertuples(), 1):
        ws = float(scored.loc[r.ticker, "winner_score"]) if r.ticker in scored.index else float("nan")
        conv = f'<span class="bar"><span style="width:{max(0,min(100,ws)):.0f}%"></span></span>' if ws == ws else ""
        star = ' <span class="amber" title="designed winner">&#9733;</span>' if getattr(r, "designed_winner", False) else ""
        stop = getattr(r, "stop_price", None)
        stop_h = f'{stop} <span class="muted">({getattr(r,"stop_pct","")}%)</span>' if stop else '<span class="muted">n/a</span>'
        cat = getattr(r, "catalyst", "") or ""
        cat_h = f'<span class="amber">&#9873;</span>' if cat else ""
        # live price + move vs entry (cell auto-updates via /api/quotes when served by the app)
        q = quotes.get(r.ticker)
        entry = r.price_usd or 0
        if q and entry:
            chg = q / entry - 1.0
            col = "green" if chg >= 0 else "red"
            inner = f'${q:,.2f} <span class="{col}">{chg*100:+.1f}%</span>'
        else:
            inner = '<span class="muted">&mdash;</span>'
        now_h = f'<span id="q-{_esc(r.ticker)}" data-entry="{entry}">{inner}</span>'
        body.append(
            f'<tr><td class="l muted">{i}</td><td class="l tk">{_esc(r.ticker)}{star} {cat_h}</td>'
            f'<td class="l">{conv}</td>'
            f'<td>&pound;{r.gbp_amount:,.0f}</td><td class="muted">{r.target_weight*100:.1f}%</td>'
            f'<td>{r.shares}</td><td>${r.price_usd:,.2f}</td>'
            f'<td>{now_h}</td>'
            f'<td class="red">{stop_h}</td>'
            f'<td class="muted">+50% ${getattr(r,"trim1_price","")} &middot; +100% ${getattr(r,"trim2_price","")}</td></tr>'
        )
    head = ('<table><tr><th class="l">#</th><th class="l">ticker</th><th class="l">conviction</th>'
            '<th>deploy</th><th>wt</th><th>shares</th><th>entry</th><th>live now</th><th>stop</th>'
            '<th>take profit</th></tr>' + "".join(body) + "</table>")
    return head


def _rate_cell(value, color: str) -> str:
    """A compact 0-100 rating: thin bar + number, color-coded. None -> dash."""
    if value is None:
        return '<td><span class="muted">&ndash;</span></td>'
    v = max(0, min(100, int(value)))
    return (f'<td><span class="bar" style="width:54px"><span style="width:{v}%;'
            f'background:var(--{color})"></span></span> <b>{v}</b></td>')


def _reasons_html(result: dict, sig: dict) -> str:
    """One-line, data-driven 'why up?' per pick — the actual signals that flagged it."""
    from .data import options, prices
    rows = result["allocation_rows"]
    anchors = rows[rows["bucket"] == "ANCHOR"] if not rows.empty else rows
    if anchors.empty:
        return ""
    reg = result["regime"].verdict.replace("_", "-")
    spx = prices.history("^SPX")
    spx_c = spx["close"] if not spx.empty else None
    items = []
    for r in anchors.itertuples():
        df = prices.history(r.ticker)
        if df.empty:
            continue
        c = df["close"]
        px = r.price_usd
        bits = []
        try:
            r6 = float(prices.trailing_return(c, 6).iloc[-1])
            r6i = float(prices.trailing_return(spx_c, 6).iloc[-1]) if spx_c is not None else 0.0
            if r6 - r6i > 0.02:
                bits.append(f"<b class='green'>+{(r6-r6i)*100:.0f}pts vs S&amp;P over 6 months</b>")
        except Exception:
            pass
        try:
            s50, s200 = c.rolling(50).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
            if px and px > s50 and px > s200:
                bits.append("above rising 50/200-day averages")
            if float(prices.pct_from_high(c).iloc[-1]) > -0.08:
                bits.append("near 52-week highs")
        except Exception:
            pass
        upp = options.target_signals(r.ticker, px).get("upside_pct")
        if upp and upp > 0.05:
            bits.append(f"<b class='green'>+{upp*100:.0f}%</b> to analyst target")
        nos = (sig.get(r.ticker, {}) or {}).get("nos")
        if nos and nos >= 55:
            bits.append(f"bullish options (net {nos:.0f})")
        reason = "; ".join(bits[:3]) if bits else "top momentum rank in the universe"
        items.append(f'<tr><td class="l tk" style="vertical-align:top">{_esc(r.ticker)}</td>'
                     f'<td class="l muted">{reason}.</td></tr>')
    return ('<h2>Why these picks &mdash; the upward case</h2><table>' + "".join(items) + '</table>'
            '<div class="edge">The engine&rsquo;s data-driven case for each name: price momentum, trend, '
            'analyst price targets, and options positioning &mdash; i.e. <i>why the signal flagged it</i>, '
            f'not a guarantee. In a {reg} regime the strategy leans into established momentum leaders.</div>')


def _how_to_hold_html(result: dict) -> str:
    """Plain-English holding discipline — the strategy is signal-driven, not time-based."""
    cfg = result.get("cfg", {})
    ex = cfg.get("exits", {})
    n = len(result["buckets"].anchors)
    items = [
        ("Rhythm", "Monthly rebalance, weekly check. The book refreshes every Monday &mdash; act on "
                   "the <b>Changes this week</b> chips (buy the new names, sell the dropped ones)."),
        ("Hold while", f"a name stays in this top-{n} book <b>and</b> trades above its stop. There&rsquo;s "
                       "no fixed timer &mdash; you hold winners as long as their momentum keeps them ranked."),
        ("Sell when", "it drops out of the book (shows up as a <b class='red'>Sell</b>) <b>or</b> closes below "
                      "its <b class='red'>stop</b> price &mdash; whichever comes first. Stops cut losers fast."),
        ("Take profit", f"trim &#8531; at <b>+{int(ex.get('trim1_at',0.5)*100)}%</b> and another &#8531; at "
                        f"<b>+{int(ex.get('trim2_at',1.0)*100)}%</b>; let the rest run. Don&rsquo;t cap a winner."),
        ("Typical hold", "weeks to a couple of months for most names; the 1&ndash;2 big winners ride far longer "
                         "(that&rsquo;s where the returns come from)."),
    ]
    body = "".join(f'<div style="margin:6px 0"><b class="blue">{k}.</b> <span class="muted">{v}</span></div>'
                   for k, v in items)
    warn = ('<div style="margin-top:8px" class="amber">&#9873; Not buy-and-forget &mdash; the backtested edge '
            'needs the rotation + stops. Concentrated to ' + str(n) + ' names = higher conviction but bigger swings '
            'than the 15-name config the backtest validated.</div>')
    return f'<h2>How to hold this book</h2><div class="panel" style="display:block">{body}{warn}</div>'


def _signals_table(result: dict, sig: dict) -> str:
    """Clean Prospero-style ratings — one row per holding, 0-100 each."""
    rows = result["allocation_rows"]
    if rows.empty or not sig:
        return ""
    body = []
    for r in rows.itertuples():
        s = sig.get(r.ticker, {})
        nos = s.get("nos")
        nos_v = round(nos) if nos is not None else None
        nos_col = "green" if (nos_v is not None and nos_v >= 55) else ("red" if (nos_v is not None and nos_v <= 45) else "amber")
        sp = s.get("short_pressure")
        sp_col = "green" if s.get("squeeze") else "amber"   # squeeze = bullish, else neutral intensity
        body.append(
            f'<tr><td class="l tk">{_esc(r.ticker)}</td>'
            + _rate_cell(nos_v, nos_col)
            + _rate_cell(s.get("upside"), "green")
            + _rate_cell(s.get("downside"), "red")
            + _rate_cell(sp, sp_col)
            + '<td class="muted" title="needs a paid / lagged feed">&ndash;</td></tr>'
        )
    return (
        '<h2>Market signals</h2>'
        '<table><tr><th class="l">ticker</th><th class="l">net options</th><th class="l">upside</th>'
        '<th class="l">downside</th><th class="l">short pressure</th><th class="l">dark pool</th></tr>'
        + "".join(body) + '</table>'
        '<div class="edge">All 0&ndash;100 (80+ strong, 20&minus; weak). '
        '<b class="green">Net options</b>: call-vs-put positioning (high = bets up). '
        '<b class="green">Upside</b> / <b class="red">downside</b>: independent breakout scores '
        '(options demand + analyst targets + momentum). '
        '<b class="amber">Short pressure</b>: short-interest intensity &mdash; '
        '<span class="green">green = squeeze</span> (heavy shorts + rising price = bullish fuel), '
        'amber = neutral. <b>Dark pool</b>: needs a paid/lagged feed (FINRA ATS) &mdash; not free real-time.</div>')


def _equity_svg(results: dict, w: int = 760, h: int = 220) -> str:
    series = {n: r["equity"] for n, r in results.items() if "equity" in r and len(r["equity"]) > 1}
    if not series:
        return ""
    allidx = sorted(set().union(*[s.index for s in series.values()]))
    t0, t1 = allidx[0], allidx[-1]
    span = (t1 - t0).days or 1
    vmax = max(float(s.max()) for s in series.values())
    pad = 30
    cols = ["var(--green)", "var(--blue)", "var(--amber)", "var(--muted)"]
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px"><rect width="{w}" height="{h}" fill="#0d0f13"/>']
    for i, (name, s) in enumerate(series.items()):
        pts = " ".join(f"{pad+(d-t0).days/span*(w-2*pad):.1f},{h-pad-(v/vmax)*(h-2*pad):.1f}" for d, v in s.items())
        out.append(f'<polyline fill="none" stroke="{cols[i%len(cols)]}" stroke-width="1.5" points="{pts}"/>')
        out.append(f'<text x="{w-pad}" y="{16+i*15}" fill="{cols[i%len(cols)]}" font-size="11" text-anchor="end">{_esc(name)} {s.iloc[-1]:.1f}x</text>')
    out.append(f'<text x="{pad}" y="{h-8}" fill="var(--muted)" font-size="10">{t0.date()}</text></svg>')
    return "".join(out)


_FLIPS = {
    "RISK_ON": "Holds while the S&P stays above its 200-day average and credit stays calm. "
               "Watch for a 200-day break (&rarr; MIXED) or spreads widening fast (&rarr; COMPRESSION).",
    "MIXED": "Conflicting signals. Resolves up (&rarr; RISK-ON) if trend &amp; breadth strengthen, "
             "or down (&rarr; COMPRESSION) if price breaks the 200-day or spreads widen.",
    "COMPRESSION": "Defensive until the S&P reclaims its 200-day average and credit spreads "
                   "stabilise &mdash; then it can step back up to MIXED / RISK-ON.",
}


def _revision_tilt(result: dict) -> str:
    from .config import DATA_DIR
    snap_dir = DATA_DIR / "snapshots"
    files = sorted(snap_dir.glob("estimates_*.csv")) if snap_dir.exists() else []
    rows = result["allocation_rows"]
    if not files or rows.empty:
        return ""
    try:
        df = pd.read_csv(files[-1])
        held = set(rows["ticker"])
        sub = df[df["ticker"].isin(held)]
        if sub.empty:
            return ""
        up = int((sub["up_30d"].fillna(0) > sub["down_30d"].fillna(0)).sum())
        return (f"{up} of {len(sub)} holdings have analysts revising next-year EPS UP over the "
                f"last 30 days &mdash; forward earnings momentum (banked {files[-1].stem.replace('estimates_','')}).")
    except Exception:
        return ""


def _outlook_html(result: dict, as_of) -> str:
    from . import exits
    reg = result["regime"]
    items = [("What flips the call", _FLIPS.get(reg.verdict, "")),
             ("How to read the signal", "RS momentum rides established trends and is late to turns "
              "&mdash; it rotates into leaders rather than calling tops or bottoms. The stops cap "
              "the downside on the names where it&rsquo;s wrong.")]
    cats = exits._catalysts()
    today = str(pd.Timestamp(as_of).date())
    upcoming = [(t, c) for t, c in cats.items() if str(c["event_date"]) >= today]
    items.append(("Upcoming catalysts", ", ".join(
        f"{_esc(t)} ({_esc(c['kind'])} {_esc(c['event_date'])})" for t, c in upcoming[:6])
        if upcoming else "None scheduled in the overlay &mdash; add dated events to data/catalysts.csv."))
    tilt = _revision_tilt(result)
    if tilt:
        items.append(("Earnings revisions", tilt))
    body = "".join(f'<div style="margin:7px 0"><b class="blue">{k}.</b> <span class="muted">{v}</span></div>'
                   for k, v in items)
    return f'<h2>Future outlook</h2><div class="panel" style="display:block">{body}</div>'


def _glossary_html() -> str:
    terms = [
        ("Regime", "The macro weather. RISK-ON = lean into momentum; MIXED = balanced; COMPRESSION = defensive, raise cash."),
        ("Deploy / Cash", "Share of the book invested vs held in cash. Cash rises automatically when the regime turns defensive."),
        ("Anchors", "Obvious, liquid leaders already trending &mdash; the core of the book, lower variance."),
        ("Satellites", "Non-obvious earlier names with strong analyst-revision momentum &mdash; small, high-variance bets (need the ERM signal)."),
        ("RS / Conviction", "Relative strength: price momentum vs the index. The 0&ndash;100 winner score is its percentile &mdash; longer bar = stronger."),
        ("Stop", "Pre-set exit ~2.5&times;ATR below entry. Caps the loss when the thesis breaks (don&rsquo;t let winners round-trip)."),
        ("Take profit", "Trim 1/3 at +50% and another 1/3 at +100%; let the rest run for the fat tail."),
        ("Safe vs Returns mode", "Safe keeps the regime cash sleeve (lower drawdown). Returns deploys fully (higher CAGR, bigger drawdown)."),
    ]
    rows = "".join(f'<tr><td class="l tk" style="white-space:nowrap;vertical-align:top">{k}</td>'
                   f'<td class="l muted">{v}</td></tr>' for k, v in terms)
    return f'<h2>What everything means</h2><table>{rows}</table>'


def _actions_html(diff: dict | None, result: dict) -> str:
    acts = []
    if diff and not diff.get("is_initial"):
        if diff["buys"]:
            acts.append("Buy &mdash; " + ", ".join(f'<b class="green">{_esc(b["ticker"])}</b> &pound;{b["gbp"]:,.0f}'
                                                    for b in diff["buys"]))
        if diff["sells"]:
            acts.append("Sell &mdash; " + ", ".join(f'<b class="red">{_esc(s["ticker"])}</b>' for s in diff["sells"]))
    acts.append("Set each position&rsquo;s stop at its red price; trim 1/3 at +50% / +100%.")
    acts.append(_esc(REGIME_CALL.get(result["regime"].verdict, "")))
    items = "".join(f'<div style="margin:5px 0">&#9656; {a}</div>' for a in acts)
    return f'<h2>This week&rsquo;s actions</h2><div class="panel" style="display:block">{items}</div>'


def _signals_html(result: dict) -> str:
    """Prospero-style overlay: Net Options Sentiment + analyst upside/downside per holding."""
    from .data import options
    rows = result["allocation_rows"]
    if rows.empty:
        return ""
    body = []
    for r in rows.itertuples():
        nos = options.net_options_sentiment(r.ticker).get("nos")
        tg = options.target_signals(r.ticker, r.price_usd)
        up, dn = tg.get("upside_pct"), tg.get("downside_pct")
        if nos is None:
            nos_h = '<span class="muted">&mdash;</span>'
        else:
            col = "green" if nos >= 55 else ("red" if nos <= 45 else "amber")
            nos_h = (f'<span class="bar" style="width:64px"><span style="width:{nos:.0f}%;'
                     f'background:var(--{col})"></span></span> <span class="{col}">{nos:.0f}</span>')
        up_h = (f'<span class="green">+{up*100:.0f}%</span>' if (up is not None and up >= 0)
                else (f'<span class="red">{up*100:.0f}%</span>' if up is not None else '<span class="muted">&mdash;</span>'))
        dn_h = f'<span class="red">{dn*100:.0f}%</span>' if dn is not None else '<span class="muted">&mdash;</span>'
        body.append(f'<tr><td class="l tk">{_esc(r.ticker)}</td><td class="l">{nos_h}</td>'
                    f'<td>{up_h}</td><td>{dn_h}</td></tr>')
    return ('<h2>Market signals &mdash; options &amp; analyst targets</h2>'
            '<table><tr><th class="l">ticker</th><th class="l">net options (0&ndash;100)</th>'
            '<th>analyst upside</th><th>downside</th></tr>' + "".join(body) + '</table>'
            '<div class="edge">Net options = call-vs-put open-interest/volume share (80+ = bets up, '
            '20&minus; = bets down, ~50 = divided). Upside/downside = mean / low analyst price target '
            'vs current price. Free delayed data &mdash; explainable analogues of Prospero&rsquo;s '
            'signals, not their proprietary ML.</div>')


def render_dashboard(result: dict, diff: dict | None = None, out_path: str | Path | None = None,
                     backtest: dict | None = None, next_run: str | None = None,
                     gpt_comparison: list | None = None) -> Path:
    reg = result["regime"]
    alloc = result["allocation"]
    as_of = result["as_of"]
    b = reg.budget
    vcol = _VC.get(reg.verdict, "var(--muted)")
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    invested = (1 - alloc.cash_weight) * 100
    nr = f' &middot; next auto-run {next_run}' if next_run else ""
    gate_on = result.get("cfg", {}).get("live", {}).get("use_regime_gate", True)
    is_early = "EARLY" in getattr(result.get("scored"), "columns", [])
    if is_early:
        mode, mode_col = "Early &mdash; catch emerging winners (experimental)", "blue"
    elif gate_on:
        mode, mode_col = "Safe &mdash; protect capital (regime cash buffer)", "amber"
    else:
        mode, mode_col = "Returns &mdash; maximise growth (fully deployed)", "green"

    c = reg.components
    def drv(label, key, fmt="{:+.2f}"):
        v = c.get(key)
        if not isinstance(v, float) or v != v:
            return f'{label} <span class="muted">n/a</span>'
        return f'{label} <span class="{ "green" if v>0 else "red"}">{fmt.format(v)}</span>'

    # live (delayed) market quotes for the holdings — shown as a "live now" column + move vs entry
    from .data import prices as _prices
    held = result["allocation_rows"]["ticker"].tolist() if not result["allocation_rows"].empty else []
    quotes = _prices.live_quotes(held)
    quote_note = (f' &middot; <span class="green">live prices {dt.datetime.now().strftime("%H:%M")}</span>'
                  if quotes else ' &middot; <span class="muted">live quotes unavailable</span>')

    # Prospero-style 0-100 ratings per holding (Net Options, Upside, Downside, Short Pressure).
    from .data import options as _options
    _scored = result["scored"]
    sig = {}
    for _r in result["allocation_rows"].itertuples():
        _rs = float(_scored.loc[_r.ticker, "winner_score"]) if _r.ticker in _scored.index else None
        sig[_r.ticker] = _options.stock_signals(_r.ticker, quotes.get(_r.ticker) or _r.price_usd, _rs)

    parts = [f"<style>{_CSS}</style>",
        "<h1>Asymmetric Allocator</h1>",
        f'<div class="sub">as of <b>{as_of.date()}</b> &middot; book &pound;{alloc.book_gbp:,.0f} '
        f'&middot; mode <b class="{mode_col}">{mode}</b> &middot; generated {now}{nr}{quote_note}</div>',

        f'<div class="call" style="--cv:{vcol}">'
        f'<div class="verdict">{reg.verdict.replace("_"," ")}</div>'
        f'<div style="margin-top:4px">{REGIME_CALL.get(reg.verdict,"")}</div>'
        f'<div class="deploy">{_deploy_bar(b)}'
        f'<span>deploy <b class="green">{invested:.0f}%</b> &middot; cash <b class="muted">{alloc.cash_weight*100:.0f}%</b></span></div>'
        f'<div class="edge">regime drivers &middot; ' + " &middot; ".join(
            [drv("trend", "spx_vs_200dma"), drv("6m", "spx_6m_ret"),
             drv("credit", "credit_spread_level_z"), drv("breadth", "breadth_above_200dma", "{:.0%}")]) + "</div></div>",

        _changes_html(diff),
        _actions_html(diff, result),

        "<h2>The book &mdash; anchors</h2>", _book_table(result, "ANCHOR", quotes),
        "<h2>Satellites &mdash; small, high-variance bets</h2>", _book_table(result, "SATELLITE", quotes),
        f'<div class="edge" style="margin-top:12px">{len(result["buckets"].anchors)} anchors '
        f'&middot; {len(result["buckets"].satellites)} satellites &middot; {len(result["buckets"].watch)} on watch '
        f'&middot; &#9873; = catalyst (de-rate if it slips) &middot; &#9733; = designed winner</div>',

        _reasons_html(result, sig),
        _how_to_hold_html(result),
        _signals_table(result, sig),
        _outlook_html(result, as_of),
        _glossary_html(),
    ]

    if backtest:
        from . import backtest as bt
        parts.append("<h2>How the engine has done &mdash; 2020&ndash;2026 backtest</h2>")
        parts.append(_equity_svg(backtest["results"]))
        bench = backtest["results"].get("S&P 500 (buy & hold)")
        bc = bt.metrics(bench["equity"], bench["returns"])["cagr"] if bench else 0
        tbl = ['<table><tr><th class="l">strategy</th><th>CAGR</th><th>max DD</th><th>Sortino</th><th>vs S&amp;P</th></tr>']
        for name, res in backtest["results"].items():
            m = bt.metrics(res["equity"], res["returns"])
            if not m:
                continue
            tbl.append(f'<tr><td class="l tk" style="font-size:13px">{_esc(name)}</td>'
                       f'<td class="green">{m["cagr"]*100:+.1f}%</td><td class="red">{m["max_drawdown"]*100:.1f}%</td>'
                       f'<td>{m["sortino"]:.2f}</td><td class="blue">{(m["cagr"]-bc)*100:+.1f}%</td></tr>')
        parts.append("".join(tbl) + "</table>")
    else:
        parts.append('<div class="edge" style="margin-top:14px">Backtest (RS, top-15, regime-gated, 2020&ndash;26, '
                     'out-of-sample validated): <span class="green">+34% CAGR</span> vs S&amp;P +14.5%, '
                     'max drawdown <span class="green">&minus;16%</span> vs &minus;25%. '
                     'Re-run with <span class="muted">research</span> for the curve.</div>')

    if gpt_comparison:
        from . import gpt_benchmark
        parts.append(gpt_benchmark.render_comparison_html(gpt_comparison))

    parts.append(
        "<script>(function(){var cells=Array.prototype.slice.call(document.querySelectorAll('[id^=\"q-\"]'));"
        "if(!cells.length)return;var syms=cells.map(function(c){return c.id.slice(2);});"
        "function mv(ch){return '<span class=\"'+(ch>=0?'green':'red')+'\">'+(ch>=0?'+':'')+(ch*100).toFixed(1)+'%</span>';}"
        "function poll(){fetch('/api/quotes?t='+syms.join(',')).then(function(r){return r.json();}).then(function(q){"
        "cells.forEach(function(c){var s=c.id.slice(2),p=q[s],e=parseFloat(c.dataset.entry);"
        "if(p){var ch=e?p/e-1:0;c.innerHTML='$'+p.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})+' '+mv(ch);}});"
        "}).catch(function(){});}poll();setInterval(poll,60000);})();</script>")

    parts.append(
        '<div class="banner">&#9873; Decision-support, not advice &mdash; it proposes, you place manually. '
        'Universe = current S&amp;P 500 + delisted overlay (survivorship bias remains; returns are an upper bound). '
        'RS is point-in-time clean from prices; ERM uses dated analyst actions (yfinance, point-in-time). '
        'Stops &amp; sizing make being wrong survivable, not being right guaranteed.</div>')

    out_path = Path(out_path) if out_path else REPORTS_DIR / f"dashboard_{as_of.date()}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("<!doctype html><html><head><meta charset='utf-8'>"
                        "<title>Asymmetric Allocator</title></head><body>"
                        + "".join(parts) + "</body></html>", encoding="utf-8")
    return out_path
