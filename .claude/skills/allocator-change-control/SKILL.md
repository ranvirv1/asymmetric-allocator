---
name: allocator-change-control
description: >
  Change-control law for the asymmetric-allocator repo. Load BEFORE proposing, coding, or
  merging ANY change here: editing config.yaml thresholds/weights/caps/budgets, adding or
  enabling a signal or sub-score (ERM, FI, EXP, CAT, THM), changing a data source or cache
  behaviour (prices.py, fred.py, fmp.py, estimates.py), touching exit/risk rules (exits.py,
  regime budgets, stops/trims/trails), modifying deploy/CI (build-report.yml, webapp.py,
  Dockerfile, requirements-web.txt, render.yaml), or writing docs that state performance
  numbers. Answers: what gate applies to this class of change, what evidence must exist
  before merge, how an experiment becomes the default (the ERM precedent), and the
  non-negotiable rules R1–R8 with the incident behind each. Also triggers on: "can I just
  tweak", "make ERM default", "add a signal", "change the stop", "new data provider",
  "deploy change", "is this safe to merge".
---

# Allocator Change Control

How changes get classified, gated, evidenced, and promoted in this repo. This is a solo
project (owner: R). There is no second reviewer — **the gate IS the review**: a change is
"approved" when the required evidence exists, is recorded, and doesn't violate R1–R8.
Nothing merges on vibes.

All file:line anchors, thresholds, and commands below verified against the repo on 2026-07-11.

## When NOT to use this skill

| You are trying to... | Use instead |
|---|---|
| Diagnose a failure/symptom (empty book, weird regime verdict, cache issues) | allocator-debugging-playbook |
| Understand WHY the system is built this way (M1–M9 design, invariants) | allocator-architecture-contract |
| Add tests / understand what counts as evidence in detail / golden expectations | allocator-validation-and-qa |
| Look up a config key, flag, or env var | allocator-config-and-flags |
| Run an ablation/sweep step-by-step with worked examples | allocator-proof-and-analysis-toolkit |
| Read the full incident histories | allocator-failure-archaeology |
| Write external docs/claims about results | allocator-docs-and-claims |
| Set up the environment | allocator-build-and-env |
| Operate the weekly run / deploy | allocator-run-and-operate |

Use THIS skill when the question is "may this change land, and what must I show first?"
No sibling skill may route around this one.

## Vocabulary (defined once)

- **Walk-forward backtest**: simulate the strategy month by month over 2020-01-01..2026-06-01,
  at each step using only data timestamped on/before that date. `scripts/run_backtest.py`.
- **Ablation**: run the backtest with a rule/signal ON vs OFF and compare out-of-sample
  metrics. The suites live in `src/allocator/backtest.py` (`default_suite()` / `rs_suite()`).
- **Tune window / validate window**: 2020-01-01..2023-12-31 (parameters may be fitted here)
  vs 2024-01-01..2026-06-01 (untouched out-of-sample; see R1). `config.yaml` `backtest:` block.
- **Sweep**: `scripts/sweep.py` — runs strategy variants over BOTH windows and prints a
  "robust pick" (best validate-window Sortino among variants whose tune-window Sortino is
  above the median), so the choice isn't curve-fit to the test set.
- **Honesty banner**: `backtest.caveat_banner()` (src/allocator/backtest.py:250) — the
  survivorship/upper-bound caveat that must accompany every performance number (R4).

## Change classification — six classes, six gates

| Class | Examples | Gate | Minimum evidence before merge |
|---|---|---|---|
| (a) Config-threshold tweak | cuts, caps, regime_budgets, breadth_riskon, kelly_fraction | Sweep or targeted ablation, tuned ONLY on tune window | Before/after sweep table (both windows), robust pick unchanged or improved; golden checks still pass |
| (b) New signal / sub-score | activating FI/EXP/CAT/THM, ERM re-adoption, any new score input | Full walk-forward ablation (R3) — the hardest gate | Ablation shows the signal HELPS out-of-sample vs the RS-only baseline; point-in-time audit of its data; ships as opt-in flag first |
| (c) Data-source change | new price provider, FRED series swap, cache logic | Smoke + coverage + PIT audit + backtest invariance | Coverage stats; identical backtest results if change is "same data, new pipe"; R5/R7 respected |
| (d) Risk / exit rule change | stop_atr, trims, trail, regime gate logic, budgets | Ablation with drawdown-first reading | Max-drawdown not worsened without an explicit, recorded trade-off; never delete a pre-committed exit |
| (e) Infra / deploy change | build-report.yml, webapp.py, Dockerfile, requirements-web.txt | Web-image weight check + a real Actions run | requirements-web.txt still pandas-free (R6); a `workflow_dispatch` build publishes `live-report` successfully |
| (f) Docs | README, DEPLOY.md, skills | Claims audit | Every performance number traceable to `backtest.metrics` output and carrying the survivorship caveat (R4) |

