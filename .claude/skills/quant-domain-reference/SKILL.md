---
name: quant-domain-reference
description: >
  Domain theory for the Asymmetric Allocator, as implemented in THIS repo. Load when you
  need to understand or modify anything involving: momentum / relative strength / RS,
  percentile ranks, WinnerScore, look-ahead or point-in-time bias, survivorship bias,
  walk-forward backtesting, tune vs validate windows, transaction costs, turnover, ATR,
  vol-scaled sizing, Kelly tilt, Sharpe/Sortino/CAGR/max drawdown/hit rate, regime gates
  (RISK_ON/MIXED/COMPRESSION), credit spreads (BAA10Y), 2s10s curve, breadth, VIX,
  z-scores, ERM / estimate revisions, anchor/satellite buckets, Extension, stops and trim
  ladders, catch-rate, GBP/fractional-share mechanics — or when reading scoring.py,
  regime.py, sizer.py, classifier.py, exits.py, backtest.py, prices.py and a finance term
  is unclear. This explains WHAT the concepts mean and the exact conventions the code uses.
---

# Quant domain reference — the theory as this repo implements it

Audience: an engineer who knows Python/pandas but not quantitative finance. Every term is
defined at first use; every formula is the one **this repo actually uses** (verified against
the code, as of 2026-07-11), with file:line and the mistake people usually make.

**When NOT to use this skill**
- Running, deploying, or operating the system (commands, artifacts, CI, Render) →
  `allocator-run-and-operate`.
- Recipes for proving/measuring something (ablation studies, sweeps, point-in-time audits,
  metric derivations with worked examples) → `allocator-proof-and-analysis-toolkit`.
- Config knobs and script flags → `allocator-config-and-flags`. History of what failed and
  why → `allocator-failure-archaeology`. Rules R1–R8 in full → `allocator-change-control`.

---

## 1. Cross-sectional momentum / relative strength (RS)

**Definition.** Momentum: stocks that have recently outperformed tend to keep outperforming
over the next months. *Cross-sectional* momentum ranks names **against each other today**
(buy the strongest relative to peers), as opposed to *time-series* momentum (buy a name when
its own past return is positive). This repo is cross-sectional: it always holds the top-N of
the universe ranked by strength, whatever the absolute level.

**This repo's RS features** — `scoring.py:58-77` (`_rs_features`), one row per ticker:

| Feature | Formula here | Meaning |
|---|---|---|
| `ret_3m_ex`, `ret_6m_ex`, `ret_12m_ex` | stock trailing return − `^SPX` trailing return over 3/6/12 months | *Excess return vs index* — strips out the market so you rank stock-specific strength, not beta in a rally |
| `dist_high` | `close / rolling_252d_max(close) − 1` (`prices.pct_from_high`, prices.py:280-283) | Distance below the 52-week high; 0 = at high = strongest |
| `above_50`, `above_200` | 1.0 if close > 50/200-day SMA else 0.0 | Trend confirmation flags |
| `sma50_rising`, `sma200_rising` | 1.0 if SMA today > SMA 21 rows ago (`.iloc[-22]`) | Is the trend itself improving |

**Trading-day convention.** `prices.trailing_return` (prices.py:275-277) uses
`periods = round(months * 21)` — **~21 trading days per month**, so 3/6/12 months = 63/126/252
rows. Everything here counts *trading* days, never calendar days. 252 trading days ≈ 1 year.

**Why percentile ranks (0–100), not raw values.** Each feature is converted to a
cross-sectional percentile rank via `_pct_rank` (scoring.py:43-45):
`s.rank(pct=True) * 100` — NaNs stay NaN. Then `rs_subscore` (scoring.py:94-100) averages the
per-feature ranks and **ranks the average again** so the final RS is itself a clean 0–100
percentile. Reasons:
1. **Unit-free**: a 40% return and "2% below high" aren't comparable raw; ranks are.
2. **Outlier-robust**: one 300% meme name would dominate any raw-value average; as a rank it
   is just "100th percentile", same as a 90% gainer.
3. **Stationary across regimes**: "top decile of the universe" means the same thing in 2020
   and 2025 even though raw return magnitudes differ wildly.
