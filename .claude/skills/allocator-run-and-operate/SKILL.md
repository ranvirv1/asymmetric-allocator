---
name: allocator-run-and-operate
description: >
  Operational runbook for RUNNING and DEPLOYING the Asymmetric Allocator: command anatomy for
  every entry point (weekly_run.py, run_allocation.py, run_backtest.py, sweep.py,
  fetch_universe.py, refresh_prices.py, webapp.py), what a healthy run prints, where artifacts
  land (reports/latest.html, reports/history/, data/snapshots/, data/cache/, logs/weekly.log,
  the live-report branch), the cloud build path (dashboard Refresh -> GitHub Actions
  build-report.yml -> Render), the Monday automation, GH token rotation, schedule changes,
  Safe vs Returns mode, and recovering from a failed Actions build. Load this when the task is
  "run the weekly book", "rebuild the report", "trigger/monitor/fix the GitHub Actions build",
  "is the dashboard stale", "where did the report/snapshot/history file go", "rotate the
  token", "change the schedule", or "view the dashboard from my phone".
---

# Running and operating the Asymmetric Allocator

This skill is the operator's manual: how to run each entry point, what output means the run
was healthy, where every artifact lands, and how the cloud publish path works. All commands,
flags, filenames, and console lines below were verified against the repo on 2026-07-11.

**When NOT to use this skill:**
- First-time environment setup (venv, deps, .env keys, Windows/Linux traps) → **allocator-build-and-env**.
- A run failed or produced weird output and you need to diagnose why → **allocator-debugging-playbook**.
- What a config value or flag *means* and whether it is production or experimental → **allocator-config-and-flags**.
- Whether a result is *valid evidence* (tune/validate discipline) → **allocator-validation-and-qa**.