Details and per-class checklists below. A change touching two classes takes BOTH gates
(e.g. a new signal that needs a new provider = (b) + (c)).

## The non-negotiables R1–R8

Each: the rule → why → the incident behind it. These are settled battles. Do not re-fight
them; cite them.

**R1 — The validate window (2024-01-01..2026-06-01) is quarantined.**
Tune parameters only on the tune window (2020-01-01..2023-12-31). Never pick a parameter
because it maximised validate-window results — that silently converts your out-of-sample
test into a second in-sample fit and the "+34% CAGR" claim becomes fiction.
*Incident:* the concentration sweep (n8/12/15/20 × regime on/off) was exactly the
temptation moment; `scripts/sweep.py` was built with the robust-pick rule (validate Sortino
ranked only among variants with above-median TUNE Sortino, sweep.py:71-79) so the winner
(n15, now `cuts.max_anchors: 15`, config.yaml:50) was chosen for robustness across both
windows, not for the best test-set number.

**R2 — Decision-support only. No broker integration, no auto-orders, ever.**
Output is a ranked, risk-budgeted proposal (~£10,000 book, US-listed names) that R reviews
and places manually at IBKR. This bounds the blast radius of every bug to "a bad
suggestion a human reads", not "an order that fired". pyproject.toml:8 states it in the
package description ("decision-support, not an autotrader"). Any PR adding order routing,
broker API keys, or execution hooks is rejected regardless of evidence — this is a design
boundary, not a tunable.

**R3 — No signal or rule becomes default without a walk-forward ablation showing it helps
out-of-sample.**
Backtests flatter whatever you just built; only an ablation (same everything, rule on vs
off) isolates a rule's worth, and only the out-of-sample window says whether it
generalises. *Incident:* ERM (analyst estimate-revision momentum) was the spec's anchor
signal at weight 0.30 (config.yaml:18 — "anchored — most robust signal"), yet the ablation
showed it cut out-of-sample CAGR from 34% to 16% (weekly_run.py:9-10), so it was demoted
to the opt-in `ermrs` flag. If the spec's own favourite signal wasn't exempt, nothing is.
See "Experiment → default" below for the full lifecycle.

**R4 — Every performance number carries the survivorship / upper-bound caveat.**
The backtest universe is today's S&P 500 constituents plus a 5-name delisted overlay
(data/delisted.csv: SIVB, FRC, ATVI, SGEN, SPLK) — NOT true point-in-time membership, so
results are an upper bound. `backtest.caveat_banner()` (backtest.py:250-260) prints this
after every `run_backtest.py` run; docs must reproduce it. Numbers come from
`backtest.metrics` output only — no eyeballed equity curves, no cherry-picked windows.
*Incident:* preventive rather than reactive — the whole survivorship-bias-campaign skill
exists because this is the project's #1 credibility gap; overclaiming once would poison
every number after.

**R5 — Point-in-time everywhere.**
Any computation at date t may use only data timestamped ≤ t. Look-ahead leakage
manufactures fake alpha that evaporates live. *Incident:* ERM again — current-consensus
estimate data is not point-in-time (revisions overwrite history), which is why ERM had to
be proxied with dated analyst grade actions (thin pre-2023 coverage) and why the weekly
`snapshot` flag banks consensus to data/snapshots/estimates_<date>.csv
(src/allocator/weekly.py:40-54): to accumulate a TRUE point-in-time series for a clean
future re-test.