4. Downstream cutoffs (`A_cut: 80`, `S_cut: 75` in config.yaml) become interpretable:
   "top ~20% of the universe", regardless of market conditions.

**What people get wrong.** (a) Confusing relative strength with RSI — the 14-day oscillator.
Unrelated; this repo has no RSI. (b) Using raw returns instead of excess-vs-index, which makes
every backtest look like a momentum win during any bull market. (c) Forgetting the double
ranking: RS is a *rank of a mean of ranks*, so you cannot back out raw returns from it.

---

## 2. Point-in-time (PIT) discipline / look-ahead bias

**Definition.** Look-ahead bias = a computation dated *t* using any information that only
became known after *t*. Even one leaked day (e.g. ranking on month-end close but "trading" at
that same close computed with next-day data) can fabricate most of a backtest's edge.
Project law R5: **any computation at date t may use only data timestamped ≤ t.**

**How this repo enforces it.** One pattern everywhere: fetch full history once, then
**slice to ≤ as_of before computing anything**.
- Prices: `fetch_ohlcv(ticker, end=as_of)` slices `df.index <= end` (prices.py:143-159);
  `_rs_features` computes SMAs/returns only on the pre-sliced frame (scoring.py:59-69).
- Macro: `_zscore_at`, `_level_at`, `_change` all start with `series[series.index <= as_of]`
  (regime.py:39-61).
- ERM: each analyst action is dated; the loop skips `d > as_of` (scoring.py:118-127).
- Backtest: at rebalance date t it builds universe, regime, and scores as-of t, holds to
  t+1, and only *then* reads the t+1 price (backtest.py:132-157).

**What would silently break it** (the review checklist for any new signal):
- Computing a rolling statistic on the **full** series and then slicing — rolling itself is
  causal, but `.iloc[-1]` on an unsliced frame reads today's value. Always slice first.
- Using **current** snapshots at historical dates: `estimates.snapshot()` (current consensus),
  FMP `profile()` shares outstanding (universe.py:78-100 — the mktcap approximation is
  current shares × as-of price, and is *flagged* as such), Wikipedia's *current* S&P list
  (that one is the accepted survivorship gap, §3 below).
- Normalising (z-score, min-max) against **full-sample** mean/std instead of trailing history.
  Repo convention: z-score vs own trailing window only (regime.py `_zscore_at`).
- Caching keyed without `as_of` — the score memos are keyed `(as_of, tuple(tickers))`
  (scoring.py:39-40, 81, 146) precisely so date-t results can't bleed into date-u.

---

## 3. Survivorship bias

**Definition.** Testing a strategy on **today's** index members means every name in the test
already survived (or thrived) to the present. Bankruptcies and deleted losers never appear,
so historical returns are inflated — momentum strategies especially, since they concentrate
in exactly the volatile names most likely to have blown up.

**This repo's approximation** (universe.py:29-63): candidate set = the *current* S&P 500 list
(`data/sp500_constituents.csv`, ~503 names) **plus** a hand-maintained delisted overlay
(`data/delisted.csv` — 5 names as of 2026-07-11: SIVB, FRC, ATVI, SGEN, SPLK), each included
only while `delist_date >= as_of` (universe.py:53-63). That is nowhere near true point-in-time
membership — the real index turns over ~25–30 names a year, so 2020–2026 has on the order of
150 membership changes vs 5 covered here.

**Consequence — the honesty protocol.** Every backtest prints the honesty banner
(backtest.py:250-260) and every universe result carries the note (universe.py:138-141):
results are an **UPPER BOUND**. The headline "+34% CAGR out-of-sample" always carries this
caveat (rule R4). Closing this gap is a dedicated campaign — see `survivorship-bias-campaign`.

**What people get wrong.** Thinking the delisted overlay *fixes* survivorship. It only removes
the most grotesque cases (names that would crash a price fetch or an obvious blowup). The bias
direction is still known (upward) and unquantified. Never quote backtest numbers without the
upper-bound caveat.

---

## 4. Walk-forward backtesting; tune vs validate windows

