---
name: allocator-build-and-env
description: >
  Recreate the Asymmetric Allocator environment from scratch on any of its three targets:
  R's Windows dev box (venv, .env keys, .bat launchers, scheduled task), a Linux/CI/cloud
  container (the GitHub Actions recipe), or the web-serve-only host (Render/Docker, no
  pandas). Load when: setting up a fresh checkout, "pip install" or import fails
  (ModuleNotFoundError: allocator), keys are missing, deciding which requirements file to
  install, bootstrapping the price cache for the first time, UnicodeEncodeError on Windows,
  or the .bat files point at the wrong path. Covers exactly which API keys each feature
  needs and what runs with no keys at all.
---

# Allocator Build and Environment

Three environment targets. Pick yours, follow top to bottom. Verified 2026-07-11.

When NOT to use: day-to-day running/deploying an already-working checkout →
`allocator-run-and-operate`. What a flag/env var means → `allocator-config-and-flags`.
Runtime failures after setup → `allocator-debugging-playbook`.

## 0. Install truth (applies everywhere)

**`pip install -e .` alone does NOT install dependencies.** `pyproject.toml` declares no
`dependencies` list (verified) — deps live in `requirements.txt`. The README's short install
line under-specifies this. The correct sequence is always:

```
pip install -r requirements.txt
pip install -e .
```

(the same order CI uses, `.github/workflows/build-report.yml:40-43`). The editable install
is what makes `import allocator` work (`[tool.setuptools.packages.find] where = ["src"]`).

## 1. Windows dev box (R's daily driver)

```powershell
# from the checkout root
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
copy .env.example .env      # then fill in the keys (see §4)
$env:PYTHONUTF8 = 1         # per session; the .bat files set it themselves
```

**Why PYTHONUTF8:** the Windows console defaults to cp1252; the scripts print unicode
(arrows, ✓) and will UnicodeEncodeError without it. Every script header and .bat file sets it.

**The .bat launchers** (`run_site.bat`, `run_weekly.bat`, `run_weekly_scheduled.bat`)
hardcode `cd /d "C:\Users\ranvi\stock"` — the original dev path. On any other checkout,
edit that line to your path (open item O4 in `allocator-failure-archaeology`).

**The scheduled task:** a Windows task named `AsymmetricAllocator-Weekly` runs
`run_weekly_scheduled.bat` Mondays 07:00 local → `weekly_run.py noopen snapshot`, appending
to `logs\weekly.log`. The task registration itself is NOT in the repo; recreate with:

```powershell
schtasks /Create /TN "AsymmetricAllocator-Weekly" /SC WEEKLY /D MON /ST 07:00 `
  /TR "C:\path\to\checkout\run_weekly_scheduled.bat"
```

(UNVERIFIED beyond schtasks syntax — the original registration parameters aren't recorded;
the .bat is the source of truth for what it must run. Note this task is the ONLY thing that
banks estimate snapshots — see O6 in `allocator-failure-archaeology`.)

## 2. Linux / CI / cloud container

Mirror the CI recipe (`.github/workflows/build-report.yml`): Python **3.11**, then §0.
Keys come from the environment (Actions secrets), not a .env file — `load_dotenv` is a
no-op when `.env` is absent and `os.getenv` picks up real env vars.

```bash
python3 -m venv .venv && . .venv/bin/activate   # or use system python 3.11
pip install -r requirements.txt
pip install -e .
export FRED_API_KEY=... FMP_API_KEY=... PYTHONUTF8=1
python scripts/weekly_run.py noopen safe
```

Container trap (seen in the Claude remote container 2026-07-11, Debian-based, may not apply
elsewhere): a debian-packaged `blinker` blocks flask's install with "Cannot uninstall
blinker … RECORD file not found". Fix: `pip install --ignore-installed blinker`, then §0.

## 3. Web-serve-only host (Render / Docker)

The web host NEVER builds the book (rule R6 — the OOM incident, `allocator-failure-archaeology`
A3). It installs **`requirements-web.txt` only** (flask, gunicorn, requests — no pandas):

```bash
pip install -r requirements-web.txt
gunicorn webapp:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

