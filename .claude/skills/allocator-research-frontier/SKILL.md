---
name: allocator-research-frontier
description: >
  The open problems where the Asymmetric Allocator can genuinely advance its state of the
  art, ranked by leverage: true point-in-time universe, ERM re-validation on the self-banked
  snapshot dataset, live-vs-backtest reconciliation, regime-gate improvement, satellite
  sleeve activation, and the unimplemented FI/EXP/CAT/THM sub-scores. Each problem states
  why the current state fails, this repo's specific asset, the first three concrete steps
  IN THIS REPO, and a falsifiable "you have a result when…" milestone. Load when: choosing
  what to research next, "what should we work on", "can we improve returns", proposing a
  new signal or data source, or scoping a multi-session research effort. All items are
  OPEN/candidate — nothing here is validated.
---

# Allocator Research Frontier

Everything below is **open**. Nothing here may be described as working until it clears the
lifecycle in `allocator-research-methodology` and the gates in `allocator-change-control`.
Ranked by leverage (credibility first, then return). Anchors verified 2026-07-11.

When NOT to use: executing the flagship problem → `survivorship-bias-campaign`; the
research discipline itself → `allocator-research-methodology`; analysis mechanics →
`allocator-proof-and-analysis-toolkit`.

## F1. True point-in-time universe (the flagship)

**Why the current state fails:** results are an admitted upper bound (README Limitation #1);
no free-data project publishes honest PIT-membership backtests, which is exactly why doing
it is differentiating.
**Asset:** the constituents scraper already parses the Wikipedia page that also carries the
dated changes table; the delisted-overlay mechanism already exists.
**First three steps + gates:** fully specified in `survivorship-bias-campaign` — go there;
this entry exists only for ranking.
**You have a result when:** the campaign's Phase 5 table exists (current vs PIT universe,
same cache/window) with the residual price-coverage bias quantified. Either direction of
the delta is a result.

## F2. ERM re-validation on the self-banked snapshot dataset

**Why current SOTA fails:** free estimate data is CURRENT consensus only (`fmp.py`
docstring); historical point-in-time estimates cost real money; the grade-action proxy
already failed its ablation (34→16 CAGR, `allocator-failure-archaeology` A1).
**Asset — the moat:** `weekly.take_snapshot` banks true PIT consensus weekly into
`data/snapshots/estimates_<date>.csv` with fields (verified in `estimates.snapshot`):
eps_0y/1y, eps_1y_growth, eps_1y now/30d/90d, up_30d/down_30d, up_7d/down_7d,
rec_strongBuy…rec_strongSell. Nobody can buy this dataset retroactively — it only exists
because the job has been running.
**First three steps:** (1) inventory the bank: count files, date span, names/row per file
(if thin — see O5/O6 in `allocator-failure-archaeology`: only the Windows task banks; fix
that first or the clock never runs); (2) define snapshot-ERM = cross-sectional percentile
of (up_30d − down_30d)/coverage + eps_1y 30d revision %, computed ONLY from banked rows
≤ as_of; (3) shadow-score: log snapshot-ERM alongside RS each weekly run WITHOUT touching
the book (a new column in the scored frame, report-only).
**You have a result when:** ≥ 52 weekly snapshots spanning ≥ 12 months AND a walk-forward
ablation over the banked period where snapshot-ERM+RS beats RS-only on validate-style
metrics (Sortino AND maxDD, not just CAGR). Anything less → ERM stays retired.

## F3. Live-vs-backtest reconciliation

**Why it matters:** a backtest that never meets its live shadow is unfalsifiable; the 8bps
cost assumption and monthly-close fills have never been checked against reality.
**Asset:** every run banks the full book to `reports/history/alloc_<date>.json`
(`weekly.save_run`) — weights, GBP, buckets, dated.
**First three steps:** (1) script: replay each saved book forward to the next book's date
using cached prices (same `_price_at` convention as the backtest) → realized book return
series; (2) compare against the backtest's contemporaneous months (same regime verdicts?
same magnitude?); (3) track the gap components: timing (weekly books vs monthly rebalance),
cost assumption, stop/trim executions R actually made vs the model's buy-and-hold-to-next-
rebalance assumption — that last one is the big unmodeled gap: **the backtest does not
simulate the M7 stops/trims at all** (verify: nothing in `backtest.run_strategy` reads
`exits`), while live R is instructed to use them.
**You have a result when:** ≥ 6 months of books with a realized-vs-modeled return table and
a stated tracking error; bonus result: the first honest estimate of what the exit rules
add/cost (which would itself feed Recipe 1 ablation).