**Definition.** *In-sample fitting*: choose parameters on a dataset, report performance on the
same data — you measure your ability to memorise, not to predict. *Walk-forward*: step through
time; at each date make decisions using only ≤ t data (PIT, §2), hold forward, repeat. This
repo's backtest (backtest.py:116-167) walks monthly rebalance dates — month-ends snapped to
the last trading day (`rebalance_dates`, backtest.py:66-77) — over 2020-01-01..2026-06-01.

**Tune vs validate** (config.yaml:76-77):
- `tune_window: 2020-01-01..2023-12-31` — in-sample; parameter/threshold choices happen here.
- `validate_window: 2024-01-01..2026-06-01` — out-of-sample, **quarantined (rule R1)**.

Why quarantined: every look at validate-window results while choosing a parameter converts
out-of-sample evidence into in-sample fitting; after enough peeks the validate window is just
a second tune window and the headline numbers mean nothing. `scripts/sweep.py` exists to do
this properly: it reports both windows and its **robust pick** requires above-median *tune*
Sortino, then ranks by *validate* Sortino (sweep.py:71-79) — chosen for holding up in both,
not for winning the test set.

**What people get wrong.** Running "just one quick check" of a new parameter against
2024–2026. That's the R1 violation. Compare candidates on the tune window; the validate window
confirms a *finished* choice, once. Also: walk-forward ≠ PIT-clean by itself — a walk-forward
loop that scores with a survivorship-clean signal but today's constituent list is still biased
(§3); the two disciplines are independent.

---

## 5. Transaction costs and turnover

**Definition.** Turnover = how much of the book you trade at a rebalance. *Two-way* turnover
sums both buys and sells: `Σ |w_new − w_old|` over the union of names. Each traded unit pays
cost (commission + spread + slippage), quoted in basis points (1 bp = 0.01%).

**This repo** (backtest.py:124, 138-141, 152):
```python
costs = cfg.get("costs_bps", 8) / 1e4          # 8 bps per side (config.yaml:70)
turn  = (w − prev_w).abs().sum()               # two-way, over union of names
port_ret -= turn * costs                       # charged every period
```
So a full liquidate-and-rebuy (turnover 2.0) costs 2.0 × 8 bps = 16 bps — i.e. the 8 bps is
per *side*, and two-way turnover naturally counts each side once. The first period charges
buying the whole book (prev_w is empty). Cash earns 0% (conservative; stated in the honesty
banner). Live cost reality for R is IBKR commissions + spread; 8 bps/side is the modelled
stand-in.

**What people get wrong.** Reporting one-way turnover against a per-side cost (halves the
drag), or ignoring costs entirely — monthly top-15 momentum has meaningful turnover, and a
signal tweak that adds churn can eat its own alpha. Any new signal's ablation must be net of
this charge (the backtest applies it automatically).

---

## 6. ATR, ATR%, vol-scaled sizing, annualised vol

**ATR (Average True Range).** A volatility measure in *price units*. True range for a day =
`max(high−low, |high−prev_close|, |low−prev_close|)` — the |·−prev_close| terms capture
overnight gaps that high−low misses. Wilder's ATR smooths TR with his own recursive average,
which is exactly an EWM with `alpha = 1/window`. Verified (prices.py:260-267):
```python
tr = concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/window, min_periods=window, adjust=False).mean()   # window=14
```
`adjust=False` is what makes it Wilder's recursion; the common mistake is a plain
`rolling(14).mean()` (SMA-ATR) or `ewm(span=14)` — different smoothing, different stops.

**ATR%** = ATR / close (prices.py:270-272) — volatility as a fraction of price, so a $30 name
and a $900 name are comparable.

**Vol-scaled sizing (1/ATR%).** Satellites are weighted proportional to `1/ATR%`
(sizer.py:104-110): a name that moves 6%/day gets half the weight of one that moves 3%/day, so
each position contributes roughly equal *risk*, not equal capital — "a 90%-vol lottery ticket
isn't sized like a utility" (sizer.py docstring). Anchors, by contrast, are score-weighted.

**Annualised volatility.** `prices.annualised_vol` (prices.py:286-287): std of daily returns
over a 63-day window × **√252**. √252 (not √365) because only trading days generate returns;
variance scales linearly with time, so std scales with √time.