**R6 — Keep the web image tiny; heavy builds belong to GitHub Actions.**
requirements-web.txt is flask/gunicorn/requests ONLY — its header comment says why: the
build "runs on GitHub Actions, never on the web host, so this stays tiny and can't OOM".
*Incident:* the OOM deploy (PR #3, merged as commit fd41943, 2026-06-30 per git log):
the first deploy built the pandas book on a 512 MB Render host and died out-of-memory.
Fix: split architecture — Actions (16 GB runner) builds via
`.github/workflows/build-report.yml` and force-pushes reports/latest.html to the
`live-report` branch; the web host only serves it. Never add pandas or any build dep to
requirements-web.txt or the Dockerfile.

**R7 — Cache operations must be non-destructive.**
Overwrite on success; never delete-then-fetch. *Incident:* the destructive prefetch wipe —
force-refresh used to delete cache entries before refetching, so a yfinance rate-limit
mid-run left the price cache EMPTY. Fix in `prices.prefetch()` (src/allocator/data/
prices.py:182-186): "NON-DESTRUCTIVE: re-attempt all and OVERWRITE on success, but keep
existing data on failure." Related guard downstream: weekly_run.py:53-57 aborts with exit
code 2 if fewer than 50 names have price data, preserving the previous latest.html instead
of publishing a degenerate one-name book.

**R8 — API keys live in .env / GitHub Actions secrets only.**
Never in code, config.yaml, or skills. src/allocator/config.py:52-56 loads
FRED_API_KEY / FMP_API_KEY / FINNHUB_API_KEY from `.env` (gitignored); build-report.yml:47-49
injects the same names from Actions secrets. A leaked key in a public momentum repo is a
free quota for strangers and a forced rotation for R. Any diff that embeds a key string is
rejected on sight.

## "Before you change X" checklists

Commands are given PowerShell-first (R's Windows dev box; `$env:PYTHONUTF8=1` avoids
console encoding crashes) then Linux/CI form. All backtest/sweep commands need a populated
price cache (`data/cache/`) and, for regime checks, a FRED key in `.env` — on a keyless
box, first run `scripts/fetch_universe.py` for prices and expect FRED-dependent steps to
degrade.

### (a) Config-threshold tweak (config.yaml numbers)

1. Confirm the key is actually read by code, not aspirational — `weights.FI/EXP/CAT/THM`
   are declared (config.yaml:20-23) but NOT implemented; only ERM and RS have scorers.
   Grep before assuming:
   ```powershell
   # PowerShell and Linux (ripgrep)
   rg "your_key_name" src/ scripts/
   ```
2. If the new value uses scientific notation, it MUST have a signed exponent. PyYAML
   (YAML 1.1) parses `1.5e9` as a STRING; `1.5e+9` is required (the trap is documented at
   config.yaml:12). Verify the parse:
   ```powershell
   $env:PYTHONUTF8=1; .venv\Scripts\python.exe -c "import yaml; c=yaml.safe_load(open('config.yaml')); v=c['universe']['min_mktcap_usd']; print(type(v), v)"
   ```
   ```bash
   python -c "import yaml; c=yaml.safe_load(open('config.yaml')); v=c['universe']['min_mktcap_usd']; print(type(v), v)"
   ```
   (Adapt the key path to the value you touched. Expect `<class 'float'>`.)
3. Run the sweep — tune-window reasoning only (R1):
   ```powershell
   $env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\sweep.py
   ```
   ```bash
   python scripts/sweep.py
   ```
   Record the before/after table and the robust pick. If your change isn't a sweep axis
   (sweep.py only varies top_n and regime on/off), run the ablation suite instead:
   ```powershell
   $env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\run_backtest.py rs
   ```
   (`rs` = RS-only suite, no FMP quota needed; omit it to include ERM strategies.)
4. If the change touches the `regime:` block or `regime_budgets`, re-run the golden
   verdicts — 2022 dates must print COMPRESSION, 2023/2025 recovery dates RISK_ON:
   ```powershell
   $env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\test_regime.py
   ```
   (Requires FRED key in .env.)
5. Evidence to record in the commit message: old value → new value, sweep/ablation table
   excerpt, which window justified it (must be tune), honesty banner acknowledged.

### (b) New signal / sub-score (or re-enabling ERM)

1. Point-in-time audit FIRST (R5): for the data feeding the signal, answer in writing —
   "at backtest date t, was this value knowable at t?" Current consensus data fails this;
   dated analyst grade actions (src/allocator/data/estimates.py) pass. If the data is not
   PIT-clean, stop; the ablation would be meaningless.
2. Wire it as OPT-IN, never default — follow the `ermrs` pattern exactly:
   weekly_run.py:33 builds `active = ("ERM","RS") if "ermrs" in flags else ("RS",)`.
   Your signal gets its own flag; the default book stays RS-only.
3. Add an ablation Strategy for it (see `default_suite()` / `rs_suite()` in
   src/allocator/backtest.py:43-58) and run:
   ```powershell
   $env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\run_backtest.py
   ```
4. Sanity-check it doesn't break winner recall (Dec-2022 top-10 should still contain 2023
   winners, Dec-2023 top-10 the 2024 winners):
   ```powershell
   $env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\test_scoring.py
   ```
