---
name: allocator-config-and-flags
description: >
  Complete catalog of every configuration axis of the Asymmetric Allocator: all config.yaml
  keys (default, reader module, production vs reserved/experimental status), every script
  flag (weekly_run.py returns/safe/ermrs/norefresh/noopen/research/snapshot, run_backtest.py
  rs, run_allocation.py research/ermrs), every environment variable (DATA_DIR, REPORTS_DIR,
  GH_TOKEN, GH_REPO, GH_REF, WORKFLOW_FILE, REPORT_BRANCH, APP_USER, APP_PASSWORD, PORT,
  HOST, PYTHONUTF8) and .env API keys, plus the checklist for adding a new option. Load when:
  changing any config value, wondering "what does this flag do", "which flag/env var
  controls X", "is this option actually used", adding a new tunable, or seeing the Safe vs
  Returns mode dial. Includes the PyYAML scientific-notation trap and re-verification
  one-liners.
---

# Allocator Config and Flags

Everything tunable, in one place. Verified against the repo 2026-07-11.

When NOT to use: setting up the environment → `allocator-build-and-env`. Deciding what a
value SHOULD be (evidence, sweeps, gates) → `allocator-change-control` and
`allocator-validation-and-qa`. Day-to-day run commands → `allocator-run-and-operate`.

## 1. config.yaml — every key

`load_config()` (`src/allocator/config.py:27-31`) reads `<repo>/config.yaml` once per
process (**`@lru_cache`** — a config edit needs a fresh process to take effect; the webapp's
subprocess/Actions build always gets a fresh process, an interactive Python session does not).

Status legend: **PROD** = read by live code paths; **RESERVED** = present but no implemented
reader/consumer (do not expect behavior from it); **PARTIAL** = read only under conditions.

| Key | Default | Reader (verified) | Status |
|---|---|---|---|
| `book_size_gbp` | 10000 | `sizer.size_allocation` | PROD |
| `rebalance` | monthly | **no code reads this top-level key** (backtest uses `backtest.rebalance`) | RESERVED (doc-only) |
| `base_currency` | GBP | no code reader (informational) | RESERVED (doc-only) |
| `fx_gbp_usd` | 1.27 | `sizer.size_allocation` (share-count math) | PROD — **manually maintained; drifts** |
| `universe.source` | sp500 | `universe._seed` (`sp500` → data/sp500_constituents.csv, else data/universe_seed.csv) | PROD |
| `universe.min_mktcap_usd` | 1.5e+9 | `universe.build_universe` | PARTIAL — only with FMP key AND `with_mktcap=True`; the live pipeline calls `with_mktcap=False` (`pipeline.py:19`), so in practice OFF |
| `universe.min_adv_usd` | 10.0e+6 | `universe.build_universe` (always) | PROD |
| `universe.index` | russell1000 | no code reader — label only; actual implementation is S&P 500 | RESERVED (aspirational) |
| `weights.ERM/.RS` | .30 / .25 | `scoring.regime_weights` — but only for sub-scores in `active` | PROD (RS always; ERM only with `ermrs`) |
| `weights.FI/.EXP/.CAT/.THM` | .15/.15/.10/.05 | **no implemented sub-score** — never enter `active` | RESERVED |
| `regime_modifiers.*` | RISK_ON {RS:1.4,EXP:0.7}, MIXED {}, COMPRESSION {RS:0.6,EXP:1.5} | `scoring.regime_weights` (only keys in `active` matter → EXP entries are RESERVED) | PROD (RS parts) |
| `regime_budgets.*` | RISK_ON .45/.40/.15; MIXED .55/.25/.20; COMPRESSION .65/.10/.25 | `regime.compute_regime` → `sizer`, `backtest.target_weights` | PROD |
| `caps.anchor_max` | .20 | `sizer`, `backtest.target_weights` | PROD |
| `caps.satellite_max` | .05 | `sizer` | PROD |
| `caps.satellite_total_max` | .45 | `sizer` | PROD |
| `cuts.A_cut/S_cut/E_hi/E_lo` | 80/75/65/40 | `classifier.classify` | PROD (live book only; the backtest ranks top-N directly, no cuts) |
| `cuts.max_anchors` | 15 | `classifier` (evidence: out-of-sample sweep, n15 robust pick) | PROD |
| `cuts.max_satellites` | 6 | `classifier` | PROD |
| `live.use_regime_gate` | true | `sizer.size_allocation` — the Safe/Returns dial (see §4) | PROD |
| `exits.stop_atr/trim1_at/trim2_at/trail_atr` | 2.5/.50/1.00/3.0 | `exits.attach_exits` | PROD |
| `kelly_fraction` | 0.25 | `sizer._kelly_tilt` | PROD |
| `costs_bps` | 8 | `backtest.run_strategy` (per side, × two-way turnover) | PROD (backtest only) |
| `backtest.start/end` | 2020-01-01 / 2026-06-01 | `backtest.run_suite` | PROD |
| `backtest.rebalance` | monthly | informational (dates are always month-end snapped, `backtest.rebalance_dates`) | RESERVED (doc-only) |
| `backtest.tune_window` | 2020-01-01..2023-12-31 | `scripts/sweep.py` | PROD — tuning allowed here ONLY |
| `backtest.validate_window` | 2024-01-01..2026-06-01 | `scripts/sweep.py` | PROD — **QUARANTINED (rule R1)** |
| `regime.breadth_riskon` | 0.55 | `regime.compute_regime` | PROD |
| `regime.vix_lookback_days` | 252 | **no code reader** — VIX median lookback is hardcoded `tail(252)` (`regime.py:130`) | RESERVED (drift trap: changing the key changes nothing) |
| `regime.credit_spread_series` | BAA10Y | **no code reader** — series is hardcoded in `fred.SERIES` | RESERVED (drift trap; change `fred.py` instead) |