**What people get wrong.** Mixing conventions — ATR uses EWM alpha=1/14 here, annualised vol
uses a 63-day rolling std; both are "volatility" but not interchangeable. And ATR is in
dollars: for cross-name comparisons always use ATR% (the sizer and exits both do).

---

## 7. Kelly criterion and the quarter-Kelly tilt

**Definition.** The Kelly criterion gives the bet fraction that maximises long-run compounded
growth given a known edge and odds (for a binary bet, `f* = edge/odds`). Full Kelly is
famously violent — it assumes you *know* your edge, and overestimating it causes ruinous
drawdowns. *Fractional Kelly* (betting some fraction of f*) sacrifices a little growth for a
large cut in variance; quarter-Kelly is a standard conservative choice.

**This repo does NOT compute true Kelly.** There is no estimated win-probability or payoff.
`_kelly_tilt` (sizer.py:41-44) borrows only the *shape* — bet more when the edge signal is
higher — as a bounded multiplicative tilt on sleeve weights:
```python
edge = (score - 50.0) / 50.0                        # WinnerScore 0-100 -> pseudo-edge in [-1, 1]
tilt = (1.0 + kelly_fraction * edge).clip(0.5, 1.5) # kelly_fraction = 0.25 (config.yaml:67)
```
Score 50 (median name) → tilt 1.0; score 100 → 1.25; score 0 → 0.75. With kelly_fraction
0.25 the raw tilt already lives in [0.75, 1.25], so the 0.5–1.5 clip only binds if someone
raises `kelly_fraction` above 0.5 — it is a safety rail, not an active constraint. Applied
inside `_size_sleeve` *before* the per-name caps and sleeve budget, which always dominate
(sizer.py:47-67): the tilt reshuffles within a sleeve; it can never blow the 20% anchor cap
or the regime cash floor.

**What people get wrong.** Calling this "Kelly sizing" in the strict sense — it isn't, and
treating `(score−50)/50` as a calibrated edge estimate would be overclaiming. It's a bounded
monotone tilt with Kelly-inspired scaling. Keep it secondary: caps and budgets are the risk
control; the tilt is seasoning.

---

## 8. Risk/performance metrics — and why median + max DD lead

All formulas from `backtest.metrics` (backtest.py:186-213), computed on the monthly-sampled
equity curve `eq` and monthly period returns `rets` (`periods_per_year = 12`):

| Metric | Formula here | Meaning / caveat |
|---|---|---|
| `max_drawdown` | `(eq / eq.cummax() − 1).min()` | Worst peak-to-trough loss. **Monthly sampling** — intramonth drawdowns are invisible; live pain can exceed this |
| `cagr` | `(eq_end/eq_start)^(1/years) − 1`, years = calendar days / 365.25 | Compound annual growth rate — the geometric annual return |
| `median_annual` / `mean_annual` | median/mean of calendar-year returns (`eq.resample("YE").last().pct_change()`) | Year-by-year distribution; first/last years are partial |
| `sortino` | `rets.mean() / std(rets[rets<0]) * √12` | Like Sharpe but denominator = std of **negative months only** — doesn't punish upside volatility. Note: simplified convention (no MAR/target; std over losing months only), not the textbook target-downside-deviation |
| `sharpe` | `rets.mean() / rets.std() * √12` | Return per unit of total volatility. **No risk-free subtraction** (rf treated as 0) — fine for comparing strategies within the repo, off by rf-level vs published Sharpes |
| `hit_rate` | `(rets > 0).mean()` | Fraction of positive months. Momentum lives with ~55-60% hit rates and skewed winners — a low hit rate is not failure by itself |
| `vol_annual` | `rets.std() * √12` | Annualised monthly volatility |

**Why lead with median annual + max drawdown (the honesty protocol, rule R4).** Mean annual
return and full-window CAGR are dominated by one or two blowout years — precisely what a
concentrated momentum book produces. Median annual answers "what does a *typical* year look
like", and max drawdown answers "what will it cost me to stay in the seat". The ordering of
the dict (backtest.py:202-213) is deliberate: `median_annual`, `max_drawdown` first. Also why
Sortino over Sharpe for the sweep's robust pick: momentum returns are right-skewed, and Sharpe
penalises the good tail. All quoted numbers must come from this function — no eyeballed
claims — and always with the survivorship caveat (§3).