5. Promotion to default requires the full "Experiment → default" protocol below. Evidence:
   ablation table showing out-of-sample improvement vs the RS-only baseline, PIT audit
   note, coverage stats (a signal covering 10% of names pre-2023 is what sank ERM).

### (c) Data-source change (provider, series, cache)

1. Read the existing source-order and cache contracts before touching them:
   src/allocator/data/prices.py (source order FMP→stooq→yfinance; `_stooq_blocked`
   session flag at prices.py:59; negative-cache TTL 6h at prices.py:58) and
   src/allocator/data/cache.py (permanent for point-in-time data, TTL for live-ish).
2. R7 check: no code path may delete cached data before a replacement is confirmed
   fetched. Overwrite-on-success only.
3. Smoke the data layer:
   ```powershell
   .venv\Scripts\python.exe scripts\smoke_data.py
   ```
   KNOWN BUG (open as of 2026-07-11): with a FRED key present, smoke_data.py:72 calls
   `fred.fetch_named("hy_spread")` but the key in fred.SERIES is `"credit_spread"`
   (src/allocator/data/fred.py:25) → KeyError. Sections 1–4 still run keyless; don't
   mistake the KeyError for your own breakage.
4. Coverage check after the change:
   ```powershell
   $env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\refresh_prices.py
   ```
   (Non-destructive refill; prints "coverage now: X/Y names".) Expect ~500/503 for the
   S&P universe; a weekly_run below 50 names aborts (exit 2).
5. Invariance test: if the change is "same data, new pipe", the backtest output must be
   identical before/after (`scripts/run_backtest.py rs`, diff the metrics table). If the
   data itself changes (e.g. a FRED series swap), re-run `scripts/test_regime.py` golden
   verdicts and treat it as class (a)+(c). Precedent for series swaps: spec wanted
   BAMLH0A0HYM2 (ICE BofA HY OAS) but FRED truncates it to ~3yr, so BAA10Y was substituted
   (fred.py:22-25, config.yaml:83-84) — the substitution was justified by full daily
   history AND co-movement with HY stress, then the golden verdicts re-checked.
6. Evidence: coverage numbers, invariance diff (or golden-verdict table), a sentence on
   how the change behaves under rate-limiting (the failure mode that caused incidents
   R7 and the degenerate-universe guard).

### (d) Risk / exit rule change (exits.py, gate logic, budgets)