`--workers 1` is load-bearing: the in-process `JOB` dict tracks build state; more workers
desynchronize the status endpoint (see `allocator-architecture-contract`). Render reads
`render.yaml`; Docker uses the repo `Dockerfile` (same command). Required env:
`GH_REPO`, `GH_TOKEN` (fine-grained: Actions R/W + Contents R), `APP_USER`, `APP_PASSWORD`.

## 4. API keys — what needs what

| Key | Needed for | Without it |
|---|---|---|
| `FRED_API_KEY` | regime gate (M2) — hence weekly book, backtest, sweep | `RuntimeError: Missing FRED_API_KEY` the first time `compute_regime` runs (`config.py Keys.require`) |
| `FMP_API_KEY` | primary price history source; company profiles / mktcap filter | prices fall back to stooq → yfinance; mktcap filter skipped (noted in universe notes) |
| `FINNHUB_API_KEY` | fundamentals/earnings backup stubs (`finnhub.py`) | those helpers raise if called; nothing in the default pipeline calls them |

Free keys: FRED (fred.stlouisfed.org), FMP (financialmodelingprep.com, 250 req/day free),
Finnhub (finnhub.io). `.env` is gitignored — never commit it (rule R8). ALPACA_* lines in
`.env.example` are read by nothing (verified; and rule R2 forbids autotrading anyway).

**What runs with NO keys at all:** price fetching (stooq/yfinance), `fetch_universe.py`,
`refresh_prices.py`, `smoke_data.py` sections 1–4, indicator math. Anything touching the
regime (weekly book, backtest, sweep, test_regime) requires FRED.

## 5. First-run bootstrap (order matters)

```powershell
# 1. constituents + bulk price cache (~500 names; several minutes; partial is normal)
.\.venv\Scripts\python.exe scripts\fetch_universe.py
# 2. if coverage < ~95%, wait a few minutes (yfinance rate limit) and re-run either:
.\.venv\Scripts\python.exe scripts\refresh_prices.py
# 3. sanity: data layer end-to-end (known bug: section 5 KeyErrors if FRED key set — O1)
.\.venv\Scripts\python.exe scripts\smoke_data.py
# 4. first book
.\.venv\Scripts\python.exe scripts\weekly_run.py
```

`fetch_universe.py` itself prints the re-run advice on partial coverage (verified in the
script). First backtest run additionally fills grade caches and is slow; later runs are fast
(everything point-in-time is cached permanently in `data/cache/`).

## 6. Disk layout created at runtime

| Path | Contents | Regenerable? |
|---|---|---|
| `data/cache/` | namespaced API/price cache | yes (refetch) |
| `data/snapshots/` | weekly estimate snapshots | **NO — precious** (the ERM re-test dataset) |
| `reports/latest.html` + dated copies | dashboards | yes |
| `reports/history/alloc_<date>.json` | book records for week-diff | **NO — precious** |
| `logs/weekly.log` | scheduled-task log | n/a |

All gitignored. `DATA_DIR` / `REPORTS_DIR` env vars relocate them (cloud persistent disk).

## Known traps (symptom → fix)

- `ModuleNotFoundError: allocator` → the editable install is missing in THIS interpreter:
  `pip install -e .` with the same python you're running.
- `UnicodeEncodeError: 'charmap' codec` → `$env:PYTHONUTF8 = 1`.
- pandas installed but flask install fails on Debian → `pip install --ignore-installed blinker`.
- yfinance bulk fetch misses many names on first run → normal; re-run `refresh_prices.py`
  after a few minutes (non-destructive).
- `.bat` opens the wrong directory → edit the hardcoded `cd /d` path.

## Provenance and maintenance

Written 2026-07-11. §0 verified by reading pyproject.toml and executing the install in a
Linux container; Windows commands verified against the .bat files and README (not executed —
no Windows box here); schtasks recipe UNVERIFIED against the original registration.
Re-verify on touch:
- deps still not in pyproject: `grep -n dependencies pyproject.toml`
- CI recipe unchanged: `grep -n "pip install" .github/workflows/build-report.yml`
- web deps still tiny: `cat requirements-web.txt`
- key requirements: `grep -n "require(" src/allocator/data/fred.py src/allocator/data/fmp.py src/allocator/data/finnhub.py`
- python floor: `grep -n requires-python pyproject.toml`