---

## 9. Regime investing — RISK_ON / MIXED / COMPRESSION

**Definition.** A regime gate classifies the macro environment *before* stock selection and
sets how much risk the book may hold. Rationale (regime.py docstring): the ARKK lesson — one
−67% year erases three good ones, so the environment decides your beta budget, not the stocks.

**The three verdicts** map to budgets (config.yaml:33-36), anchor/satellite/cash:
RISK_ON .45/.40/.15 · MIXED .55/.25/.20 · COMPRESSION .65/.10/.25 — plus RS-weight modifiers
(×1.4 in RISK_ON, ×0.6 in COMPRESSION; config.yaml:27-30).

**The rule layer** (regime.py:153-171) — deterministic, checked in order:
1. **COMPRESSION** if S&P 500 below its own 200-day SMA, **or** credit spreads "widening
   fast" = the 21-day *change* in the spread, z-scored against its own history, > 1.5σ
   (regime.py:158-159). 21-day change because a single volatile day used to false-trigger
   COMPRESSION (documented fix; see `allocator-failure-archaeology`).
2. **RISK_ON** if trend up (S&P above 200dma AND positive 6-month return) AND spreads tight
   (level z < 0.5 and not widening fast) AND breadth ≥ 0.55.
3. **MIXED** otherwise.

**The inputs, in plain English:**
- **Credit spread — BAA10Y**: Moody's Baa corporate bond yield minus the 10-year Treasury
  yield. It measures how much extra yield the market demands to lend to medium-quality
  companies — it widens when default fear rises, and it co-moves with equity stress. The spec
  wanted true high-yield OAS (FRED `BAMLH0A0HYM2`, ICE BofA HY option-adjusted spread) — a
  purer junk-stress gauge — but FRED now truncates it to ~3 years (ICE licensing), useless
  for a 2020–2026 backtest, so BAA10Y was substituted (fred.py:22-25, config.yaml:83).
- **Yield curve 2s10s**: 10Y minus 2Y Treasury yield (regime.py:120-121). Negative
  (inverted) historically precedes recessions; feeds the composite score, not the rule layer.
- **Breadth**: fraction of universe names trading above their *own* 200-day SMA
  (regime.py:64-78). A rally carried by 5 mega-caps has poor breadth; broad participation is
  the healthier signal. RISK_ON needs ≥ 0.55 (`breadth_riskon`, config.yaml:81).
- **VIX vs its own 1-year median** (regime.py:129-131): `vix_now / median(trailing 252) − 1`.
  Relative to own history rather than an absolute level, because "high VIX" in 2021 and 2008
  are different numbers.

**Z-scores against trailing history.** `_zscore_at` (regime.py:39-49): latest value vs the
mean/std of its own trailing 756-day (~3-year) window, sliced to ≤ as_of. Point-in-time by
construction and self-calibrating per series.

**The composite score** (regime.py:137-151): each component is sign-oriented so positive =
risk-on (spreads and VIX get flipped), squashed through `tanh` to bound outliers to (−1, 1),
then averaged. `tanh` means one 8σ input can't dominate. Note the composite `regime_score` is
**reported but does not decide the verdict** — the rule layer does. That is the #1 reading
error in this module.

**What people also get wrong.** (a) Editing budgets to "stay invested" in COMPRESSION —
defeats the entire point; the gate costs CAGR (+34% gated vs +41% ungated) and buys drawdown
(−16% vs −21%); that trade is the deliberate `live.use_regime_gate` dial (config.yaml:54-57).
(b) Missing that with no S&P price data, `below_200` stays False (regime.py:107-115) — a dead
price feed silently biases *away* from COMPRESSION; the degenerate-universe guard in
`weekly_run.py` is the backstop.

---

## 10. Estimate-revision momentum (ERM) — status: CUT from default, re-test pending

**The hypothesis.** When analysts raise earnings estimates, they under-adjust; stocks with
rising estimates drift up for weeks afterward (post-revision drift). Estimate-revision
momentum should therefore lead price momentum — the spec anchored it at weight 0.30.

