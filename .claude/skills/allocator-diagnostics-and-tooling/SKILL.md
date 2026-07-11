---
name: allocator-diagnostics-and-tooling
description: >
  How to MEASURE the Asymmetric Allocator instead of eyeballing it: interpretation guides
  for the repo's diagnostic scripts (smoke_data.py, test_regime.py, test_scoring.py,
  run_backtest.py output anatomy, sweep.py output anatomy) plus four ready-to-run tools
  shipped in this skill's scripts/ dir — cache_stats.py (cache inventory per namespace),
  price_coverage.py (universe price-cache coverage and staleness), book_diff.py (diff saved
  weekly books), config_lint.py (config.yaml sanity gates). Load when: checking system
  health, "is the cache OK", "how fresh are prices", "what changed between books", "is the
  config sane", reading backtest/sweep output, or before/after any data refresh. Not a
  failure-triage guide (allocator-debugging-playbook) and not the acceptance-standards doc
  (allocator-validation-and-qa).
---

# Allocator Diagnostics and Tooling

Rule of the house: **numbers, not vibes.** Health is measured with the tools below; results
come from `backtest.metrics` / sweep output with the window stated (see
`allocator-validation-and-qa` for what counts as evidence).

All tools verified by execution 2026-07-11 (empty-cache container: each degrades gracefully).

When NOT to use: a run is FAILING (not just unmeasured) → `allocator-debugging-playbook`;
what result is good enough → `allocator-validation-and-qa`.

## 1. Shipped tools (this skill's scripts/ dir)

Run from the repo root with the repo's python (editable install required — see
`allocator-build-and-env`). None touch the network or need API keys.

### cache_stats.py — what's in the cache?
`python .claude/skills/allocator-diagnostics-and-tooling/scripts/cache_stats.py`

Prints files/MB/oldest/newest per namespace. Interpretation:
| Namespace | Meaning | Healthy look |
|---|---|---|
| `prices` | permanent full-history OHLCV per ticker | ~500 files after bootstrap; "newest" ≈ last refresh |
| `prices_neg` | 6h-TTL "no data" markers | few; MANY after a run = provider rate-limited that run |
| `fred` | macro series (cleared each weekly refresh) | small; recent |
| `yf_grades` | dated analyst actions (cleared each weekly refresh) | present only after ERM/backtest runs |
| `fmp_*`, `fh_*` | FMP/Finnhub responses | only with keys |

### price_coverage.py — can a book actually be built?
`python .claude/skills/allocator-diagnostics-and-tooling/scripts/price_coverage.py [--stale-days N]`

Coverage of the CONFIGURED universe (reads `universe.source` from config) against the disk
cache only. Interpretation: coverage <90% after a refill = provider trouble (see
`allocator-debugging-playbook`); a run against stale bars (> 7d) produces a stale book —
`weekly_run.py` refreshes automatically unless `norefresh` was passed. Coverage below ~10%
of the universe would trip weekly_run's <50-name abort.

### book_diff.py — what changed between any two weekly books?
`python .claude/skills/allocator-diagnostics-and-tooling/scripts/book_diff.py` (list runs)
`python ... book_diff.py 2026-06-19 2026-06-26` (diff)

Reads `reports/history/alloc_<date>.json`. Shows BUY/SELL/ADD/TRIM (±0.5pt threshold, same
as `weekly.diff_vs_prev`) and the deployed-% change. **Deployed % is the cash-drag canary**:
in RISK_ON with the gate on it should be ~85% (anchor .45 + satellite .40); materially less
means a sleeve is idle — the A2 bug class in `allocator-failure-archaeology`.

### config_lint.py — is the config self-consistent?
`python .claude/skills/allocator-diagnostics-and-tooling/scripts/config_lint.py` (exit 1 on FAIL)

Gates: no string-typed numerics (the PyYAML `1.5e9` trap), base weights sum to 1, every
regime budget sums to 1, `A_cut ≥ S_cut`, `E_hi > E_lo`, caps sane, trim ladder ordered,
tune/validate windows non-overlapping and inside start/end. Run it after ANY config edit
and in any future CI test step.

