---
name: allocator-debugging-playbook
description: >
  Triage and fix runtime failures in the Asymmetric Allocator. Load this when a run
  misbehaves: empty or near-empty book; weekly_run.py exits with code 2 ("only N names
  have price data"); scores or the ERM column all NaN; regime always MIXED or looks wrong;
  backtest RuntimeError "Not enough rebalance dates"; stooq returns nothing; yfinance
  rate-limited / prefetch misses; RuntimeError "Missing FRED_API_KEY"; FMP 429/402 quota;
  reports/latest.html stale or missing; webapp "Refresh" fails (workflow not found, token
  rejected, build failed); Windows UnicodeEncodeError; ModuleNotFoundError: allocator;
  cache poisoned or stale negative-cache entries. Covers safe cache inspection
  (data/cache/, cache.clear/invalidate) and the known smoke_data.py "hy_spread" bug.
---

# Allocator Debugging Playbook

Runbook for diagnosing a misbehaving run of the Asymmetric Allocator (the weekly S&P 500
momentum book builder). Audience: an engineer who knows Python/pandas but not this repo.
All file:line anchors verified against the repo on 2026-07-11.

**When NOT to use this skill**
- Designing or gating a change (fix beyond a config/env correction) → `allocator-change-control`.
- Measuring/benchmarking signal or portfolio behaviour → `allocator-diagnostics-and-tooling`.
- "Why is it built this way?" / history of a past incident → `allocator-failure-archaeology`.

**60-second orientation.** `scripts/weekly_run.py` runs the live pipeline
(`src/allocator/pipeline.py:19-25`): universe (data/sp500_constituents.csv + delisted
overlay, ADV-filtered) → regime verdict (FRED macro + ^SPX trend + breadth) → scoring
(RS price momentum; ERM analyst momentum is opt-in via the `ermrs` flag) → classify →
size → `reports/latest.html`. All market data flows through a disk cache in `data/cache/`
(`src/allocator/data/cache.py`). Price source order: FMP (if key) → stooq → yfinance
(`src/allocator/data/prices.py:127-131`). Run commands (PowerShell first — R's dev box is
Windows; Linux second):

```powershell
$env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\weekly_run.py noopen
```
```bash
PYTHONUTF8=1 .venv/bin/python scripts/weekly_run.py noopen
```

## Symptom → triage table

| # | Symptom (as you see it) | Most likely causes, ranked | Discriminating experiment | Fix |
|---|---|---|---|---|
| 1 | Book empty / near-empty (0–2 anchors) but run completes | (a) genuine COMPRESSION verdict + high cuts; (b) incomplete price data depressing scores; (c) Extension gate: anchors need WinnerScore ≥ 80 AND Extension ≥ 65 (`classifier.py:63`, config `cuts`) | Read the run's console line `<VERDICT> \| deploy N% \| N anchors` (`weekly_run.py:60-61`); in a REPL inspect `result["scored"]` and `result["buckets"].watch` — high scores stuck in watch means the Extension gate, not data | (a) is correct behaviour; (b) → row 2/8; (c) only change cuts via allocator-change-control |
| 2 | `ABORT: only N names have price data` and exit code 2 | (a) yfinance batch prefetch rate-limited; (b) stale negative-cache entries blocking retries; (c) network/proxy outage | `.venv\Scripts\python.exe scripts\refresh_prices.py` — it prints `coverage now: X/Y names have price data` (`scripts/refresh_prices.py:22-23`) | Wait out the rate limit, re-run `refresh_prices.py` (clears `prices_neg`, non-destructive), then `weekly_run.py norefresh`. Guard is intentional: previous latest.html is preserved (`weekly_run.py:50-57`) |
| 3 | All names score NaN / `winner_score` empty | (a) cached price frames too short — RS needs ≥ 60 rows (`scoring.py:60`); (b) `^SPX` history missing (this actually raises IndexError inside `_rs_features`, not NaN); (c) ERM-only run with zero grade coverage | REPL: `prices.fetch_ohlcv("NVDA")` — check `len(df)`; `prices.history("^SPX")` — empty? | Refill cache (`refresh_prices.py`); for ^SPX: `cache.invalidate("prices", "^SPX\|full"); prices.history("^SPX")` |
| 4 | ERM column all NaN (or absent) | (a) **ERM absent is the default** — RS-only unless the `ermrs` flag is passed (`weekly_run.py:33`); (b) no analyst actions in the 90-day window (coverage thins for small names / dates pre-2023, `scoring.py:109-136`); (c) yfinance grades fetch failing (failures memoised in-memory only, `estimates.py:70-71`) | Did you pass `ermrs`? Then REPL: `from allocator.data import estimates; estimates.dated_grades("NVDA")` — empty list = fetch/coverage problem | (a) expected; (b) expected — per-name weights renormalise to RS (`scoring.py:207-216`); (c) `cache.clear("yf_grades")` and retry later |
| 5 | Regime always MIXED | RISK_ON needs ALL of: trend up, spreads tight (credit z < 0.5), breadth ≥ 0.55 (`regime.py:160-171`). Missing ^SPX trend data defaults `trend_up` to False → MIXED (`regime.py:161`) | Print `result["regime"].components` and `.notes` — look for "S&P 500 trend unavailable" and check `breadth_above_200dma`, `credit_spread_level_z` | If a component is NaN, fix its data feed (rows 3, 6, 9); if all populated, MIXED is the honest verdict |
| 6 | Regime looks wrong (e.g. COMPRESSION in a calm market) | (a) stale ^SPX cache → below-200dma computed on old prices (`regime.py:107-112`); (b) stale FRED cache (`norefresh` skips the clear); (c) genuine 21-day spread-widening trigger | Check `components["spx_vs_200dma"]` and the last date of `prices.history("^SPX")`; check `notes` for which COMPRESSION trigger fired (`regime.py:164-167`) | Run without `norefresh` (refresh invalidates ^SPX and clears `fred`, `weekly.py:30-34`), or invalidate manually |
| 7 | Backtest: `RuntimeError: Not enough rebalance dates / price data for the backtest window.` | ^SPX history empty or truncated — rebalance dates are month-ends snapped to ^SPX trading days (`backtest.py:66-77`); < 6 dates aborts (`backtest.py:267-269`) | REPL: `prices.history("^SPX")` — empty or ends early? | `cache.invalidate("prices", "^SPX\|full"); prices.history("^SPX")`; if still empty it's a network/provider issue (rows 8, 10) |
| 8 | stooq returns nothing | (a) stooq served its JS anti-bot challenge — session-wide skip flag set (`prices.py:59,78-80`); (b) unknown symbol; (c) rate-limited burst | `curl -s "https://stooq.com/q/d/l/?s=nvda.us&i=d" \| head -c 200` — body starting `<` is the challenge page, CSV header `Date,Open,...` is healthy | Nothing to fix in-session: the pipeline falls through to yfinance (`prices.py:127-131`). Flag resets on the next process. Never add per-name stooq retries — see trap 2 |
| 9 | yfinance rate-limited / prefetch mostly misses | Yahoo throttling the batch download (`prices.py:193-199`, chunk = 40) | Look at the printed `prices refreshed: ok=X miss=Y` (`weekly_run.py:45`) — high `miss` with low `ok` = rate limit | Wait (hours, not minutes), then `refresh_prices.py`. Prefetch is non-destructive: existing cache survives a failed refresh (trap 1) |
| 10 | `RuntimeError: Missing FRED_API_KEY...` | No `.env` / key not set — raised by `Keys.require` (`config.py:40-47`) on the first uncached FRED fetch (`fred.py:54`) | `Test-Path .env` and check it contains `FRED_API_KEY=` (never print the value). Note: cached FRED series serve WITHOUT a key (`fred.py:46-52`), but a normal weekly run clears the `fred` namespace (`weekly.py:33`) | Copy `.env.example` → `.env`, add the key. Keys are read once per process (`config.py:50` `lru_cache`) — restart after editing `.env`. Keys live in `.env`/Actions secrets ONLY (rule R8) |
| 11 | FMP quota hit (429/402) — but nothing errors | By design: `_get` returns None and memoises the failure IN-MEMORY FOR THIS RUN ONLY (`fmp.py:31,51-56`); prices silently fall through to stooq/yfinance (`prices.py:90-101,127-131`); mktcap filter silently skips | REPL: `from allocator.data import fmp; fmp.profile("NVDA")` — `{}` with a key set suggests quota/plan gating. Free tier is 250 requests/day | Wait for the daily quota reset; a new process retries (disk cache keeps successes permanently) |
| 12 | `reports/latest.html` stale or missing | (a) last run aborted with exit 2 — old report intentionally kept; (b) looking at the wrong dir — `REPORTS_DIR` env overrides `reports/` (`config.py:24`, `webapp.py:36`); (c) cloud: `live-report` branch not rebuilt since | Local: check exit code of last run (`$LASTEXITCODE` / `$?`) and the report's mtime. Cloud: `git fetch origin live-report && git show origin/live-report:built_at.txt` | (a) fix the data problem (row 2) and re-run; (b) unset/align `REPORTS_DIR`; (c) trigger the `build-report` workflow (Mondays 11:13 UTC otherwise, `build-report.yml:16`) |
| 13 | webapp "Refresh" fails: *workflow not found* | `build-report.yml` not on the branch `GH_REF` points at (default `main`), or `GH_REPO` wrong — the 404 handler says exactly this (`webapp.py:94-96`) | `git ls-tree origin/main .github/workflows/` — is `build-report.yml` there? Check `GH_REPO`/`GH_REF` env on the host | Fix the env vars or push the workflow to the right branch |
| 14 | webapp "Refresh" fails: *GitHub rejected the token* | Token lacks Actions read+write on the repo (401/403 handler, `webapp.py:97-98`) or expired | Test the token against the API: `curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/repos/$GH_REPO` | Re-issue a fine-grained token with Actions read+write + contents read on the repo; update host env |
| 15 | webapp "Refresh" fails: *GitHub build failure* | The Actions build itself failed (surfaced by `_poll_github`, `webapp.py:216-219`); commonly the data-guard exit 2 inside CI | Click the `view build` link in the status bar (run_url) and read the job log for the `ABORT: only N names...` line vs a real traceback | Data-guard → row 2 logic applies (usually retry later); real traceback → debug as local |
| 16 | Windows: `UnicodeEncodeError` printing the run output | cp1252 console can't encode ✓/arrows/× in script output; fixed by UTF-8 mode | Reproduce: run without `PYTHONUTF8`. All three `.bat` launchers set it (`run_weekly.bat:4`); webapp sets it for its subprocess (`webapp.py:150`); CI sets it (`build-report.yml:50`) | `$env:PYTHONUTF8=1` before any script (Linux: `PYTHONUTF8=1`) |
| 17 | `ModuleNotFoundError: No module named 'allocator'` | Package not installed editable (`pip install -e .`; packages resolve from `src/`, `pyproject.toml [tool.setuptools.packages.find] where=["src"]`) or wrong interpreter | `.venv\Scripts\python.exe -c "import allocator; print(allocator.__file__)"` | `pip install -e .` in the venv, or set `PYTHONPATH` to `src` (webapp does exactly this for its local subprocess, `webapp.py:151`; pytest gets it via `pyproject.toml pythonpath=["src"]`) |
| 18 | Cache poisoned (truncated frame) or stale negative-cache | (a) `prices_neg` "no data" markers (TTL 6h, `prices.py:58`) blocking real names; (b) a partial price frame cached during an outage | (a) `refresh_prices.py` output — `coverage now` jumps after it clears `prices_neg`; (b) REPL: `prices.history(t).index.max()` — ends months ago for a live ticker = poisoned entry | (a) `cache.clear("prices_neg")` (routine, done by `refresh_prices.py:16`); (b) `cache.invalidate("prices", f"{t}\|full")` then re-fetch that one name. Never bulk-delete `prices` (see below) |

REPL setup used above (run from repo root, venv python):

```python
from allocator.data import cache, prices, fred, estimates
from allocator import pipeline
result = pipeline.run_live("2026-07-11", active=("RS",))
```

## The traps that cost real time

Each of these burned hours once. The full incident history lives in
`allocator-failure-archaeology`; what follows is the operational summary plus the check
that tells you whether you're looking at the same beast.

**1. Destructive prefetch wipe.** Force-refresh used to delete cache entries before
refetching; one yfinance rate-limit later, the entire ~500-name price cache was gone and
every downstream stage failed at once. The fix is overwrite-on-success: `prefetch(...,
force=True)` only clears per-ticker `prices_neg` markers and re-attempts, keeping existing
frames on failure (`prices.py:182-190`; project rule R7: cache operations must be
non-destructive). **Discriminating check:** count `data/cache/prices__*` files before and
after a failed forced refresh — the count must never drop. If you see a mass-empty cache
today, suspect a manual `cache.clear("prices")` or a deleted `data/cache/`, not prefetch.

**2. stooq JS challenge.** stooq intermittently serves an HTML anti-bot page that
`requests` cannot solve; per-name retries against it wasted minutes per run across ~500
names. Fix: the first challenge sets a session-wide `_stooq_blocked` flag and stooq is
skipped for the rest of the process (`prices.py:59,66-80`). **Discriminating check:**
`curl` the stooq CSV URL (row 8) — a body starting `<` is the challenge. A healthy failover
shows one fast stooq failure then yfinance; if a run grinds per-name on stooq, the flag
logic has regressed.

**3. Degenerate-universe guard.** A rate-limited provider once produced a near-empty
universe and the run happily published a broken 1-name book over the good report. Now
`weekly_run.py` aborts with exit code 2 if fewer than 50 names have price data, leaving
the previous `latest.html` untouched (`weekly_run.py:50-57`). **Discriminating check:**
exit code 2 plus the `ABORT: only N names have price data` line = the guard working as
designed, not a crash. Fix the feed (rows 2/9/18), never lower the threshold to "make it
pass".

**4. PyYAML 1.5e9 trap.** YAML 1.1 requires a signed exponent, so `yaml.safe_load` parses
`1.5e9` as the STRING `'1.5e9'` while `1.5e+9` is the float — verified:
`python -c "import yaml; print(repr(yaml.safe_load('a: 1.5e9')['a']))"` → `'1.5e9'`.
`config.yaml` carries the signed form with a warning comment (`min_mktcap_usd: 1.5e+9`).
Existing readers defensively coerce (`float(ucfg["min_mktcap_usd"])`, `universe.py:114-115`),
so this survives today — but any NEW config number in scientific notation used without
`float()` will silently compare as a string. **Discriminating check:** run the one-liner
above on the exact literal you added.

**5. FRED truncated BAMLH0A0HYM2.** The spec's credit-stress series was ICE BofA HY OAS
(`BAMLH0A0HYM2`), but FRED now truncates it to roughly the last 3 years (ICE licensing) —
useless for a 2020–2026 backtest. `BAA10Y` (Moody's Baa − 10Y Treasury) was substituted:
daily, full history, co-moves with HY stress (`fred.py:22-25`, `config.yaml regime.
credit_spread_series`). **Discriminating check:** if a FRED series you fetch starts only
~3 years back, that's licensing truncation at the source, not a bug in `fetch_series` —
check the series page on fred.stlouisfed.org before debugging the wrapper.

**6. Daily-spread false triggers.** The COMPRESSION trigger "credit spreads widening fast"
originally used the daily change; one volatile day flipped the whole book defensive.
Fix: "widening fast" = the 21-day change in the spread, z-scored against its own history,
> 1.5σ (`regime.py:156-159`). **Discriminating check:** an unexpected COMPRESSION verdict
should come with the note naming its trigger (`regime.py:164-167`); compute
`_zscore_at(credit.diff(21), as_of)` in a REPL — if it's ≤ 1.5 yet the note claims
spread-widening, the rule regressed. A single-day spike must NOT flip the verdict.

## Known open bug (as of 2026-07-11): smoke_data.py "hy_spread" KeyError

`scripts/smoke_data.py:72` calls `fred.fetch_named("hy_spread")`, but the friendly-name
map `fred.SERIES` (`fred.py:18-27`) only has keys `fed_funds`, `ust10y`, `ust2y`,
`credit_spread`, `vix`. `fetch_named` does a bare `SERIES[name]` lookup (`fred.py:84`), so
**section 5 of the smoke test raises `KeyError: 'hy_spread'` whenever a FRED key is
present** (the section is gated on `keys.fred`, `smoke_data.py:69`). Without a key the bug
is invisible — sections 1–4 pass and section 5 is skipped, which is why it survives. The
section's print text is doubly stale: it labels the output `BAMLH0A0HYM2`, the series that
was replaced by `BAA10Y` (trap 5). The one-line correction is `"credit_spread"`, but route
it through `allocator-change-control` — do not patch mid-debug. Until fixed, treat a
section-5 KeyError as this known defect, not a FRED problem.

## Inspecting the cache safely

Layout (`src/allocator/data/cache.py`): every entry is one file in `data/cache/`
(or `$DATA_DIR/cache` if `DATA_DIR` is overridden — `config.py:22-23`), named
`<namespace>__<sha1-of-ident, 16 hex>.<json|csv>` (`cache.py:19-27`). Namespaces in use:
`prices`, `prices_neg` (negative "no data" markers), `fred`, `yf_grades`, `fmp_profile`,
`fmp_ptc`, `fmp_grades`, `fmp_estimates`, `fmp_sp500`, `fmp_hist`, `fh_metric`, `fh_earn`,
`fh_profile` (grep `put_json\|put_df\|"fmp_\|"fh_` under `src/allocator/data/` to
re-enumerate). Because idents are hashed, filenames don't reveal the ticker — resolve a
specific entry with the same helper the code uses (read-only):

```python
from allocator.data import cache
print(cache._path("prices", "NVDA|full", "csv"))   # exact file for NVDA's price frame
```

Census by namespace (safe, read-only):

```powershell
Get-ChildItem data\cache | Group-Object { ($_.Name -split '__')[0] } | Select-Object Count, Name
```
```bash
ls data/cache | sed 's/__.*//' | sort | uniq -c
```

Semantics you must know before deleting anything:

- **TTLs are read-side, not stored**: `get_json`/`get_df` take `max_age_sec` and compare
  against file mtime; expired files are ignored, not deleted (`cache.py:30-39,48-57`).
  So an "expired" file on disk is normal.
- **`cache.invalidate(ns, ident)`** deletes exactly one entry (both `.json` and `.csv`
  forms) so the next read re-fetches (`cache.py:66-71`). This is the precise tool — e.g.
  `cache.invalidate("prices", "^SPX|full")`.
- **`cache.clear(ns)`** deletes every file matching `<ns>__*` (`cache.py:74-83`). The glob
  includes the `__` separator, so `clear("prices")` does NOT touch `prices_neg`, and
  vice versa.
- **Safe to clear anytime**: `prices_neg` (6h markers), `fred`, `yf_grades` — the weekly
  refresh clears the latter two routinely (`weekly.py:33-35`) and `refresh_prices.py`
  clears `prices_neg`.
- **Do NOT bulk-clear `prices`**: full histories for ~500 names take hours to rebuild
  against rate-limited free sources, and mid-rebuild runs will hit the exit-2 guard.
  If one frame is poisoned, `invalidate` that one ident. Rule R7 (non-destructive cache
  operations) applies to your debugging session too: prefer targeted `invalidate` +
  re-fetch over any delete-then-hope sequence.
- In-memory layers sit above the disk cache (`prices._MEM_PRICES` `prices.py:104`,
  `fred._MEM` `fred.py:30`, FMP/estimates per-run failure memos `fmp.py:31`,
  `estimates.py:27`): a long-lived REPL can serve stale data after you fix the disk cache —
  call the module's `reset_memory()` or restart the process. Likewise `load_config`/
  `load_keys` are `lru_cache`d (`config.py:27,50`): config/.env edits need a new process.

## Provenance and maintenance

All claims verified 2026-07-11 against branch `claude/skill-library-handoff-vm2gku`.
Re-verify before trusting, in one line each:

- Symptom messages still match: `grep -rn "ABORT: only\|Not enough rebalance\|Missing.*_API_KEY\|workflow not found\|rejected the token" scripts/ src/ webapp.py`
- Price source order + negative-cache TTL: `grep -n "_NEG_TTL\|_from_fmp\|_from_stooq\|_fetch_yfinance" src/allocator/data/prices.py`
- Prefetch still non-destructive: `grep -n "NON-DESTRUCTIVE" src/allocator/data/prices.py` (expect the force-branch comment, ~line 183)
- Degenerate-universe threshold: `grep -n "n_uni < 50" scripts/weekly_run.py`
- FRED series map / hy_spread bug still open: `grep -n "hy_spread" scripts/smoke_data.py && grep -n "credit_spread" src/allocator/data/fred.py`
- Regime trigger (21-day z > 1.5): `grep -n "cs_chg21_z" src/allocator/regime.py`
- Cache namespaces: `grep -rno '"\(prices\|prices_neg\|fred\|yf_grades\|fmp_[a-z]*\|fh_[a-z]*\)"' src/allocator/data/ | sort -u`
- PyYAML trap: `python -c "import yaml; print(repr(yaml.safe_load('a: 1.5e9')['a']))"` (expect the string `'1.5e9'`)
- Webapp env contract: `grep -n "GH_TOKEN\|GH_REPO\|GH_REF\|REPORT_BRANCH\|APP_USER" webapp.py`
- CI schedule/flags: `grep -n "cron\|weekly_run" .github/workflows/build-report.yml`