**The proxy this repo has.** True historical estimate revisions (dated changes to consensus
EPS) are not free. Substitute: **dated analyst grade actions** (upgrade/downgrade events)
from yfinance (`estimates.dated_grades`, estimates.py:52-92). Features per name over a
trailing 90-day window (scoring.py:109-142): net upgrades−downgrades, breadth
(net / count), cumulative grade-level change (grades mapped to ordinals 0–4 via
`_GRADE_RANK`, scoring.py:28-36), and coverage count. Point-in-time honest — each action is
dated and filtered ≤ as_of.

**Why the proxy is weaker than true revisions:** grade actions are sparse (a name can go
months without one), binary-ish (upgrade/downgrade loses the *size* of the estimate change),
lag the estimate changes themselves, and coverage thins badly pre-2023 and for smaller names
(uncovered names get ERM = NaN and are scored on RS alone via per-name weight renormalisation,
scoring.py:207-214).

**Status (as of 2026-07-11).** The walk-forward ablation showed ERM+RS *cut* out-of-sample
CAGR roughly in half vs RS-only (~34% → ~16%) — so ERM was removed from the default signal
(rule R3 in action; README.md:16-18). It remains opt-in via the `ermrs` flag. The clean
re-test path: `weekly.take_snapshot` (weekly.py:40-56) banks the *current* consensus +
revision counts (`estimates.snapshot`, estimates.py:112-145) to `data/snapshots/
estimates_<date>.csv` every week, accumulating a TRUE point-in-time revision series; after
~1 year of snapshots, re-run the ablation on real revisions. Details of the cut:
`allocator-failure-archaeology`; the re-test plan: `allocator-research-frontier`.

**What people get wrong.** Treating "ERM failed" as "estimate revisions don't work". What
failed is the *grade-action proxy on thin history*. The hypothesis is unresolved until the
banked-snapshot re-test — but per R3 it stays out of the default until evidence says otherwise.

---

## 11. Book construction: anchors, satellites, Extension, exits, catch-rate

**Anchor/satellite.** Two return profiles (classifier.py:47-85, cuts in config.yaml:45-51):
- **ANCHOR** ("obvious"): WinnerScore ≥ 80 **and** Extension ≥ 65 — a confirmed, liquid,
  already-trending leader. Lower variance. Score-weighted, capped 20%/name, max 15 names.
- **SATELLITE** ("non-obvious"): WinnerScore ≥ 75, Extension ≤ 40, **and** ERM strong
  (≥ 60, falling back to WinnerScore when ERM is absent — classifier.py:60-61) — high score
  *before* the trend is obvious. Higher variance; vol-scaled 1/ATR%, capped 5%/name, max 6.
- **WATCH**: everything else.

**Extension ("obviousness")**, 0–100 (classifier.py:32-44): mean of RS percentile and an
ADV-size percentile (20-day average dollar volume as the size/liquidity proxy). The spec's
valuation percentile is omitted without an FMP key — flagged in the notes. High extension =
everyone already knows; low = early. Practical consequence: with RS-only scoring, high score
and low extension are nearly contradictory (RS is inside Extension), so **the satellite bucket
is usually empty in RS-only mode** — which caused the ~40% cash-drag bug, fixed by folding the
idle satellite budget into anchors (sizer.py:89-98). Story: `allocator-failure-archaeology`.

