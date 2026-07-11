---
name: survivorship-bias-campaign
description: >
  EXECUTABLE, decision-gated campaign to fix the Asymmetric Allocator's #1 credibility gap:
  the backtest universe is TODAY'S S&P 500 members plus a 5-name delisted overlay, so every
  published number is an admitted upper bound. This skill is the full battle plan — numbered
  phases with exact commands, expected observations at every gate ("if you see X instead →
  branch"), a ranked solution menu, fenced-off wrong paths, and the promotion protocol.
  Load when: asked to "fix survivorship bias", "build a point-in-time universe", "make the
  backtest honest", extend data/delisted.csv, parse historical S&P 500 membership changes,
  or evaluate whether the +34% CAGR is real. The single most valuable multi-session project
  in this repo.
---

# Survivorship-Bias Campaign

**Mission:** replace "current members + 5 dead names" with membership-accurate point-in-time
S&P 500 constituents for 2020–present, re-run the walk-forward, and publish the honest
numbers — whatever they are.

**Prime expectation, fixed before you start (hypothesis-predicts-numbers,
`allocator-research-methodology`):** headline CAGR should **DROP** when membership is honest
— the current universe omits 2020–2026 index departures (mostly losers) that a momentum
book could have held on the way down. **If honest CAGR goes UP, treat it as a bug in your
membership data until proven otherwise.** A plausible outcome is a drop of a few CAGR
points with a similar or deeper max drawdown; the strategy beating the S&P should survive —
if it doesn't, that is a publishable finding too (rule R4: report it).

Evidence for the current state (verified 2026-07-11): `README.md` Limitations #1;
`src/allocator/universe.py:1-7` docstring; `data/delisted.csv` = SIVB, FRC, ATVI, SGEN,
SPLK only; honesty banner `src/allocator/backtest.py:250-260`.

When NOT to use: other research problems → `allocator-research-frontier`; general evidence
rules → `allocator-validation-and-qa`.

## Solution menu (ranked)

| # | Approach | Fidelity | Cost | Obligation before trusting |
|---|---|---|---|---|
| 1 | Parse Wikipedia's "Selected changes to the list of S&P 500 components" table (same page constituents.py already scrapes) into dated add/remove events; reconstruct membership intervals backwards from today | High for membership; limited by price availability for departed names | Free, ~1–2 sessions | Structure-validate the parse (Phase 1 gate); cross-check counts (Phase 2 gate) |
| 2 | Manually extend `data/delisted.csv` from the same table (top ~30 departures by size) | Medium — bounds the bias, doesn't remove it | Free, hours | State it's a partial overlay, not PIT membership |
| 3 | Community GitHub datasets of historical constituents | Unknown freshness/accuracy | Free | Diff against approach 1 output; never trust unaudited |
| 4 | Paid PIT membership (CRSP/Compustat/Norgate) | Gold standard | £££ | **FENCED OFF** — violates the free-data constraint. Note only as the ceiling |

Approach 1 is the campaign. Approach 2 is the fallback if Phase 1/2 gates fail repeatedly.

**Wikipedia table status:** the changes table's existence and rough structure (multi-level
header: Date / Added Ticker / Added Security / Removed Ticker / Removed Security / Reason;
coverage back well before 2020) is well-established but was NOT live-verified during
authoring (the authoring container's proxy blocked wikipedia.org, 2026-07-11). **Phase 1
verifies it before anything else is built.**

## Phase 0 — Baseline (do not skip)

Prerequisites: FRED key in .env, price cache filled (`scripts/fetch_universe.py` then
`price_coverage.py` ≥ ~90%).

```bash
python scripts/run_backtest.py rs   | tee baseline_backtest.txt
python scripts/sweep.py             | tee baseline_sweep.txt
```

**Gate G0:** headline ≈ the goldens in `allocator-validation-and-qa` §3 (RS regime ~+34%
CAGR / ~−16% maxDD as of 2026-07-11; drifts with new months). If wildly off → your
environment is broken; fix via `allocator-debugging-playbook` before proceeding. Record the
exact numbers — every later comparison is against THESE, on THIS cache, not the README.

## Phase 1 — Acquire and parse the changes table

The constituents scraper (`src/allocator/data/constituents.py`) already fetches
`https://en.wikipedia.org/wiki/List_of_S%26P_500_companies` and reads `tables[0]`. The
changes table should be `tables[1]`. Working sketch (structure-validate before trusting —
written from documented structure, verify on first run):

```python
import io, requests, pandas as pd
r = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                 headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
tables = pd.read_html(io.StringIO(r.text))
chg = tables[1]
# multi-level header -> flatten
chg.columns = ["_".join(str(c) for c in tup).lower() for tup in chg.columns]
print(len(tables), list(chg.columns), len(chg))
```

**Gate G1 (structure validation):** a date-like first column parseable with
`pd.to_datetime`; distinct added-ticker and removed-ticker columns; ≥ 1 row per month on
average since 2020 (S&P changes run ~20–50/yr). **If instead** `len(tables) < 2` or columns
don't match → Wikipedia restructured the page: dump `[t.columns for t in tables]`, find the
changes table by content (columns containing "Added"/"Removed"), and pin by content not
index. **If the page is unreachable** → check network/proxy first, and fall back to
approach 3 ONLY as a cross-check source, never sole truth.

Persist: `data/sp500_changes.csv` with columns
`date, added_ticker, added_name, removed_ticker, removed_name, reason` (dots→dashes like
constituents.py does). Filter to `date >= 2019-06-01` (6 months before backtest start, so
the first rebalance has correct membership).

## Phase 2 — Reconstruct membership intervals

Walk BACKWARDS from today's membership (`data/sp500_constituents.csv`, ~503 names): at each
change event going back in time, reverse it (an "added" name was NOT a member before its
date; a "removed" name WAS). Output `data/sp500_membership.csv`:
`ticker, start_date, end_date` (end_date empty = still a member).

**Gate G2 (sanity counts):** membership count at 2020-01-01, 2022-01-01, 2024-01-01 must be
**500–510** (the index holds ~503 tickers due to share classes). **If** count drifts
monotonically away from ~503 as you walk back → you're applying events in the wrong
direction or double-counting ticker renames; **if** a handful of names appear twice →
ticker changes (e.g. FB→META) — treat renames as the same instrument, keyed by the change
table's reason column. Spot-check 5 known events against the table (e.g. TSLA added
2020-12-21, PLTR added 2024-09-23 — the latter already in `data/catalysts.csv`).