Context in one paragraph: the engine ranks the S&P 500 by price relative strength ("RS" —
each stock's return vs the index, percentile-ranked), gates exposure by a macro regime verdict
(RISK_ON / MIXED / COMPRESSION), sizes a ~£10,000 weekly book, and renders a single-file HTML
dashboard. It is decision-support only — it proposes; R places orders manually. The default
signal is RS-only (analyst-revision momentum "ERM" is opt-in via a flag because it failed the
out-of-sample ablation — see allocator-failure-archaeology).

Conventions used below: PowerShell commands assume the repo root on R's Windows box with
`.venv` created; bash commands assume a Linux checkout with the package installed
(`pip install -r requirements.txt && pip install -e .`). On Windows always set `PYTHONUTF8=1`
first (the report and console output contain non-ASCII characters). Commands that hit
FRED/FMP need keys in `.env` — this container has none, so those were verified by
code-reading, not execution.

---

## 1. Command anatomy — every entry point

### 1.1 `scripts/weekly_run.py` — THE production entry point

Builds the weekly book end-to-end (universe → regime → scoring → classify → size → exits →
report), saves the run record, diffs vs last week, renders the dashboard. This is what the
Windows scheduled task and the GitHub Actions workflow both run.

```powershell
# PowerShell (R's dev box)
$env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\weekly_run.py [YYYY-MM-DD] [flags]
```
```bash
# bash (CI / this container)
python scripts/weekly_run.py [YYYY-MM-DD] [flags]
```

Arguments are positional and order-free: anything matching a known flag is a flag, the first
remaining token is the as-of date (default: today). The full flag set (`FLAGS` in the script):

| Flag | Effect |
|---|---|
| `noopen` | don't auto-open the report in a browser (used by all automation) |
| `norefresh` | skip the data refresh; rebuild off cache (fast re-run) |
| `snapshot` | also bank this week's analyst-consensus snapshot to `data/snapshots/` |
| `research` | also run the RS walk-forward backtest and embed the panel in the report |
| `ermrs` | add ERM to scoring (default is RS-only; ERM is opt-in — it cut CAGR 34%→16% in the ablation) |
| `returns` | force `live.use_regime_gate=false` for this run (full deploy) |
| `safe` | force `live.use_regime_gate=true` for this run (keep the regime cash sleeve) |

No mode flag → whatever `config.yaml` `live.use_regime_gate` says (currently `true` = Safe).

**What a healthy run prints** (exact console lines, in order; `flush=True` so they stream):

```
Refreshing prices + macro for 508 names (this takes a few min) ...   # skipped with norefresh
  prices refreshed: ok=490 miss=18
Building book for 2026-07-11 (signals: RS) ...                       # or RS+ERM with ermrs
  RISK_ON | deploy 85% | 15 anchors, 0 satellites
  changes vs 2026-07-04: 2 buys, 1 sells, 3 adjusts                  # or "(first run — no prior book to diff)"
Banking estimate snapshot for 508 names (spec §8.8) ...              # only with snapshot flag
  snapshot: 412 names -> data/snapshots/estimates_2026-07-11.csv

Report -> /path/to/reports/latest.html
```

(Counts illustrative; line formats verified. With RS-only, satellites are normally 0 and the
satellite budget folds into anchors — that is correct behaviour, not a bug.)

**The degenerate-universe abort.** After building, if fewer than 50 names survived with price
data, the script prints

```
ABORT: only N names have price data — the data provider looks rate-limited. Keeping the previous report (latest.html unchanged). Try again later.
```

and exits with code **2**, *before* touching `latest.html` or the history record. This guard
exists because a rate-limited provider once produced a near-empty book. What to do: the price
feed is incomplete, not the code. Run `scripts/refresh_prices.py` (§1.6) to non-destructively
refill the cache, wait a few minutes if yfinance is rate-limiting, then re-run
`weekly_run.py`. Do not delete `data/cache/` — that makes it worse. In GitHub Actions the
exit-2 fails the build step, so the `live-report` branch keeps serving the previous good
report (§4.4).

Note: the report renders twice — once to a dated file, once to `latest.html` (§2). The
"next auto-run Mon 07:00" stamp in the report is hardcoded in `weekly_run.py` and refers to
the Windows task, not the Actions cron.

### 1.2 `scripts/run_allocation.py` — one-off book, verbose console

Same pipeline for a single date, but no data refresh, no history save, no diff — and it prints
the full allocation table to the console (ticker, weight, GBP, shares, stop). Use it to
inspect a book for an arbitrary date without disturbing the weekly history.

```powershell
$env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\run_allocation.py [YYYY-MM-DD] [research] [ermrs]
```
```bash
python scripts/run_allocation.py [YYYY-MM-DD] [research] [ermrs]
```

Healthy output: regime verdict with numeric score and anchor/satellite/cash budget, bucket
counts and invested %, then an `ALLOCATION:` block, one line per position, ending with the
dated dashboard path. No degenerate-universe guard here — that lives only in `weekly_run.py`.

### 1.3 `scripts/run_backtest.py` — walk-forward backtest + ablations

```powershell
$env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\run_backtest.py [rs]
```
```bash
python scripts/run_backtest.py [rs]
```

`rs` = RS-only suite; without it the default suite includes ERM variants (needs FMP/yfinance
grade data — first run fills caches and takes minutes). Output sections, in order: headline
metrics table (median annual and max drawdown lead, deliberately), `ABLATION — CAGR delta vs
S&P`, `PER-YEAR RETURNS`, `CATCH-RATE` (did the strategy hold each year's top-10 movers before
the move — expect 0–20%, that's normal for momentum), and the honesty banner
(`backtest.caveat_banner`) restating the survivorship upper-bound caveat. Any number you quote
from this output carries that caveat — project law (see allocator-change-control, rule R4).

### 1.4 `scripts/sweep.py` — concentration × regime-gate sweep

```powershell
$env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\sweep.py
```
```bash
python scripts/sweep.py
```

Runs RS top-N for N ∈ {8, 12, 15, 20}, gate on and off, and reports tune window
(2020-01-01..2023-12-31) and validate window (2024-01-01..2026-06-01) side by side, ending
with a "Robust pick" ranked by validate Sortino among above-median tune Sortino. Discipline:
the validate window is quarantined for parameter *selection* — use the robust pick, never
eyeball the validate column (allocator-validation-and-qa has the full rules).

### 1.5 `scripts/fetch_universe.py` — refresh constituents + bulk price fill

```powershell
$env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\fetch_universe.py
```
```bash
python scripts/fetch_universe.py
```

Pulls the current S&P 500 list from Wikipedia into `data/sp500_constituents.csv` (which IS
committed to git), then batch-prefetches full price histories via yfinance in chunks of 40.
Prints a final `Price coverage: X/Y names` line; if X < Y it tells you to re-run after a few
minutes — yfinance rate-limits, and partial coverage is fine because the prefetch is
non-destructive (re-runs only fill gaps).

### 1.6 `scripts/refresh_prices.py` — cache recovery

```powershell
$env:PYTHONUTF8=1; .venv\Scripts\python.exe scripts\refresh_prices.py
```
```bash
python scripts/refresh_prices.py
```

The recovery tool after a rate-limit incident or a degenerate-universe abort. It clears only
the *negative* cache (`prices_neg` — cached "no data" markers, TTL 6h) plus the `^SPX` entry,
then prefetches missing names non-destructively. Everything already cached is kept — never
manually delete `data/cache/` to "fix" prices; delete-then-fetch is exactly the failure mode
that once emptied the cache mid-rate-limit (allocator-failure-archaeology has the story).
Prints `prefetch ok=… miss=… cached=…` and a coverage line.

### 1.7 `webapp.py` — local dashboard server

```powershell
$env:PYTHONUTF8=1; .venv\Scripts\python.exe webapp.py     # -> http://127.0.0.1:8765, auto-opens browser
```
```bash
python webapp.py
```

With no `GH_TOKEN`/`GH_REPO` set, the app runs in **local mode**: the "Refresh data" button
spawns `weekly_run.py noopen <mode>` as a subprocess on your machine (adds `norefresh` unless
the request passes `full=1`), so it needs the full venv and `.env` keys. Env knobs: `PORT`
(default 8765), `HOST` (default 127.0.0.1; see §4.5 for phone access), `APP_USER` +
`APP_PASSWORD` (set BOTH to enable Basic Auth; unset = open, fine locally),
`DATA_DIR`/`REPORTS_DIR` (relocate artifacts). `run_site.bat` wraps this on Windows — but note
all three `.bat` launchers hardcode the original dev path `C:\Users\ranvi\stock`; on any other
machine run the python command directly (documented trap, see allocator-build-and-env).

With `GH_TOKEN`+`GH_REPO` set the same app switches to **cloud mode** — see §3.

---

## 2. Artifact conventions — what lands where

All paths relative to the repo root unless `DATA_DIR`/`REPORTS_DIR` env vars redirect them
(they exist so a cloud host can mount a persistent disk).

| Artifact | Written by | Contents | Regenerable? |
|---|---|---|---|
| `reports/latest.html` | every `weekly_run.py`; webapp pulls it in cloud mode | THE live single-file dashboard | Yes — next run overwrites |
| `reports/dashboard_<YYYY-MM-DD>.html` | `render_dashboard` default path (weekly_run renders this dated copy first, then `latest.html`) | dated report copy | Yes for recent dates (re-run with the date arg) |
| `reports/history/alloc_<YYYY-MM-DD>.json` | `weekly.save_run()` | the book record: as_of, regime verdict, `{ticker: weight/gbp/bucket}` — the input to next week's buys/sells/adjusts diff (`diff_vs_prev`, 0.5pt drift threshold) | **NO — precious** |
| `data/snapshots/estimates_<YYYY-MM-DD>.csv` | `weekly.take_snapshot()` (only with the `snapshot` flag) | banked analyst-consensus rows with a `snapshot_date` column — the accumulating true point-in-time estimate bank for the future ERM re-test | **NO — precious** |
| `data/cache/<ns>__<sha1[:16]>.{json,csv}` | data layer (`allocator/data/cache.py`) | API responses + price frames, namespaced: `prices`, `prices_neg`, `fred`, `yf_grades`, `fmp_profile`, `fmp_grades`, `fmp_estimates`, `fmp_hist`, `fmp_ptc`, `fh_profile`, `fh_metric`, `fh_earn` | Yes — refetchable (slowly) |
| `logs/weekly.log` | `run_weekly_scheduled.bat` (Windows task only) | appended stdout/stderr of each scheduled run | Yes (it's just logs) |
| `live-report` branch (GitHub) | Actions publish step | `latest.html`, `built_at.txt`, `mode.txt` — single commit, force-pushed | Yes — next green build |

**Precious vs regenerable — the operational risk.** `.gitignore` excludes `reports/`,
`data/cache/`, `data/snapshots/`, `logs/`, `.env`, `.venv`. Cache and reports are fine to
lose. But `reports/history/*.json` and `data/snapshots/*.csv` **cannot be regenerated**: the
history files are the week-over-week diff chain, and the snapshots are consensus data that
only existed at the moment of capture. Because they are gitignored, **they exist only on the
machine that produced them**. Today that means: snapshots + history accumulate on R's Windows
box (the Monday 07:00 task); the GitHub Actions runner is ephemeral, so its history record is
discarded after every build (its runs always print "first run — no prior book to diff" and
the cloud report never shows a week-over-week diff). Losing the Windows box loses the entire
estimate bank — there is no off-machine backup in the repo as of 2026-07-11. If you set up a
backup, those two directories are the payload.

---

## 3. The cloud path end-to-end

The build is expensive (pandas over ~500 names; a 512 MB free web host OOMs — that incident
is why this architecture exists) but serving is cheap, so build and serve are split:

```
Phone/browser -> Render webapp ("Refresh data" button)
  -> POST /repos/{GH_REPO}/actions/workflows/build-report.yml/dispatches  (mode: safe|returns)
  -> GitHub Actions ubuntu-latest runner (multi-GB RAM; comments say 16 GB), 30-min timeout:
       pip install -r requirements.txt && pip install -e .
       python scripts/weekly_run.py noopen <mode>          # NOTE: no snapshot flag
       force-push a single fresh commit to the `live-report` branch containing
         latest.html + built_at.txt (UTC ISO timestamp) + mode.txt (safe|returns)
  -> webapp polls the run via the API (phases: queued -> building -> done), then
     GETs latest.html from the live-report branch and serves it
```

Key facts (all from `.github/workflows/build-report.yml`, `webapp.py`, `render.yaml`, DEPLOY.md):

- **Schedule:** cron `13 11 * * 1` — Mondays 11:13 UTC (off-minute on purpose, avoids the
  top-of-hour Actions rush). Scheduled runs have an empty `mode` input → default **safe**.
- **Manual trigger:** GitHub → the repo → **Actions → build-report → Run workflow** → pick
  mode `safe` or `returns` → Run. Or tap Refresh on the dashboard. Or via CLI:
  `gh workflow run build-report.yml -f mode=safe`.
- **Freshness check:** read `built_at.txt` on the `live-report` branch —
  `https://github.com/<owner>/<repo>/blob/live-report/built_at.txt`, or
  `git fetch origin live-report && git show origin/live-report:built_at.txt`. `mode.txt`
  tells you which mode built it. The branch is always exactly one commit (force-pushed), so
  the commit message/date is an equivalent check.
- **Concurrency:** the workflow declares `concurrency: group: build-report,
  cancel-in-progress: false` — two Refresh taps (or a tap during the Monday scheduled run)
  queue instead of racing, so double publishes to `live-report` can't interleave.
- **Render behaviour:** free tier; `render.yaml` blueprint; gunicorn serves `webapp:app`.
  The free instance sleeps after ~15 min idle and takes ~1 min to wake on the next visit
  (per DEPLOY.md). The *report* is never stale because of sleep — GitHub builds it
  independently; the webapp just re-pulls `latest.html` on wake.
- **Secrets split:** FRED/FMP/FINNHUB API keys live in GitHub **Actions secrets** (the build
  needs them); Render only holds `GH_TOKEN`, `GH_REPO`, `GH_REF`, `APP_USER`, `APP_PASSWORD`
  (serving needs no data keys). Never add pandas or data keys to the web side — the web image
  (`requirements-web.txt`: flask/gunicorn/requests only) must stay tiny.

---

## 4. Operational runbook

### 4.1 Rotate the GitHub fine-grained token (the webapp's `GH_TOKEN`)

1. GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → generate
   new. Repository access: **only** `asymmetric-allocator`. Permissions: **Actions → Read and
   write** (dispatch + poll runs), **Contents → Read-only** (pull `latest.html` from
   `live-report`). Nothing else.
2. Render dashboard → the `asymmetric-allocator` service → Environment → replace `GH_TOKEN` →
   save (Render redeploys the service).
3. Verify: open the site, tap **Refresh data**. If the status bar shows
   "GitHub rejected the token (needs Actions: read+write on this repo)" the Actions scope is
   wrong; if it shows "workflow not found …" check `GH_REPO`/`GH_REF` instead — that error is
   about the workflow file's branch, not the token.
4. Revoke the old token on GitHub.

(The Actions workflow itself uses the ephemeral `GITHUB_TOKEN` with `permissions: contents:
write` to force-push `live-report` — that one needs no rotation.)

### 4.2 Change the schedule

Two independent schedules exist (see §5 for why both):

- **Actions (cloud):** edit the cron in `.github/workflows/build-report.yml`
  (`- cron: "13 11 * * 1"`). Times are UTC; keep an off-minute. Merge to the default branch —
  schedules only run from the default branch's workflow file.
- **Windows task (local, the one that banks snapshots):** the task is named
  `AsymmetricAllocator-Weekly`, Mondays 07:00 local, and runs `run_weekly_scheduled.bat`.
  Change it in Task Scheduler (taskschd.msc) or:
  `schtasks /Change /TN "AsymmetricAllocator-Weekly" /ST 07:30` (UNVERIFIED: the task's exact
  registration isn't in the repo — confirm the task name with
  `schtasks /Query /TN "AsymmetricAllocator-Weekly"` before changing it).

### 4.3 Run Safe vs Returns mode, from each surface

Safe = regime gate on (keeps the cash sleeve; validated ~+34% CAGR / −16% max DD). Returns =
gate off (full deploy; ~+41% / −21%). Both numbers carry the survivorship upper-bound caveat.

| Surface | How |
|---|---|
| CLI | `weekly_run.py safe` or `weekly_run.py returns` (per-run override; no flag = config default, currently Safe) |
| Dashboard (Render or local webapp) | Safe/Returns toggle in the top bar — switching mode immediately triggers a rebuild in that mode |
| GitHub Actions manual | Run workflow → `mode` dropdown |
| Actions Monday schedule | always `safe` (empty input defaults) |
| Windows Monday task | no mode flag → config default |
| Permanently | edit `config.yaml` `live.use_regime_gate` (that is a change-control matter — see allocator-change-control) |

`mode.txt` on `live-report` records which mode the served report was built in.

### 4.4 Recover from a failed Actions build

1. Repo → Actions → build-report → the red run → open the **Build the book** step log.
2. Read the tail. The known failure signatures:
   - `ABORT: only N names have price data …` + exit code 2 — the degenerate-universe guard.
     Provider rate-limited. The publish step never ran, so `live-report` still serves the
     previous good report; nothing is broken. Re-run the workflow later (Actions → the failed
     run → **Re-run all jobs**, or tap Refresh again). If it recurs across hours, go to
     allocator-debugging-playbook.
   - `no report produced` in the publish step — the build "succeeded" without writing
     `reports/latest.html` (the publish step guards with `test -f`). Shouldn't happen; treat
     as a code regression and debug locally.
   - Missing-key `RuntimeError` (`Missing FRED_API_KEY …`) — an Actions secret was removed or
     expired; re-add under repo Settings → Secrets and variables → Actions.
   - 30-minute timeout — usually rate-limited price fetching grinding through retries; re-run
     later.
3. The webapp surfaces failures as `GitHub build failure` in the status bar with a
   "view build ↗" link straight to the run — start there when reported from the phone.
4. Nothing to roll back, ever: a failed build never touches `live-report`.

### 4.5 View a *local* webapp from your phone (no cloud)

Bind to all interfaces and use the machine's LAN address:

```powershell
$env:PYTHONUTF8=1; $env:HOST="0.0.0.0"; .venv\Scripts\python.exe webapp.py
```
```bash
HOST=0.0.0.0 python webapp.py
```

Then browse to `http://<machine-LAN-IP>:8765` from a phone on the same Wi-Fi (find the IP with
`ipconfig` / `ip addr`). Set `APP_USER`/`APP_PASSWORD` (both, or auth stays disabled) if the
network isn't trusted. Note the auto-open-browser only fires when HOST is
127.0.0.1/localhost — with 0.0.0.0 you open the URL yourself, and Windows Firewall may prompt
to allow python on the first run (UNVERIFIED: firewall behaviour depends on the machine).

---

## 5. The weekly cadence — what Monday actually does

Two automations fire every Monday, and they are NOT equivalent:

| | Windows task `AsymmetricAllocator-Weekly` | GitHub Actions `build-report` |
|---|---|---|
| When | Monday **07:00 local** | Monday **11:13 UTC** |
| Runs | `weekly_run.py noopen snapshot` (via `run_weekly_scheduled.bat`, logging to `logs\weekly.log`) | `weekly_run.py noopen safe` — **no `snapshot` flag** (verified in build-report.yml) |
| Snapshot banked? | **YES** → `data/snapshots/` on R's box | **NO** |
| History/diff chain | persists on R's box | ephemeral runner — discarded per run |
| Publishes | local `reports\latest.html` (desktop shortcut) | `live-report` branch → Render dashboard |

**The implication to keep in mind:** the estimate bank — the dataset that will eventually let
ERM be re-tested on true point-in-time consensus instead of the grade-action proxy — grows
**only** through the Windows task. If R's machine is off on a Monday, that week's snapshot is
silently skipped (no alert exists as of 2026-07-11), and the cloud build will never backfill
it because the Actions command has no `snapshot` flag and the runner's disk is discarded
anyway. If a Monday was missed, run `weekly_run.py noopen norefresh snapshot` manually — but
note the consensus captured is *as of when you run it*, not as of Monday; a late snapshot is
better than a gap, and the `snapshot_date` column records the truth. Check the bank's health
by listing `data/snapshots/` — expect roughly one `estimates_*.csv` per week. Making the
snapshot job machine-independent is an open problem tracked in allocator-research-frontier.

---

## Provenance and maintenance

All claims verified against the repo at branch `claude/skill-library-handoff-vm2gku`,
2026-07-11. Facts most likely to drift, and the one-liner to re-verify each:

- Flag set + console lines + abort threshold (50) and exit code (2):
  `grep -n "FLAGS\|ABORT\|sys.exit" scripts/weekly_run.py`
- Actions cron, mode default, missing snapshot flag, concurrency, publish trio:
  `grep -n "cron\|weekly_run\|concurrency\|built_at\|mode.txt" .github/workflows/build-report.yml`
- Dated report filename (`dashboard_<date>.html`): `grep -n "out_path = " src/allocator/report.py`
- History/snapshot paths and record shape: `grep -n "alloc_\|estimates_\|HIST_DIR\|SNAPSHOT_DIR" src/allocator/weekly.py`
- Cache slug scheme + namespaces: `grep -n "_slug" src/allocator/data/cache.py` and
  `grep -rhoE '"(prices|prices_neg|fred|yf_grades|fmp_[a-z_]+|fh_[a-z_]+)"' src/allocator/data/ | sort -u`
- Gitignored (hence machine-local) artifact dirs: `cat .gitignore`
- Webapp env knobs + cloud/local switch: `grep -n "os.getenv" webapp.py`
- Token scopes + Render envs: `grep -n "Actions\|Contents\|GH_TOKEN" DEPLOY.md render.yaml`
- Windows task name/time and what it runs: `grep -n "Monday\|AsymmetricAllocator" README.md`
  and `cat run_weekly_scheduled.bat`
- Mode default: `grep -n -A1 "use_regime_gate" config.yaml`

Unverified-by-execution (label kept in text): Render ~15-min sleep / ~1-min wake (DEPLOY.md
statement, host-controlled), the "16 GB" runner figure (workflow/DEPLOY.md comments; GitHub
may resize standard runners), the `schtasks /Change` recipe (task registration is not in the
repo), and Windows Firewall prompting on `HOST=0.0.0.0`. Live-run console output was verified
by reading the scripts, not by executing them (no API keys in this container).
