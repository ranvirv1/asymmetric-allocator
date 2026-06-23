# Asymmetric Allocator

A point-in-time, regime-gated stock allocation engine. Each week it reads the macro regime,
ranks the S&P 500 for momentum leaders, sizes a risk-budgeted book with pre-set stops and
take-profits, and proves itself with an honest walk-forward backtest.

**Decision-support only — not financial advice and not an autotrader.** It proposes a ranked
allocation to review and place manually. See _Limitations_.

---

## What it does (and what the evidence says)

- **Regime gate (M2):** classifies RISK-ON / MIXED / COMPRESSION from FRED rates, credit
  spreads (BAA10Y), VIX, S&P trend and breadth → sets how much to deploy vs hold in cash.
- **Signal (M4):** **RS** (price relative-strength) is the validated engine. **ERM**
  (analyst estimate-revision momentum, from yfinance dated grades) was tested and **cut** —
  it hurt returns out-of-sample (the spec's §6 ablation doing its job). ERM is opt-in.
- **Book (M5/M6/M7):** top-15 momentum anchors, vol-scaled, capped, with hard stops
  (~2.5×ATR) and a trim ladder (+50% / +100%). Satellites (non-obvious bets) need ERM, so the
  default RS book is anchors-only.
- **Backtest (M8):** monthly walk-forward 2020–2026, point-in-time, with transaction costs,
  an ablation suite, catch-rate, and median+drawdown-first metrics.

**Out-of-sample validated result (RS, top-15, regime-gated):** ~**+34% CAGR** vs S&P **+14.5%**,
with **−16% max drawdown** vs the market's −25%. The single biggest live-return fix was deploying
the full equity budget (~85%) instead of leaving the satellite sleeve as idle cash.

### Returns vs Safe mode (the dial)
`config.yaml → live.use_regime_gate`:
- **Safe (default, `true`):** keep the regime cash sleeve. +34% CAGR / −16% drawdown.
- **Returns (`false`):** deploy fully. +41% CAGR / −21% drawdown (still better than buy-and-hold).

Toggle it live from the site, or run `weekly_run.py returns` / `safe`.

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
Report_ (last report). **Automation:** a Windows task rebuilds the book and banks an estimate
snapshot every **Monday 07:00** (`AsymmetricAllocator-Weekly`).

### Scripts
| Script | Purpose |
|---|---|
| `webapp.py` | local live site (Flask) |
| `scripts/weekly_run.py` | build the book + report; flags: `returns safe research ermrs snapshot norefresh noopen` |
| `scripts/run_backtest.py [rs]` | walk-forward backtest + ablations |
| `scripts/sweep.py` | out-of-sample concentration/regime sweep |
| `scripts/fetch_universe.py` | refresh S&P 500 list + bulk price cache |

## Data sources (free)
FRED (macro), **yfinance** (prices + analyst revisions — no daily cap, the primary source),
FMP (backup, 250/day), stooq (backup). See `src/allocator/data/`.

## Limitations (read before trusting a number)
1. **Survivorship bias:** universe = *current* S&P 500 + a delisted overlay, not true
   point-in-time membership → backtest returns are an **upper bound**.
2. **Momentum is late** — catch-rate on real winners is 0–20%; it rides trends and dodges
   crashes, it doesn't call turns.
3. ERM uses a grade-action proxy; the forward-snapshot job banks true estimate revisions
   weekly for a cleaner test in ~a year.
4. **Decision-support, not advice.** Stops & sizing make being wrong survivable, not being
   right guaranteed. Past-pattern fit ≠ future return.
