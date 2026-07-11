---
name: allocator-failure-archaeology
description: >
  The chronicle of every settled investigation, dead end, rejected fix, and open defect in
  the Asymmetric Allocator — so no session re-fights a settled battle. Load when: you are
  about to propose removing/adding something and wonder "has this been tried?"; you see a
  suspicious design (idle satellite budget, BAA10Y instead of HY OAS, RS-only default,
  session-wide stooq skip, non-destructive prefetch) and want the why; you hit a bug and
  want to know if it is a KNOWN open item; or you finished an investigation and must record
  it. Triggers: "why was ERM removed", "why not use BAMLH0A0HYM2", "why is default RS-only",
  "is this a known bug", "has anyone tried", "revert", "dead branch", "post-mortem".
---

# Allocator Failure Archaeology

The project's history lives in code comments, two commits, and three PRs — not in a long git
log. This file is the assembled chronicle. Format per entry:
**symptom → root cause → evidence → status.** Statuses: `SETTLED` (do not re-litigate
without new evidence), `OPEN` (known defect/debt, unfixed), `RE-TEST SCHEDULED` (retired,
with a defined trigger to revisit).

When NOT to use this skill: fixing a live failure right now → `allocator-debugging-playbook`.
Understanding the current design → `allocator-architecture-contract`. Deciding whether a new
change is allowed → `allocator-change-control`.

All file:line anchors verified 2026-07-11.

## SETTLED battles

### A1. ERM cut from the default book (the big one)
- **Symptom:** the spec's anchor signal (Estimate-Revision Momentum, weight 0.30 in
  `config.yaml`) made the backtest WORSE: out-of-sample CAGR fell 34% → 16% when ERM was
  blended with RS.
- **Root cause:** the free proxy (yfinance dated analyst grade actions) is thin pre-2023 and
  noisy; grade actions lag the price move RS already captures.