## F4. Regime-gate improvement (tread carefully)

**Why naive improvement fails:** regime models overfit spectacularly — 2020–2026 contains
only ~3 regime episodes; any gate tuned to them is memorization.
**Asset:** the gate's value is already measurable (gate on/off ablation exists: ~34/−16 vs
~41/−21 as of 2026-07-11), so any variant has a clean baseline; verdict components are
logged per date (`RegimeResult.components`).
**First three steps:** (1) dump per-date verdicts + components across the backtest into a
CSV; (2) measure transition timing vs the S&P's actual drawdowns (how late was each
COMPRESSION call? how early each re-entry?); (3) sweep ONE threshold (e.g.
`breadth_riskon`) on the TUNE window only, robust-pick rule.
**You have a result when:** validate-window maxDD improves while giving up LESS CAGR than
the current gate's known cost (the 34-vs-41 spread). A variant that wins CAGR by dropping
the gate's crash protection is a regression, not a result.

## F5. Satellite sleeve activation

**Why it's dormant:** satellites require a validated "non-obvious" signal (that was ERM's
job — `classifier.py` gates satellites on ERM strength); with RS-only the bucket is empty
and its budget folds into anchors (`sizer.py:95-98`).
**Asset:** the whole sleeve machinery (vol-scaled sizing, caps, designed-winner tags)
already exists and is tested by construction; it just has no signal feeding it.
**Blocked by:** F2 — snapshot-ERM is the natural satellite driver. Do F2 first.
**You have a result when:** F2 passes AND an ablation shows the satellite sleeve
(RS anchors + snapshot-ERM satellites) beats anchors-only on Sortino at equal-or-better
maxDD.

## F6. The unimplemented sub-scores (FI / EXP / CAT / THM)

**Status:** config weights reserved (`allocator-config-and-flags` §1); data stubs exist
(FI: `finnhub.basic_financials`; CAT: `data/catalysts.csv` — read by exits for slip flags
but NOT scored; THM: `data/theme_tree.yaml` — no reader at all, verified; EXP: needs FMP
valuation fields).
**Why SOTA fails / why this might:** each is a well-known factor family; the edge, if any,
is in the regime-conditional blending the config already sketches (EXP up-weighted in
COMPRESSION), not the factor itself.
**First three steps (per sub-score):** (1) implement as a scoring.py sub-score returning a
0-100 percentile Series (the RS/ERM pattern); (2) run the Recipe 1 ablation RS vs
RS+NEW; (3) only on a pass, add to `active` behind a flag.
**You have a result when:** any ONE survives the same ablation bar that killed ERM. The
prior is that most won't — budget accordingly.

## How to claim a frontier result

Hypothesis with predicted numbers first → tune-window experiment → single validate look →
adversarial refutation → promotion or documented retirement. The full discipline:
`allocator-research-methodology`. The merge gate: `allocator-change-control`. Anything
claimed externally: `allocator-docs-and-claims`.

## Provenance and maintenance

Written 2026-07-11. Snapshot fields read from `estimates.snapshot`; the
backtest-ignores-exits observation verified by reading `backtest.run_strategy` (no exits
import/use). Ranking is judgment, dated today. Re-verify on touch:
- snapshot bank size: `ls data/snapshots/ | wc -l` (on the machine that runs Mondays)
- theme_tree still unread: `grep -rn theme_tree src scripts webapp.py`
- backtest still exit-blind: `grep -n exits src/allocator/backtest.py` (no hits = still true)
- satellite gate on ERM: `grep -n erm_strong src/allocator/classifier.py`
- gate cost baseline: `python scripts/sweep.py` (needs keys/cache)