**Stops and trim ladders** (exits.py:41-65, config.yaml:60-64) — pre-committed at entry,
*before* emotion, because of the OKLO +250%→flat round-trip lesson. Instructions for R, never
auto-orders (rule R2):
- Hard stop: `entry − 2.5 × ATR` (thesis invalidation, scaled to the name's own volatility).
- Trim ladder: sell 1/3 at +50%, another 1/3 at +100%, let the runner ride.
- Trail: once in profit, trail at 3 × ATR.
- Catalyst de-rate-on-slip: dated events from `data/catalysts.csv` get a warning flag (the
  TTWO catalyst-slip lesson).

**Catch-rate** (`backtest.catch_rate`, backtest.py:216-243). For each calendar year: take the
year's actual top-10 performers among that year's universe, and ask how many the strategy
**already held at the year's first rebalance** — i.e. before the move. Measured result: 0–20%.
Read honestly, that number says this system **rides trends; it does not call turns**. Nearly
none of a year's biggest winners are in the book on Jan 1 — the strategy climbs aboard
mid-move once momentum confirms (a mid-year buy of a winner scores zero here). The returns
come from riding confirmed trends with sizing and exits, not from prediction. Quoting the CAGR
without this context oversells what the signal is.

---

## 12. GBP book mechanics: FX conversion and fractional shares

The book is £10,000 GBP base, buying US-listed (USD) names via IBKR (config.yaml:4-7).
Sizing math (sizer.py:125-135):
```python
gbp    = target_weight * book_gbp
shares = round(gbp * fx / price_usd, 4)    # fx = fx_gbp_usd = 1.27 (config.yaml:7)
```
`fx_gbp_usd` is GBP→USD: £1 buys $1.27, so `gbp * fx` is the position in USD, divided by the
USD price. It is a **static config constant, not a live FX quote** — share counts are
approximate by design (the notes say so), and R trues them up at order entry. Fractional
shares (4 dp) are essential: a 5% satellite of a £10k book is £500 ≈ $635 — under one share
of many $700+ names; IBKR supports fractional orders. Backtest returns are computed in USD
price terms and ignore FX entirely (backtest.py holds no currency leg) — GBP only enters at
the live order-instruction stage.

**What people get wrong.** Inverting the FX rate (dividing by 1.27 instead of multiplying),
and expecting backtest P&L to include GBP/USD moves — it doesn't; currency risk on the live
book is real but unmodelled (open issue; see `allocator-research-frontier`).

---

## Provenance and maintenance

All claims verified against the repo on **2026-07-11** (branch claude/skill-library-handoff-vm2gku).
Line numbers drift with edits — re-verify with:

| Fact | Re-verify |
|---|---|
| RS features / percentile ranking | `grep -n "_rs_features\|_pct_rank\|rank(pct=True)" src/allocator/scoring.py` |
| ~21 trading days/month | `grep -n "months \* 21" src/allocator/data/prices.py` |
| Wilder ATR (ewm alpha=1/window, adjust=False) | `grep -n "ewm(alpha" src/allocator/data/prices.py` |
| √252 annualisation | `grep -n "sqrt(252)" src/allocator/data/prices.py` |
| Costs: two-way turnover × 8 bps/side | `grep -n "costs_bps\|turn \* costs" src/allocator/backtest.py config.yaml` |
| Metrics formulas (median/DD/Sortino/Sharpe/hit) | read `src/allocator/backtest.py` `def metrics` |
| Catch-rate definition | read `src/allocator/backtest.py` `def catch_rate` |
| Kelly tilt: edge=(score−50)/50, clip 0.5–1.5, kf=0.25 | `grep -n "_kelly_tilt\|kelly_fraction" src/allocator/sizer.py config.yaml` |
| Cash-drag fold (satellite budget → anchors) | `grep -n "fold\|satellite budget" src/allocator/sizer.py` |
| Regime triggers (below-200dma, 21d spread z>1.5, breadth .55) | read `src/allocator/regime.py` rule layer; `grep -n "1.5" src/allocator/regime.py` |
| BAA10Y substitution for HY OAS | `grep -n "BAMLH0A0HYM2\|BAA10Y" src/allocator/data/fred.py config.yaml` |
| Cuts A/S/E_hi/E_lo, budgets, caps, exits | read `config.yaml` |
| Delisted overlay contents (5 names) | `cat data/delisted.csv` |
| Tune/validate windows | `grep -n "tune_window\|validate_window" config.yaml` |
| ERM cut + headline numbers (+34%/−16% vs +41%/−21%) | `grep -n "34\|ERM" README.md config.yaml` |
| Snapshot banking path | `grep -n "estimates_" src/allocator/weekly.py` |

Volatile facts to re-check on touch: the delisted overlay grows over time; the ERM re-test
lands when ~1 year of snapshots is banked (from mid-2026); `max_anchors`/top-N and the
regime-gate dial may be re-swept — treat config.yaml as the source of truth over any number
quoted here.
