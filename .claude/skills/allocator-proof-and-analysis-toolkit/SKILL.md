---
name: allocator-proof-and-analysis-toolkit
description: >
  First-principles analysis recipes for the Asymmetric Allocator — "prove it, don't just
  install it". Each method is a step-by-step recipe with a worked example from this repo's
  real history: ablation studies (worked: the ERM cut), out-of-sample sweeps with the
  robustness pick (worked: n15 concentration), point-in-time audits against look-ahead
  leaks, cash-drag accounting (worked: the 40% idle-sleeve bug), metric derivations
  (CAGR/maxDD/Sortino/turnover cost from scratch), and the Kelly-tilt's honest status.
  Load when: designing an experiment to isolate a rule's value, auditing new code for
  look-ahead bias, decomposing an unexpected return number, deriving or checking a metric
  by hand, or reviewing whether an analysis actually proves what it claims.
---

# Allocator Proof and Analysis Toolkit

Recipes for producing evidence, each with the worked example that made it house method.
When NOT to use: what evidence is REQUIRED to merge → `allocator-validation-and-qa`;
running the tools → `allocator-diagnostics-and-tooling`; the full idea lifecycle →
`allocator-research-methodology`. All code anchors verified 2026-07-11.

## Recipe 1 — Ablation study (isolate one rule's worth)

**When:** any proposed signal, rule, or behavior change.
**Method:** run matched strategy pairs identical except for the one rule, through the same
walk-forward, and read the delta. The unit of comparison is a `Strategy` dataclass
(`src/allocator/backtest.py:34-41`): `name, active (sub-score tuple), top_n, weighting
("score"|"equal"), use_regime (bool)`.

Steps:
1. Define the pair, e.g. `Strategy("RS+NEW (regime)", ("RS","NEW"), use_regime=True)` vs
   the existing `Strategy("RS-only (regime)", ("RS",), use_regime=True)`.
2. Add both to a suite and run `backtest.run_suite(cfg, suite=[...])` (pattern:
   `scripts/run_backtest.py`).
3. Read the ablation delta on the FULL window first, then — once, when deciding — the
   validate window (`sweep.win_metrics` pattern in `scripts/sweep.py:18-23`).
4. Judge on CAGR delta AND maxDD AND Sortino together; a CAGR gain bought with deeper
   drawdown fails the house bar.

**Worked example — the ERM cut:** suite `default_suite()` pairs "ERM+RS (regime)" against
"RS-only (regime)". Out-of-sample, adding ERM cut CAGR 34% → 16% (`scripts/weekly_run.py:9-10`).
Decision: ERM removed from the default `active` tuple, kept as the `ermrs` opt-in. The
spec's anchor signal lost to its own ablation — that's the method working.
**Failure mode of skipping:** you ship a plausible-sounding rule that quietly costs half
the return, and nobody can say which rule did it.

## Recipe 2 — Out-of-sample sweep with the robustness pick

**When:** choosing a parameter value (top_n, thresholds, gate on/off).
**Method** (from `scripts/sweep.py`, verified): run every variant over the full
walk-forward; score each on the TUNE window (2020–2023) and the VALIDATE window
(2024–2026) separately; the pick = **best validate Sortino among variants whose tune
Sortino ≥ the median of all variants**.

Why the two-sided rule: picking the best validate performer alone re-fits the test set —
the tune-side filter demands the variant was already good before the out-of-sample look.
Budget: the validate window is read ONCE per question (rule R1); iterate on tune only.

**Worked example — concentration:** n ∈ {8,12,15,20} × gate on/off. n15 won the robust
pick and became `cuts.max_anchors: 15` (`config.yaml:50`).
**Failure mode:** "n8 had the best validate CAGR!" — and the worst tune Sortino; adopting
it is fitting noise.

## Recipe 3 — Point-in-time audit (hunt look-ahead)

**When:** ANY new feature that reads data; any suspicious backtest jump.
**Method:** trace every data access in the new path to an explicit `<= as_of` cut. The
repo's choke points (all verified):
- prices: `fetch_ohlcv(..., end=as_of)` slicing `history()` (`prices.py:143-159`)
- macro: `_zscore_at/_level_at/_change` all filter `series.index <= as_of` (`regime.py:39-61`)
- grades: ERM filters `d > as_of → skip` (`scoring.py:125-127`)
- universe: delisted overlay `delist_date >= as_of` (`universe.py:59`)
- rebalance loop: only `dates[i]` data builds weights held to `dates[i+1]` (`backtest.py:132-157`)