Current committed values (config.yaml:60-64): stop = entry − 2.5×ATR, trim 1/3 at +50%,
another 1/3 at +100%, trail 3×ATR once in profit. These encode two named lessons: the
OKLO +250%→flat round-trip (pre-committed trims/trails exist so gains get banked) and the
ARKK study (one −67% year erases three good ones — the regime gate's reason to exist).
The TTWO catalyst slip is why dated catalysts get a de-rate-on-slip flag
(src/allocator/exits.py:8, data/catalysts.csv).

1. Never REMOVE a pre-committed exit or the regime gate's COMPRESSION de-risking without
   an ablation demonstrating the drawdown cost is acceptable — and note the gate is already
   a user-facing dial, not a constant: `live.use_regime_gate` true = Safe (~+34% CAGR /
   ~−16% max DD) vs false = Returns (~+41% / ~−21%), config.yaml:55-57. Changing the
   DEFAULT of that dial is a class (d) change; flipping it per-run via the `safe`/`returns`
   flags (weekly_run.py:36-39) is normal operation, not a change.
2. Run the ablation and read it drawdown-first — the metrics table deliberately leads with
   median annual return and max drawdown (run_backtest.py:31-44):
   ```powershell
   $env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\run_backtest.py rs
   ```
3. Run the sweep to confirm the robust pick under both windows still holds:
   ```powershell
   $env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\sweep.py
   ```
4. Evidence: before/after max drawdown and Sortino in BOTH windows; if drawdown worsens,
   an explicit recorded statement of the trade-off accepted. A sizing change must also
   confirm the cash-drag fix is intact: with RS-only (no satellites) the satellite budget
   folds into anchors (src/allocator/sizer.py:85-98 — "this was a real ~40% cash-drag
   bug", the single biggest live-return fix per README).

### (e) Infra / deploy change (CI, webapp, Docker, Render)

1. R6 weight check — must print nothing:
   ```powershell
   rg -i "pandas|numpy|yfinance" requirements-web.txt Dockerfile
   ```
2. Understand what you're touching: `.github/workflows/build-report.yml` is the ONLY CI.
   It runs Mondays 11:13 UTC + on `workflow_dispatch` (mode: safe|returns), installs
   requirements.txt + `pip install -e .`, runs
   `python scripts/weekly_run.py noopen <mode>`, and force-pushes a single-commit
   `live-report` branch containing latest.html + built_at.txt + mode.txt. NO tests run in
   CI (pyproject.toml:16 points pytest at `tests/`, which does not exist as of
   2026-07-11 — see allocator-validation-and-qa for fixing that).
3. Webapp contract (webapp.py:39-45): cloud mode activates when GH_TOKEN + GH_REPO are
   set — "Refresh" dispatches build-report.yml, polls, then serves latest.html from the
   `live-report` branch; without them it falls back to a local subprocess build. Don't
   break either mode; Basic Auth comes from APP_USER/APP_PASSWORD.
4. Gate: after merging a workflow/webapp change, trigger a real `workflow_dispatch` run
   (Actions tab, or the dashboard Refresh button) and confirm `live-report` received a
   fresh commit (built_at.txt updated). The exit-2 degenerate-universe abort
   (weekly_run.py:54-57) is load-bearing here: it's what keeps a bad data day from
   overwriting the published report — never "fix" a red CI run by removing it.
5. The Windows .bat launchers (run_site.bat, run_weekly.bat, run_weekly_scheduled.bat)
   hardcode the original dev path `C:\Users\ranvi\stock` — a documented trap. Don't
   propagate that path anywhere new.
6. Evidence: green Actions run link + fresh live-report commit + the weight-check output.

### (f) Docs

1. Every performance number must be traceable to a `backtest.metrics` line from a run you
   (or a recorded prior run) actually executed, and must carry the survivorship caveat.
   Canonical validated claim (as of 2026-07-11): RS top-15 regime-gated, validate window:
   ~+34% CAGR vs S&P +14.5%, max DD ~−16% vs −25%; gate off: ~+41% / ~−21%; momentum
   catch-rate on each year's top-10 movers: 0–20% (it rides trends, it does not call
   turns). All upper bounds — the universe is not true point-in-time membership.
2. Do not present open/candidate items as shipped. As of 2026-07-11: PR #1 (GPT-picks
   benchmark) and PR #2 (log_picks.py showdown tracker) are open on stale pre-PR-#3 main —
   candidate features, not part of the system (status per project brief; re-verify with
   `gh pr list` — not checkable from the local clone alone, which only shows PR #3 merged
   as commit fd41943). data/theme_tree.yaml has NO reader in code (grep confirms) — the
   THM sub-score is future work.
3. Deep house style and positioning rules live in allocator-docs-and-claims.

## Experiment → default: the promotion protocol

The ERM story is the precedent in BOTH directions — how a spec-anchored signal gets cut,
and how a cut signal can earn its way back.

**The lifecycle (every future signal/rule follows it):**

1. **Experiment flag.** The change ships behind an opt-in flag; the default book is
   untouched. Pattern: `ermrs` in weekly_run.py (FLAGS set, line 24; signal selection,
   line 33) and run_allocation.py:19.
2. **Ablation.** Add a Strategy variant to the backtest suite; run
   `scripts/run_backtest.py` (and `scripts/sweep.py` if a threshold is involved). The
   only question: does it improve the OUT-OF-SAMPLE window vs the current default,
   without unacceptable drawdown? Tune-window-only fitting (R1) applies throughout.