## 2. Script flags (all verified against source)

| Script | Flags / args | Semantics |
|---|---|---|
| `scripts/weekly_run.py` | `YYYY-MM-DD` | run as-of a specific date (default today) |
| | `noopen` | don't open the browser (scheduled/CI use) |
| | `norefresh` | skip the live data refresh; run off cache (fast re-run) |
| | `research` | also run the RS backtest suite and embed the panel |
| | `ermrs` | add ERM to scoring — **default is RS-only** (ERM cut CAGR 34→16 OOS) |
| | `snapshot` | also bank this week's estimate snapshot to data/snapshots/ |
| | `returns` | force `live.use_regime_gate=false` (full deploy) |
| | `safe` | force `live.use_regime_gate=true` (keep cash sleeve) |
| `scripts/run_backtest.py` | `rs` | RS-only suite (no ERM/FMP calls); default = full suite incl. ERM ablations |
| `scripts/run_allocation.py` | `YYYY-MM-DD`, `research`, `ermrs` | one-off book; same semantics as above |
| `scripts/sweep.py` | none | fixed n8/12/15/20 × gate on/off sweep |
| `scripts/fetch_universe.py` | none | refresh Wikipedia constituents + bulk price prefetch |
| `scripts/refresh_prices.py` | none | non-destructive cache refill |
| `scripts/smoke_data.py`, `test_regime.py`, `test_scoring.py` | none | diagnostics (see `allocator-diagnostics-and-tooling`) |

Unknown strings that aren't in `weekly_run.py`'s `FLAGS` set are treated as the date — a
typo like `retuns` becomes a date-parse error later, not a flag warning.

## 3. Environment variables and secrets

