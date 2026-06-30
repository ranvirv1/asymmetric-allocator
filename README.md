# Asymmetric Allocator

A point-in-time, regime-gated stock allocation engine. Each week it reads the macro regime,
ranks the investable universe (S&P 500 + Nasdaq-100 + TSM) for momentum leaders, sizes a
risk-budgeted book with pre-set stops and take-profits, proves itself with an honest
walk-forward backtest, and benchmarks itself against published ChatGPT **and** Claude stock picks.

**Decision-support only — not financial advice and not an autotrader.** It proposes a ranked
allocation to review and place manually. See _Limitations_.

---

## What it does (and what the evidence says)

- **Regime gate (M2):** classifies RISK-ON / MIXED / COMPRESSION from FRED rates, credit
  spreads (BAA10Y), VIX, S&P trend and breadth → sets how much to deploy vs hold in cash.
- **Signal (M4):** **RS** (price relative-strength) is the validated engine. **ERM**
  (analyst estimate-revision momentum, from yfinance dated grades) was tested and **cut** —
  it hurt returns out-of-sample (the spec's §6 ablation doing its job). ERM is opt-in.
- **Book (M5/M6/M7):** top **5** momentum anchors by default (switch to 10 or 15 live), vol-scaled,
  capped, with hard stops (~2.5×ATR) and a trim ladder (+50% / +100%). Satellites (non-obvious bets)
  need ERM, so the default RS book is anchors-only.
- **Backtest (M8):** monthly walk-forward 2020–2026, point-in-time, with transaction costs,
  an ablation suite, catch-rate, and median+drawdown-first metrics.
- **Dashboard (M9):** the report leads with the regime call, then what changed, the book (with
  **live delayed prices** that auto-refresh), a **"why these picks"** line per name, a **"how to hold"**
  guide, and a **Market signals** table — Prospero-style 0–100 ratings: Net Options, Upside, Downside,
  Short Pressure (Dark Pool needs a paid feed). Plus the ChatGPT-vs-Claude-vs-S&P race.

**Out-of-sample validated result (RS, top-15, regime-gated):** ~**+34% CAGR** vs S&P **+14.5%**,
with **−16% max drawdown** vs the market's −25%. The single biggest live-return fix was deploying
the full equity budget (~85%) instead of leaving the satellite sleeve as idle cash.

(The +34% figure is the validated **top-15** config; the live default is now **5 names** —
more concentrated, so higher highs and deeper drawdowns. 10/15 are a click away.)

### Live dials (control bar on the site)
**Mode** — three presets, each with a clear intention:
- **Safe** — *protect capital, lower drawdown.* RS signal + regime **cash buffer** (de-risks in
  downturns). The validated default. ~+34% CAGR / −16% DD.
- **Returns** — *maximise compounding, accept bigger swings.* Same RS picks, **fully deployed**,
  no cash buffer. ~+41% CAGR / −21% DD.
- **Early** — *catch emerging winners earlier.* A **different signal**: short-window strength +
  momentum **acceleration** + volume surge + breakout proximity, instead of long-window RS.
  Keeps the cash buffer. **Experimental — not yet backtested; expect more whipsaws.**

(Safe vs Returns differ *only* in deployment — same picks. Early changes the *signal*.)

**Picks — 5 / 10 / 15** (`config.yaml → cuts.max_anchors`): concentration. 15 is the
risk-adjusted sweet spot from the sweep; 5 is highest-conviction / highest-variance.

Toggle both live on the site, or via flags: `weekly_run.py returns top10`, `safe top5`,
`early top5`, etc.

## Using it

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
copy .env.example .env   # add free keys: FRED, FMP (FINNHUB optional)

# the live site (opens http://127.0.0.1:8765 — refresh + mode dial)
.\run_site.bat

# or one-shot the weekly book + dashboard
.\.venv\Scripts\python.exe scripts\weekly_run.py
```

**Desktop shortcuts:** _Open Site_ (live site), _Run Now_ (rebuild + open report), _Latest
Report_ (last report). **Automation:** a Windows task (`AsymmetricAllocator-Weekly`) runs every
**Monday 07:00** — rebuilds the book, banks an estimate snapshot, and auto-rolls a fresh Claude
pick round from the engine's top names.

### Scripts
| Script | Purpose |
|---|---|
| `webapp.py` | local live site (Flask) — mode + picks dials, live prices, refresh |
| `scripts/weekly_run.py` | build the book + report; flags: `safe/returns/early`, `top5/top10/top15`, `research`, `ermrs`, `snapshot`, `claudelog`, `nogpt`, `norefresh`, `noopen` |
| `log_picks.py` | log AI stock picks for the benchmark: `--chatgpt`/`--claude TICKERS`, `--close N`, `--show` |
| `scripts/run_backtest.py [rs]` | walk-forward backtest + ablations |
| `scripts/sweep.py` | out-of-sample concentration/regime sweep |
| `scripts/fetch_universe.py` | rebuild the S&P 500 + Nasdaq-100 + TSM list + bulk price cache |

## Data sources (free)
FRED (macro), **yfinance** (prices + analyst revisions — no daily cap, the primary source),
FMP (backup, 250/day), stooq (backup). See `src/allocator/data/`.

## Limitations (read before trusting a number)
1. **Survivorship bias:** universe = *current* S&P 500 + Nasdaq-100 + TSM + a delisted
   overlay, not true point-in-time membership → backtest returns are an **upper bound**.
2. **Momentum is late** — catch-rate on real winners is 0–20%; it rides trends and dodges
   crashes, it doesn't call turns.
3. ERM uses a grade-action proxy; the forward-snapshot job banks true estimate revisions
   weekly for a cleaner test in ~a year.
4. **Market signals are free analogues, not Prospero's ML.** Net Options / Upside / Downside /
   Short Pressure are transparent 0–100 composites from delayed, all-participant free data
   (yfinance options, analyst targets, short interest). Dark Pool needs a paid (or 2–4-week
   lagged FINRA) feed — shown as `—`.
5. **Decision-support, not advice.** Stops & sizing make being wrong survivable, not being
   right guaranteed. Past-pattern fit ≠ future return.