3. **Verdict — one of two, both recorded:**
   - **Promote:** flip the default (e.g. change the `active` tuple default), keep the
     flag as the off-switch for one cycle, record the ablation table in the commit.
   - **Documented retirement:** the flag stays opt-in (or is removed), and the negative
     result is written down where the next person will trip over it — ERM's retirement is
     documented in weekly_run.py's docstring ("ERM failed the backtest ablation: it cut
     CAGR 34%->16%. Opt-in only."), config.yaml keeps the aspirational weight with the
     regime-modifier note that ERM "stays anchored (1.0) in every regime by design"
     (config.yaml:26), and README:18 records that the ablation "did its job".
4. **Never silently delete the losing branch's evidence.** The point of documented
   retirement is that the retirement is re-testable.

**ERM's cut (the "demote" precedent):** spec weight 0.30, "anchored — most robust
signal" — yet the walk-forward ablation showed out-of-sample CAGR 34%→16%. Root cause
wasn't necessarily the idea: the implementation proxied estimate revisions with yfinance
dated analyst grade actions (the only PIT-clean source available), which have thin
pre-2023 coverage. Spec authority did not outrank evidence (R3).

**ERM's re-adoption path (the "promote" precedent, open as of 2026-07-11):** every weekly
run with the `snapshot` flag banks the CURRENT analyst consensus to
`data/snapshots/estimates_<YYYY-MM-DD>.csv` (weekly.py:40-54; the Windows scheduled task
and the manual runbook include `snapshot`). After roughly a year of banked snapshots there
will exist a true point-in-time ERM series with real coverage. The re-test is then a clean
class (b) change: build an ERM scorer over the snapshot series, add it to the suite,
re-run the ablation, and promote only if it beats RS-only out-of-sample. Until that
ablation exists, ERM stays opt-in — no exceptions, including "the spec said 0.30".

The same path applies to FI/EXP/CAT/THM (weights declared in config.yaml:20-23, zero
implementation) and to data/theme_tree.yaml (currently read by nothing).

## What "recorded evidence" means here (solo protocol)

Since there is no reviewer, the merge artifact substitutes for review. A gated change is
mergeable when ALL of:

1. The commit message (or PR body) contains the evidence: before/after metrics table
   excerpt, which gate was run, which window justified any tuning.
2. The relevant golden checks pass: `test_regime.py` verdicts (2022 COMPRESSION,
   2023/2025 RISK_ON), `test_scoring.py` winner recall, universe count ≥ 50.
3. No R1–R8 violation. If a change requires violating one, the change is wrong, not the
   rule — the rules each have a paid-for incident behind them.
4. Anything unproven that ships anyway ships as opt-in and labeled candidate/experimental.

## Provenance and maintenance

Authored 2026-07-11 against branch `claude/skill-library-handoff-vm2gku` (HEAD fd41943).
Re-verify before trusting drift-prone facts:

- Config values (cuts, caps, exits, windows, gate default): `rg -n "" config.yaml` and re-read.
- RS-only default + ermrs flag + 34→16 ablation note: `rg -n "ermrs|34" scripts/weekly_run.py`
- Degenerate-universe abort (<50, exit 2): `rg -n "n_uni < 50" scripts/weekly_run.py`
- Cash-drag fold: `rg -n "cash-drag" src/allocator/sizer.py` (expect ~line 88)
- 21-day credit-spread z>1.5 trigger: `rg -n "1.5" src/allocator/regime.py` (expect ~156-159)
- Non-destructive prefetch: `rg -n "NON-DESTRUCTIVE" src/allocator/data/prices.py`
- Web image still tiny: `rg -i "pandas" requirements-web.txt` (expect no output)
- smoke_data.py hy_spread bug still open: `rg -n "hy_spread" scripts/smoke_data.py` vs
  `rg -n "credit_spread" src/allocator/data/fred.py` (bug fixed when these agree)
- tests/ still missing: `ls tests` (errors = still missing) and `rg -n "testpaths" pyproject.toml`
- PR #1/#2 status (needs network): `gh pr list --state open`
- Robust-pick logic: `rg -n "tune_median" scripts/sweep.py`
- CI schedule/modes: `rg -n "cron|mode" .github/workflows/build-report.yml`