## Phase 3 — Wire in behind a flag (design; route via change control)

Add `universe.source: sp500_pit` handled in `universe.py`: `candidate_set(as_of)` returns
names whose `[start_date, end_date]` interval contains `as_of` (union with the existing
delisted overlay for names that left the EXCHANGE, not just the index). Keep `sp500`
(current behavior) untouched as the fallback. This is a behavior change → the full
`allocator-change-control` gate applies; do not flip the default until Phase 5 passes.

**Gate G3:** with the flag ON, `universe.build_universe("2021-06-30")` returns a set that
(a) differs from the current-members run, (b) still passes the <50-name guard by a wide
margin, (c) includes at least one name that later left the index.

## Phase 4 — Measure price coverage for departed names (the honest limit)

Departed names are exactly where free price data thins (stooq/yfinance often drop delisted
tickers). Measure, don't assume:

```bash
python scripts/refresh_prices.py     # attempt to fill, non-destructive
python .claude/skills/allocator-diagnostics-and-tooling/scripts/price_coverage.py
```

plus a one-off count of coverage among ONLY the departed names.
**Gate G4:** record `X of Y departed members have usable prices`. **Expect meaningful
gaps.** Names without prices drop out of universe[t] exactly as today (ADV filter) — the
residual bias MUST be quantified and stated: "membership-accurate; N departed names
(Z% of departures) unpriceable and excluded". **If** coverage of departures is very low
(<~40%), the campaign result is still valuable but the claim ceiling drops — say so in the
writeup; do NOT backfill prices from questionable sources to force coverage.

## Phase 5 — Re-run and compare (the payoff gate)

```bash
# flag ON via config, same cache, same window
python scripts/run_backtest.py rs | tee pit_backtest.txt
python scripts/sweep.py           | tee pit_sweep.txt
```

Deliverable table (this IS the result — never judged by eye):
| metric | current universe (G0) | PIT universe | delta |
with CAGR, maxDD, Sortino, median annual, per-year rows, for gate-on and gate-off.

**Gate G5:** CAGR drops (expected) → proceed to promotion. **If CAGR rises** → hunt the bug:
most likely membership intervals wrong (names present that shouldn't be) or departed losers
excluded by missing prices (check the Phase 4 number — that's the mechanism by which the
"honest" run can still be flattered). **If the strategy no longer beats the S&P
out-of-sample** → that is the finding; publish it with the same rigor (R4), and the README
headline changes accordingly. Adversarial-refutation pass required either way
(`allocator-research-methodology`).

## Phase 6 — Promotion

Through `allocator-change-control`: flip `universe.source` default → `sp500_pit`; update
README numbers + Limitations #1 (from "survivorship bias: upper bound" to
"membership-accurate; residual price-coverage bias: N names excluded, quantified");
rewrite `backtest.caveat_banner` to match reality; update `allocator-validation-and-qa`
goldens; add the campaign outcome to `allocator-failure-archaeology` (closing item O7).
Never delete the old path until one full weekly cycle runs green on the new one.

## Fenced-off wrong paths

- **Re-tuning thresholds to claw back the lost CAGR** — violates R1/R3. The honest number
  is the deliverable, not a target to defend.
- **Keeping the old universe as silent default after the honest one works** — the whole
  point is the default becomes honest.
- **Treating unpriceable departures as zero-return holdings** (or any imputation) without a
  separate justified analysis — exclusion + disclosure is the default handling.
- **Claiming "survivorship-free"** — the ceiling claim is "membership-accurate,
  price-coverage-limited". Full freedom needs paid data (menu #4).
- **Buying data** — fenced by the free-data constraint (see `allocator-docs-and-claims`).

## Provenance and maintenance

Written 2026-07-11. Repo anchors verified; baseline numbers inherited from README/sweep
(drift with new months — always re-run Phase 0). Wikipedia changes-table structure NOT
live-verified at authoring time (proxy-blocked); Phase 1's gate exists precisely for this.
Re-verify on touch:
- delisted overlay still 5 names: `wc -l data/delisted.csv`
- universe source options: `grep -n "source" config.yaml src/allocator/universe.py`
- constituents scraper table index: `grep -n "read_html" src/allocator/data/constituents.py`
- campaign not yet executed: `ls data/sp500_changes.csv data/sp500_membership.csv 2>&1`
  (errors = not started)