## 2. Repo diagnostics — interpretation guides

### scripts/smoke_data.py — data-layer end-to-end
Sections: (1) stooq/yfinance prices + indicators for NVDA; (2) RS spread NVDA vs ^SPX;
(3) universe[t] at three dates with ADV filter; (4) which keys are present; (5)+(6) FRED/FMP
light calls if keys exist. **Known bug (O1):** section 5 calls `fetch_named("hy_spread")` —
not a key in `fred.SERIES` — so it KeyErrors when a FRED key IS present. Sections 1–4 are
still trustworthy; treat a section-5 crash as the known bug, not a data problem.

### scripts/test_regime.py — regime-gate golden pattern
Prints verdict/score/components for fixed dates. Expected (the golden pattern, from the
script header): 2022 quarter-ends → COMPRESSION; 2023-06-30, 2023-12-29, 2025-02-28 →
RISK_ON; 2025-06-02 borderline. Deviations mean: FRED data missing (check key), price cache
gaps (breadth NaN), or a genuinely changed threshold — diff `config.yaml regime:` first.
Requires FRED key + price cache.

### scripts/test_scoring.py — winner recall
Scores the universe as of Dec-2022 and Dec-2023; the top-10 should contain known next-year
winners (2023: NVDA/META/AMD/PLTR/CRM/TSM/AVGO; 2024: NVDA/VST/PLTR/AVGO/GEV/CEG/AMZN —
from the script's CASES). Also prints ERM coverage n/total: thin coverage pre-2023 is
EXPECTED (the A1 story). Zero recall = scoring broke; partial recall is normal (momentum
catches 0–20% of top movers early — see `quant-domain-reference`).

### scripts/run_backtest.py output anatomy
1. **Headline table** — read `medANN` and `maxDD` FIRST (house rule), then CAGR. `turn` is
   two-way turnover per rebalance (cost drag = turn × 8bps).
2. **ABLATION deltas vs S&P** — what each rule is worth; a variant whose delta is negative
   fails rule R3 for adoption.
3. **PER-YEAR RETURNS** — look for one great year masking bad ones (that's why median leads).
4. **CATCH-RATE** — % of each year's top-10 movers already held at the year's first
   rebalance. 0–20% is the honest historical range; do not promise better.
5. **HONESTY BANNER** — must always print; results are a survivorship upper bound.

### scripts/sweep.py output anatomy
Columns: TUNE window metrics | VALIDATE window metrics | FULL CAGR, per variant
(n8/12/15/20 × gate on/off). The **robust pick** = best VALIDATE Sortino among variants with
above-median TUNE Sortino — this is the only sanctioned way to spend a validate-window look
(rule R1; details in `allocator-proof-and-analysis-toolkit`).

## 3. Measurement discipline

- A claim about performance = a `backtest.metrics` / sweep number + the window + the
  survivorship caveat. Charts illustrate; they never decide.
- Before/after ANY data refresh: `cache_stats.py` + `price_coverage.py`.
- After ANY config edit: `config_lint.py`.
- After ANY weekly run: `book_diff.py` against the prior book; check the deployed-%.
- Something failing rather than measuring → `allocator-debugging-playbook`.

## Provenance and maintenance

Written 2026-07-11. The four shipped scripts executed clean in an empty-cache Linux
container (exit 0; config_lint reported CLEAN on the current config.yaml). Repo-script
guides verified by reading sources, not execution (no API keys here). Re-verify on touch:
- shipped scripts still run: `for s in cache_stats price_coverage book_diff config_lint; do python .claude/skills/allocator-diagnostics-and-tooling/scripts/$s.py >/dev/null && echo $s ok; done`
- smoke bug still open: `grep -n hy_spread scripts/smoke_data.py`
- golden dates unchanged: `grep -n "DATES\|CASES" scripts/test_regime.py scripts/test_scoring.py`
- robust-pick rule unchanged: `grep -n "tune_median" scripts/sweep.py`
- diff threshold: `grep -n "0.005" src/allocator/weekly.py`