- **Evidence:** `scripts/weekly_run.py:9-10` ("ERM failed the backtest ablation: it cut CAGR
  34%->16%. Opt-in only."), README "What it does" section, `README.md:16-18`.
- **Status:** SETTLED as default; **RE-TEST SCHEDULED** — the weekly snapshot job
  (`src/allocator/weekly.py:40-56`, `take_snapshot`) banks true point-in-time consensus into
  `data/snapshots/estimates_<date>.csv`; a clean re-test is due after ~1 year of snapshots
  (from mid-2026). Until then RS-only is the validated book; `ermrs` flag exists for research.

### A2. The ~40% cash-drag bug ("the single biggest live-return fix")
- **Symptom:** live book deployed only ~45% in RISK_ON instead of the intended ~85%.
- **Root cause:** with RS-only there are no satellites, and the naive sleeve split left the
  entire satellite budget (40% in RISK_ON) sitting in cash.
- **Fix:** fold the satellite budget into anchors when the satellite bucket is empty.
- **Evidence:** `src/allocator/sizer.py:86-98` ("this was a real ~40% cash-drag bug"),
  `README.md:26-28`.
- **Status:** SETTLED. Any sizer change must preserve this fold (invariant in
  `allocator-architecture-contract`).

### A3. OOM on the first cloud deploy → split build/serve architecture
- **Symptom:** "Refresh" on the deployed dashboard returned nothing; the 512 MB Render free
  host ran out of memory building the S&P 500 book.
- **Fix:** GitHub Actions (16 GB runner) builds and force-pushes `latest.html` to the
  single-commit `live-report` branch; the web host only serves. Web image has NO pandas.
- **Evidence:** merged PR #3 (2026-06-30, "Phone-accessible dashboard"), `DEPLOY.md:6-23`,
  `.github/workflows/build-report.yml:3-6`, `requirements-web.txt` comment.
- **Status:** SETTLED. Never add build deps to `requirements-web.txt` (rule R6).

### A4. Destructive prefetch wiped the price cache
- **Symptom:** after a force refresh, the cache was EMPTY and every run failed — yfinance had
  rate-limited mid-refresh after the old entries were already deleted.
- **Fix:** non-destructive refresh — re-attempt all and overwrite ON SUCCESS only.
- **Evidence:** `src/allocator/data/prices.py:183-185` ("Deleting first then failing …
  wipes the cache.").
- **Status:** SETTLED. Cache ops are overwrite-on-success everywhere (rule R7).

### A5. stooq JS anti-bot challenge burned minutes per run
- **Symptom:** every ticker paid retries against an HTML interstitial `requests` can't solve.
- **Fix:** one challenge sets session-wide `_stooq_blocked = True`; stooq is skipped for the
  rest of the process.
- **Evidence:** `src/allocator/data/prices.py:59-79`.
- **Status:** SETTLED.

### A6. FRED truncated the HY OAS series → BAA10Y substitute
- **Symptom:** the spec's credit-stress series (ICE BofA HY OAS, `BAMLH0A0HYM2`) comes back
  from FRED truncated to ~3 years (ICE licensing) — useless for a 2020–2026 backtest.
- **Fix:** `BAA10Y` (Moody's Baa − 10Y Treasury): daily, full history, co-moves with HY
  stress.
- **Evidence:** `src/allocator/data/fred.py:22-26`, `config.yaml:83-84`.
- **Status:** SETTLED. Do not "fix" the regime gate by switching back to BAMLH0A0HYM2
  without first checking FRED's current coverage of it.

### A7. Daily credit-spread change false-triggered COMPRESSION
- **Symptom:** one volatile day flipped the regime to COMPRESSION.
- **Fix:** "widening fast" = the 21-day change, z-scored against its own history, > 1.5σ.
- **Evidence:** `src/allocator/regime.py:156-159`.
- **Status:** SETTLED.

### A8. PyYAML parsed `1.5e9` as a string
- **Symptom:** the market-cap filter silently compared against the string `"1.5e9"`.
- **Root cause:** YAML 1.1 requires a signed exponent for scientific notation.
- **Fix:** `1.5e+9` in config; verified 2026-07-11 (`yaml.safe_load('x: 1.5e9')` → `'1.5e9'`
  str, `'1.5e+9'` → float).
- **Evidence:** `config.yaml:12` comment.
- **Status:** SETTLED. Every new scientific-notation config number needs the signed exponent
  (checklist in `allocator-config-and-flags`).

### A9. Rate-limited feed produced a 1-name book that overwrote the good report
- **Symptom:** `reports/latest.html` showed a degenerate book after a provider outage.
- **Fix:** `weekly_run.py` aborts with exit code 2 if fewer than 50 names have price data,
  leaving the previous report in place.
- **Evidence:** `scripts/weekly_run.py:50-57`.
- **Status:** SETTLED.

### A10. Domain lessons that shaped the design (pre-repo history, recorded in docstrings)
- **ARKK study** — one −67% year erases three good ones → the regime gate exists and runs
  BEFORE stock scoring (`src/allocator/regime.py:4-6`).
- **OKLO +250% → flat round-trip** — winners round-trip without pre-committed exits → exits
  are attached at allocation time (`src/allocator/exits.py:1-3`).
- **TTWO catalyst slip** — dated catalysts that slip de-rate the thesis → the
  "DE-RATE ON SLIP" flag (`src/allocator/exits.py:8`, `data/catalysts.csv`).
- **Status:** SETTLED rationale; these are why-anchors, not tunable rules.

## OPEN items (known, unfixed as of 2026-07-11)

| # | Item | Evidence | Notes |
|---|------|----------|-------|
| O1 | `scripts/smoke_data.py` section 5 calls `fred.fetch_named("hy_spread")`; the key is `credit_spread` → KeyError when a FRED key is present | `scripts/smoke_data.py:72` vs `src/allocator/data/fred.py:19-27`; verified by import 2026-07-11 | Leftover from the A6 rename. Fix is a one-word change, route as a bug fix via `allocator-change-control` |
| O2 | `pyproject.toml` sets `testpaths = ["tests"]` but no `tests/` dir exists; there is no pytest suite at all | `pyproject.toml:14-16`; `ls tests` fails | Recipe to close: `allocator-validation-and-qa` §4 |
| O3 | `data/theme_tree.yaml` has no code reader — the THM sub-score was never implemented | `grep -rn theme_tree src scripts webapp.py` → no hits (verified) | Reserved for a future THM signal; see `allocator-research-frontier` |
| O4 | `.bat` launchers hardcode `C:\Users\ranvi\stock` | `run_site.bat:3`, `run_weekly.bat:3`, `run_weekly_scheduled.bat:4` | Breaks on any other checkout path; edit the `cd /d` line locally |
| O5 | Precious artifacts (`data/snapshots/`, `reports/history/`) are gitignored — they exist only on the machine that produced them; a disk loss loses the ERM re-test dataset | `.gitignore:11-13` | Back them up; the A1 re-test depends on the snapshot bank surviving |
| O6 | The GitHub Actions Monday build does NOT pass the `snapshot` flag — only the Windows scheduled task banks estimate snapshots | `.github/workflows/build-report.yml:52` (`noopen <mode>` only) vs `run_weekly_scheduled.bat` (`noopen snapshot`) | If the Windows box stops running, the snapshot bank silently stops growing |
| O7 | Survivorship bias: universe = current S&P 500 + a 5-name delisted overlay (`data/delisted.csv`) | `src/allocator/universe.py:1-7`, honesty banner in `backtest.py:250-260` | THE headline credibility gap; executable fix: `survivorship-bias-campaign` |

## Stalled / candidate branches (not part of the system)

- **PR #1 — GPT-picks benchmark** (open, non-draft): adds `gpt_benchmark.py` + a report hook
  comparing the allocator to published ChatGPT pick lists. Additive, unwired into the weekly
  run, based on pre-PR-#3 main. Candidate feature.
- **PR #2 — AI pick showdown tracker** (open, DRAFT): `log_picks.py` CLI + `data/ai_picks.csv`.
  Partially tested per its own checklist. Candidate feature.
- Both would need a rebase onto current main and a pass through `allocator-change-control`
  before merging.

## How to add an entry (do this every time an investigation settles)

```markdown
### A<n>. <one-line title>
- **Symptom:** what was observed, as observed.
- **Root cause:** the mechanism — one mechanism must explain ALL observations (see
  allocator-research-methodology).
- **Fix / decision:** what was done, or why nothing was done.
- **Evidence:** file:line, PR/commit, or command output (dated).
- **Status:** SETTLED | OPEN | RE-TEST SCHEDULED (with the trigger).
```

Never delete entries; supersede them ("Superseded by A<m> on <date>").

## Provenance and maintenance

Written 2026-07-11 from: repo code comments (all anchors spot-checked), `git log --all`,
GitHub PRs #1–#3, and live verification of A8/O1/O3 in a Linux container. Re-verify on touch:
- O1 still open: `grep -n hy_spread scripts/smoke_data.py`
- O2 still open: `ls tests 2>&1`
- O3 still open: `grep -rn theme_tree src scripts webapp.py`
- O6 still open: `grep -n weekly_run .github/workflows/build-report.yml`
- PR states (needs network): GitHub → pulls list for ranvirv1/asymmetric-allocator
- Line anchors drift with edits: `grep -n "cash-drag" src/allocator/sizer.py`,
  `grep -n "_stooq_blocked" src/allocator/data/prices.py`