| Var | Used by | Effect |
|---|---|---|
| `FRED_API_KEY` | `.env` / Actions secret | REQUIRED for the regime gate (`fred.py` raises without it) |
| `FMP_API_KEY` | `.env` / Actions secret | optional — primary price source + profiles when present |
| `FINNHUB_API_KEY` | `.env` / Actions secret | optional — fundamentals/earnings backup stubs |
| `ALPACA_API_KEY/_SECRET` | `.env.example` only | **no code reads these** (verified `grep -rn ALPACA src scripts webapp.py` → only .env.example). Reserved; also note rule R2: no autotrading |
| `DATA_DIR` | `config.py` | relocate data/ (cache, snapshots) — cloud persistent disk |
| `REPORTS_DIR` | `config.py`, `webapp.py` | relocate reports/ |
| `PYTHONUTF8=1` | Windows runs, CI | prevents cp1252 UnicodeEncodeError in console output |
| `GH_TOKEN`, `GH_REPO` | `webapp.py` | BOTH set → cloud build mode (dispatch Actions, pull live-report); else local subprocess mode |
| `GH_REF` | `webapp.py` | branch the workflow lives on (default `main`) |
| `WORKFLOW_FILE` | `webapp.py` | default `build-report.yml` |
| `REPORT_BRANCH` | `webapp.py` | default `live-report` |
| `APP_USER`, `APP_PASSWORD` | `webapp.py` | BOTH set → Basic Auth gate; either missing → site is OPEN |
| `PORT`, `HOST` | `webapp.py` | default 8765 / 127.0.0.1; `HOST=0.0.0.0` for LAN/phone |

GitHub Actions workflow input: `mode` = `safe` | `returns` (default safe; the cron run gets
safe via the `|| 'safe'` fallback).

## 4. The mode dial (Safe vs Returns) — three surfaces, one truth

`live.use_regime_gate`: `true` = keep the regime cash sleeve (validated ~+34% CAGR / −16%
maxDD); `false` = deploy the whole book into anchors (~+41% / −21%). Control surfaces:

1. `config.yaml live.use_regime_gate` — the at-rest default.
2. `weekly_run.py returns|safe` — **overrides config for that run** (mutates the loaded cfg
   dict, `weekly_run.py:36-39`).
3. Dashboard toggle / Actions `mode` input — becomes surface 2 (`webapp.py` dispatches the
   workflow with `mode`, the workflow passes it as the flag).

Precedence: flag > config. The published report records its mode in `mode.txt` on the
live-report branch.

## 5. Adding a config option — checklist

1. **YAML trap first:** scientific notation MUST have a signed exponent (`1.5e+9`, never
   `1.5e9` — PyYAML 1.1 parses the latter as a string; verified 2026-07-11).
2. Add the key to `config.yaml` with a comment stating units, default rationale, and the
   evidence (sweep/ablation) behind the number.
3. Read it via `load_config()` in exactly one module; remember the lru_cache (fresh process
   to pick up edits).
4. If it changes book/backtest behavior → it needs an ablation or sweep before becoming the
   default: route through `allocator-change-control` (rule R3).
5. Update the table in THIS skill (status PROD/RESERVED/PARTIAL) and, if it has a golden
   value, `allocator-validation-and-qa`.
6. Beware the RESERVED drift traps above (`regime.vix_lookback_days`,
   `regime.credit_spread_series`): if you make one live, delete its row from RESERVED.

## Provenance and maintenance

Written 2026-07-11; every reader claim verified by grep against the working tree.
Re-verification one-liners:
- Config keys: `python3 -c "from allocator.config import load_config; import json; print(json.dumps(load_config(), indent=1, default=str))"`
- weekly_run flags: `grep -n "FLAGS" scripts/weekly_run.py`
- Env vars: `grep -rn "os.getenv" src/allocator webapp.py`
- Reserved keys still unread: `grep -rn "vix_lookback_days\|credit_spread_series\|ALPACA" src scripts webapp.py`
- Dial plumbing: `grep -n "use_regime_gate" config.yaml src/allocator/sizer.py scripts/weekly_run.py`
- YAML trap: `python3 -c "import yaml; print(repr(yaml.safe_load('a: 1.5e9')['a']))"` (expect `'1.5e9'`)
Volatile: `fx_gbp_usd` (manual), headline CAGR/DD numbers (drift as months accrue), the
n15/threshold values if a new sweep is accepted.