Checklist for new code: (1) every Series/DataFrame filtered to ≤ as_of BEFORE any
statistic; (2) no "current" API field used for a historical date (the FMP consensus trap —
`fmp.py` docstring); (3) rolling windows use only trailing data (`min_periods` set); (4) no
global fit (a percentile rank at t must rank within universe[t], not all history).

**Known disclosed violations** (approximations, not bugs — never silently add more):
market cap = CURRENT shares × as-of price (`universe.py:78-81`); sector labels are current;
membership survivorship (see `survivorship-bias-campaign`).
**Failure mode:** a leaked feature backtests brilliantly and dies live. A sudden
implausible improvement IS the symptom — audit before celebrating.

## Recipe 4 — Cash-drag accounting (decompose deployment)

**When:** returns lag expectations; after any sizer/budget change.
**Method:** portfolio return = Σ(sleeve weight × sleeve return) + cash × 0. Compare
INTENDED deployment (regime budget) against ACTUAL (`1 − alloc.cash_weight`, printed by
every weekly run: "deploy NN%" — `scripts/weekly_run.py:60`).

**Worked example — the 40% idle-sleeve bug:** RISK_ON budget is anchor 45 / satellite 40 /
cash 15. RS-only produces zero satellites, so actual deployment was 45%, not 85%. At the
strategy's return level, ~40% of the book earning 0% cost roughly a dozen CAGR points —
found by comparing the printed deploy% to the budget, fixed by folding the empty satellite
sleeve into anchors (`sizer.py:86-98`, `allocator-failure-archaeology` A2).
**The canary lives on:** `book_diff.py` (diagnostics skill) prints deployed-% per book;
in RISK_ON gate-on it should read ~85%.

## Recipe 5 — Metric derivations (check any number by hand)

From `backtest.metrics` (`backtest.py:186-213`, verified):
- **CAGR** = `(eq_end/eq_start)^(1/years) − 1`, years = calendar days/365.25.
- **Max drawdown** = `min(eq / eq.cummax() − 1)` — worst peak-to-trough on MONTHLY points
  (intramonth drawdowns are deeper; say "monthly maxDD" when precision matters).
- **Sortino** = `mean(rets)/std(rets[rets<0]) × √12` (monthly periods; downside std only).
- **Sharpe** = `mean/std × √12` (no risk-free deduction — flag if comparing externally).
- **Turnover cost**: two-way turnover `Σ|w_t − w_{t−1}|` charged at `costs_bps=8` per side
  per rebalance; annual drag ≈ avg_turnover × 0.0008 × 12. A turnover of 0.5/month ≈
  0.5% CAGR drag — always fold into any proposed higher-frequency idea.
- **Why median annual + maxDD lead every table:** a single +150% year drags the MEAN up
  while telling you nothing about a repeatable process; median + worst-case is the
  distribution's honest summary (house rule, `backtest.py:9-11`).

## Recipe 6 — Expected-value framing for the Kelly tilt (and its honest status)

As implemented (`sizer.py:41-44`): edge = (WinnerScore − 50)/50 ∈ [−1,1]; multiplier =
`1 + 0.25 × edge`, clipped to [0.5, 1.5], applied within the sleeve then re-capped.
**Honest status:** this is a bounded heuristic MAPPING from score to size, not a fitted
Kelly estimate — no win-probability or payoff distribution is estimated. Caps and budgets
dominate by design. Do not describe it externally as "Kelly-optimal sizing"; describe it as
"a bounded quarter-Kelly-style tilt". Upgrading it to a fitted edge model is frontier work
(`allocator-research-frontier`) and must survive Recipe 1.

## Provenance and maintenance

Written 2026-07-11; every formula and anchor read from the working tree; worked-example
numbers from README/script comments (they drift as data accrues — regenerate before
quoting). Re-verify on touch:
- Strategy fields: `grep -n "class Strategy" -A 8 src/allocator/backtest.py`
- robust pick: `grep -n "tune_median" scripts/sweep.py`
- metric formulas: `grep -n "def metrics" -A 30 src/allocator/backtest.py`
- kelly clip: `grep -n "_kelly_tilt" -A 4 src/allocator/sizer.py`
- costs: `grep -n costs_bps config.yaml src/allocator/backtest.py`
