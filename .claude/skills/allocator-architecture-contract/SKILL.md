---
name: allocator-architecture-contract
description: >
  The architecture contract for the Asymmetric Allocator repo: the M1-M9 pipeline map,
  the load-bearing design decisions and WHY each exists, the invariants any change must
  preserve, and the known-weak points stated plainly. Load this when you are about to
  MODIFY, EXTEND, or REVIEW code in src/allocator/ (universe.py, regime.py, scoring.py,
  classifier.py, sizer.py, exits.py, backtest.py, pipeline.py, report.py, data/*.py),
  webapp.py, Dockerfile, render.yaml, or .github/workflows/build-report.yml; when you
  need to know which module owns a responsibility, why the code is shaped the way it is
  ("why is the cache permanent?", "why percentile ranks?", "why does the web image have
  no pandas?", "why is the regime computed before scoring?"), what must not break, or
  where the honest limitations are before making claims. Not an operational runbook and
  not a history lesson - see "When NOT to use this skill" at the end.
---

# Allocator architecture contract

**What this system is (one paragraph).** A point-in-time, regime-gated S&P 500 momentum
allocation engine in Python 3.11 + pandas. Once a week it proposes a ranked,
risk-budgeted book (~£10,000, GBP base, US-listed names) that the owner ("R") reviews
and places manually via IBKR. It is decision-support only — there is no broker
integration and never will be (`sizer.py:141`, `exits.py:2`). The code was built to a
spec whose document is NOT in the repo; comments referencing "spec §X" are the surviving
record — restate their content, never cite "§X" as if a reader can look it up.

All facts below were verified against the working tree on **2026-07-11** (branch
`claude/skill-library-handoff-vm2gku`). Citations are `file:line` in this repo.

---

## 1. The pipeline: M1 → M9

Milestone numbering note: **there is no module labelled M3** — the numbering jumps
M2 → M4 (grep for `M3` across `*.py` finds nothing). The data layer
(`src/allocator/data/`) is unnumbered infrastructure shared by every milestone.

```
                       ┌─────────────────────────────────────────────┐
                       │        data layer  src/allocator/data/       │
                       │  prices.py  fred.py  estimates.py  fmp.py    │
                       │  finnhub.py  constituents.py  cache.py       │
                       └──────────────────┬──────────────────────────┘
                                          │ (all point-in-time sliced to <= as_of)
   M1 universe.py ──► M2 regime.py ──► M4 scoring.py ──► M5 classifier.py
   candidate set      RISK_ON/MIXED/     RS + ERM          ANCHOR / SATELLITE
   + ADV filter       COMPRESSION        percentile        / WATCH buckets
                      sets budgets       WinnerScore
                                          │
                      ┌───────────────────┘
                      ▼
   M6 sizer.py ──► M7 exits.py ──► M9 report.py ──► reports/latest.html
   weights + £     stops/trims      single-file HTML dashboard
                                          ▲
   M8 backtest.py — walk-forward harness that re-runs M1→M4 (+ top-N selection)
   at every monthly rebalance date; the go/no-go evidence gate for everything.

   Orchestrators: pipeline.run_live() = M1→M2→M4→M5→M6→M7 for one date
                  (pipeline.py:1, 19-25); weekly.py = refresh/snapshot/save/diff
                  around it; scripts/weekly_run.py is the entry point.
```

| Mod | File (src/allocator/) | Responsibility | Key outputs |
|-----|----------------------|----------------|-------------|
| M1 | `universe.py` | Point-in-time investable set: `sp500_constituents.csv` seed (~503 names) + `delisted.csv` overlay (5 names), ADV filter always; market-cap filter only with FMP key AND `with_mktcap=True` (universe.py:103-136) | `UniverseResult{as_of, members[ticker,sector,industry,mktcap,adv,source], notes}` |
| M2 | `regime.py` | Macro regime verdict from FRED (DFF, DGS10, DGS2, BAA10Y, VIXCLS) + ^SPX trend + breadth (% above own 200dma). Rule layer: below-200dma OR spreads widening fast → COMPRESSION; trend up + spreads tight + breadth ≥ 0.55 → RISK_ON; else MIXED (regime.py:153-171) | `RegimeResult{verdict, regime_score, budget{anchor,satellite,cash}, tilt_weights, components}` |
| M4 | `scoring.py` | Sub-scores RS (price relative strength) and ERM (dated analyst grade actions), each a cross-sectional percentile rank 0-100; regime-modulated WinnerScore blend (scoring.py:1-17) | per-name DataFrame: `winner_score`, `RS`, `ERM`, `erm_covered` |
| M5 | `classifier.py` | Buckets: ANCHOR (score ≥ A_cut=80 AND Extension ≥ E_hi=65), SATELLITE (score ≥ S_cut=75, Extension ≤ E_lo=40, ERM strong), WATCH (classifier.py:47-73). Extension = mean(RS pctile, ADV-size pctile); valuation pctile omitted without FMP (classifier.py:32-44) | `Buckets{anchors, satellites, watch, extension, notes}` |
| M6 | `sizer.py` | Anchors score-weighted, satellites vol-scaled (1/ATR%), iterative per-name caps, quarter-Kelly tilt bounded 0.5-1.5x, GBP conversion at config `fx_gbp_usd` (sizer.py:41-67, 100-118) | `Allocation{rows[ticker,bucket,target_weight,gbp_amount,shares,...], cash_weight}` |
| M7 | `exits.py` | Pre-committed exits attached at allocation time: hard stop = entry − 2.5×ATR, trims at +50%/+100%, trail 3×ATR, catalyst de-rate-on-slip flags from `data/catalysts.csv` (exits.py:1-9, 41-65) | allocation rows merged with `stop_price, trim1_price, trim2_price, trail_rule, catalyst` |
| M8 | `backtest.py` | Monthly walk-forward, point-in-time at each step, 8 bps/side costs, ablation suites (`default_suite`/`rs_suite`), metrics leading with median annual + max drawdown, catch-rate report, honesty banner (backtest.py:1-14, 250-260) | `run_suite()` dict: equity curves, returns, weights_by_date, regimes |
| — | `pipeline.py` | `run_live(as_of)`: M1→M2→M4→M5→M6→M7 for one date (pipeline.py:14-36) | result dict consumed by M9 |
| — | `weekly.py` | `refresh_live_data()`, `take_snapshot()` (banks consensus to `data/snapshots/estimates_<date>.csv`), `save_run()`/`diff_vs_prev()` (`reports/history/alloc_<date>.json`) | run history + week-over-week diff |
| M9 | `report.py` | Single-file HTML dashboard, dark house style, action-first (regime call → changes → book); writes `reports/latest.html` + dated copy (report.py:1-5, 293-298) | the artifact R actually reads |
| — | `data/cache.py` | Disk cache under `data/cache/`, sha1-slugged filenames; permanent for point-in-time data, TTL for live-ish (cache.py:1-5) | `get_json/put_json/get_df/put_df/invalidate/clear` |
| — | `data/prices.py` | Prices: FMP (if key) → stooq → yfinance; full history per ticker cached permanently; negative cache TTL 6 h; stooq JS-challenge session skip flag; non-destructive `prefetch()` (prices.py:107-140, 167-218) | OHLCV frames + indicators (SMA, ATR, trailing return) |
| — | `data/fred.py` | FRED series wrapper; `credit_spread` = BAA10Y (spec wanted BAMLH0A0HYM2 but FRED truncates it to ~3yr) (fred.py:18-27) | float Series per macro series |
| — | `data/estimates.py` | yfinance `dated_grades()` (point-in-time analyst actions, cached permanently) + `snapshot()` (current consensus, banked weekly) (estimates.py:1-13) | ERM inputs + weekly snapshot rows |
| — (serve) | `webapp.py` (repo root) | Flask viewer. Cloud mode (GH_TOKEN+GH_REPO): dispatches the `build-report.yml` GitHub Actions workflow, polls, pulls `latest.html` from the `live-report` branch. Local mode: subprocess build. Basic Auth via APP_USER/APP_PASSWORD (webapp.py:1-17) | the always-on site; serves, never computes |

Note M8 does NOT run M5/M6/M7: `backtest.target_weights()` takes the top-N by
WinnerScore, score- or equal-weights them with the anchor cap, and applies the regime
equity fraction directly (backtest.py:89-109). The backtest tests the *signal + regime
budget*, not the full classifier/sizer book.

---

## 2. Load-bearing design decisions — and WHY

Each of these is deliberate and has a code comment (or an incident) behind it. Do not
"clean them up" without reading the why. The full incident stories live in
**allocator-failure-archaeology**; change gating lives in **allocator-change-control**.

### D1. Point-in-time discipline everywhere (data ≤ as_of)
Any computation at date t may use only data timestamped ≤ t. Enforced by construction:
`fetch_ohlcv(end=...)` slices `df[df.index <= end]` (prices.py:155-158); regime helpers
`_zscore_at`/`_level_at`/`_change` filter `series[series.index <= as_of]`
(regime.py:39-61); ERM filters dated grade actions `d > as_of → skip`
(scoring.py:126-127); the backtest prices holdings via `_price_at` = last close ≤ t
(backtest.py:80-82). Indicators are rolling, "every value at row t uses only data up to
and including t" (prices.py:251-254). **Why:** the walk-forward backtest is "the whole
point: signal vs hindsight" (backtest.py:1) — one leak of future data and every result
is fiction.

### D2. Fetch-full-history-once, slice-everywhere price model
`prices.history()` fetches the FULL daily OHLCV for a ticker once and caches it
permanently; every as-of computation slices that single frame, "so a backtest over many
dates costs one request per ticker, not one per (ticker, date)" (prices.py:107-115).
`fetch_ohlcv()` is deliberately a thin slicing wrapper (prices.py:149-151). The same
pattern applies to FRED: a fixed early start (`FRED_START = "2014-01-01"`) "so a
backtest fetches each series ONCE" (regime.py:25, 91-93) — the ≤ as_of filters make the
extra history harmless. **Why:** a ~500-name universe × ~77 monthly rebalance dates
would otherwise be tens of thousands of HTTP requests against rate-limited free
providers; this model makes it ~500.

### D3. Permanent caching for point-in-time data, TTL for live-ish data
"Point-in-time data (historical prices, dated FRED vintages) never changes, so it is
cached permanently. Live-ish data (current consensus, profiles) takes a TTL"
(cache.py:3-5). Concretely: price frames and `yf_grades` have no max-age
(prices.py:120-122, estimates.py:54-55); FMP/Finnhub JSON reads pass a TTL
(fmp.py:45, finnhub.py:22); empty price results are negative-cached for 6 h only
(`_NEG_TTL`, prices.py:58) "so transient failures don't poison results". The weekly
live run explicitly invalidates what needs to be fresh (`weekly.refresh_live_data`,
weekly.py:25-37). **Why:** history is immutable, so re-fetching it only spends quota;
"today" changes, so it must expire.

### D4. Percentile-rank cross-sectional scoring (ranks, not raw values)
Every sub-score is "a cross-sectional percentile rank (0-100) within universe[t]"
(scoring.py:2-3, `_pct_rank` scoring.py:43-45). Heterogeneous features (3/6/12-mo
excess return, distance from 52-wk high, trend flags; ERM net/breadth/magnitude) are
each rank-transformed and then averaged, and the average is ranked again
(scoring.py:94-102, 155-162). **Why:** the features have incompatible units and scales
— a raw blend would be dominated by whichever feature has the biggest numbers that
month, and outliers would swamp the weights. Ranks put every feature on the same
bounded 0-100 scale within the same date's universe, so the config weights mean what
they say and scores are comparable across dates and regimes.

### D5. Per-name weight renormalisation over available sub-scores
"Per-name weights are renormalised over whichever sub-scores are available, so an
ERM-uncovered name is scored on RS alone rather than penalised to zero"
(scoring.py:187-189; implementation `_row_score`, scoring.py:207-214). Background:
"grade history thins for smaller names / older dates. Names with no actions in the
window get ERM = NaN" (scoring.py:15-16). **Why:** missing analyst coverage is a data
artifact, not information about the stock; zeroing the ERM term would systematically
punish smaller/older names and silently bias the book toward covered mega-caps.

### D6. Regime gate BEFORE stock selection (the ARKK rationale)
M2 runs before M4 in the live pipeline (pipeline.py:19-24) and its verdict feeds the
scoring weights and the sleeve budgets. The module docstring states the reason:
"Classifies the macro regime → sets the risk budget ... BEFORE any stock scoring
matters. This is the lesson from the ARKK study: one −67% year erases three good ones,
so the regime decides how much beta you're allowed to hold" (regime.py:3-5). "No
high-beta satellite sizing in COMPRESSION, full stop (enforced downstream in M6)"
(regime.py:12). **Why:** stock selection cannot save you from a market-wide drawdown;
the survival decision (how much equity at all) is made independently of, and prior to,
the ranking decision (which equities).

### D7. Split build/serve deployment (the OOM rationale)
The web host ONLY serves; the book is built on GitHub Actions. "Builds the weekly
allocation book on GitHub's runners (16 GB RAM — no OOM, unlike the 512 MB web host)
and publishes the rendered report to the `live-report` branch, which the web app
serves" (build-report.yml:3-6). The web image installs only `requirements-web.txt`
(flask/gunicorn/requests — no pandas; requirements-web.txt:1-6) and copies only
`webapp.py` (Dockerfile:14-17). render.yaml pins the same shape (render.yaml:1-12).
**Why:** the first deploy built the book on the 512 MB Render free tier and OOM'd
(the PR #3 incident — story in allocator-failure-archaeology). The web image must
never grow pandas or build deps.

### D8. config.yaml as the single tunable surface
"All thresholds tunable & auditable. The backtester (M8) can sweep any of these"
(config.yaml:1-2); "All tunable thresholds live in config.yaml so the backtester can
sweep them and every run is auditable. API keys live in .env (gitignored) — never in
code or config" (config.py:1-4). **Why:** if a threshold lives in code, it can't be
swept by `scripts/sweep.py`, can't be audited against a past run, and invites silent
tuning. Trap embedded in the file itself: YAML scientific notation needs a signed
exponent — `1.5e+9`, because PyYAML parses `1.5e9` as a *string* (config.yaml:12).
Full config axis inventory: **allocator-config-and-flags**.

### D9. Decision-support-only boundary
"Output is INSTRUCTIONS for R — not auto-orders" (sizer.py:10-11);
"Decision-support only — these are instructions to review and place manually"
(sizer.py:141); exits are "INSTRUCTIONS for R, not auto-orders" (exits.py:2); the
dashboard banner says "it proposes, you place manually" (report.py:288). **Why:** this
is a hard project law (rule R2 in allocator-change-control) — no broker integration,
no auto-orders, ever. Any PR adding order placement is out of contract regardless of
quality.

Two more decisions worth knowing (details in siblings): **RS-only is the validated
live default** — ERM is opt-in via the `ermrs` flag because the walk-forward ablation
showed ERM cut out-of-sample CAGR 34%→16% (weekly_run.py:9-10, 32-33; story in
allocator-failure-archaeology, method in allocator-proof-and-analysis-toolkit); and
**the satellite-budget fold** — with RS-only there are no satellites, so the idle
satellite budget folds into anchors instead of sitting in cash ("this was a real ~40%
cash-drag bug", sizer.py:85-98).

---

## 3. Invariants — testable assertions any change must preserve

State these as pass/fail checks. If your change breaks one, stop and route through
**allocator-change-control**.

| # | Invariant (assertion) | Where enforced / how to check |
|---|----------------------|-------------------------------|
| I1 | No function may read data timestamped > as_of. Every data accessor either takes an `end`/`as_of` bound or is filtered `index <= as_of` by its caller. | prices.py:155-158; regime.py:43, 53, 58; scoring.py:126-127; backtest.py:80-82. Check any new accessor: `grep -n "as_of\|<= t\|index <=" <file>`. A point-in-time audit recipe lives in allocator-proof-and-analysis-toolkit. |
| I2 | The web image has no pandas (and no build deps at all). `requirements-web.txt` contains exactly flask, gunicorn, requests; the Dockerfile copies only `webapp.py`. | `grep -iv "^#" requirements-web.txt` must show only those three; `grep -n "COPY" Dockerfile` must show only requirements-web.txt and webapp.py (Dockerfile:14-17). `webapp.py` must import neither pandas nor allocator (verified: it imports requests/flask/stdlib only, webapp.py:20-31). |
| I3 | Cache writes are overwrite-on-success; never delete-then-fetch. `prefetch(force=True)` re-attempts and overwrites on success but keeps existing data on failure (prices.py:183-188); `cache.put_df/put_json` write only when there is a result to write (prices.py:133-139). | Any new refresh path must not call `cache.invalidate`/`clear` on data it has not yet successfully replaced (the one allowed exception: clearing `prices_neg` stale "no data" markers, prices.py:187, and the weekly run's deliberate fred/yf_grades clears immediately before re-pull, weekly.py:33-36). |
| I4 | The validate window (2024-01-01..2026-06-01) is untouched by tuning. Parameters are picked on the tune window (2020-01-01..2023-12-31); sweep.py reports both windows and its robust pick requires above-median *tune* Sortino ranked by *validate* Sortino (config.yaml:76-77; sweep.py:1-5, 71-76). | Never add code that selects a parameter value by validate-window results. This is rule R1 — evidence standard in allocator-validation-and-qa. |
| I5 | Every backtest output prints/renders the honesty banner (survivorship = upper bound). `backtest.caveat_banner()` (backtest.py:250-260) is printed by `scripts/run_backtest.py:76`; the live dashboard renders the equivalent banner div (report.py:287-291); universe notes carry the SURVIVORSHIP flag (universe.py:138-141). | Any new results-emitting path must include the banner or the equivalent caveat text. |
| I6 | Exactly 1 gunicorn worker serves webapp.py. The refresh-job state is a process-local dict `JOB` (webapp.py:48-49); "One worker keeps the in-memory job state coherent" (Dockerfile:19-21, `--workers 1`; render.yaml:12, `--workers 1`). | If you ever need >1 worker, JOB must first move to shared storage. Check: `grep -n "workers" Dockerfile render.yaml`. |
| I7 | The weekly run aborts (exit 2) rather than publish a degenerate book: universe < 50 names with price data → keep the previous latest.html (weekly_run.py:50-57). | Do not remove or weaken this guard; it exists because a rate-limited provider once produced a near-empty book. |
| I8 | API keys live in `.env` / GitHub Actions secrets only — never in code, config, or skills (config.py:3-4, 50-57; build-report.yml:46-49; render.yaml:30-32 explicitly moves FRED/FMP keys OUT of the web host). | `grep -rn "API_KEY\s*=" src/ scripts/ config.yaml` must only ever find `os.getenv` reads. |
| I9 | The regime verdict and budgets are computed before, and independently of, stock scores (pipeline.py:21-22; backtest.py:284-288 builds regimes per date before running any strategy). | No signal may feed back into the regime verdict. |

---

## 4. Known-weak points — stated plainly

These are honest limitations, not hidden bugs. Do not paper over them in docs or
claims (see allocator-docs-and-claims); several have open campaigns
(survivorship-bias-campaign, allocator-research-frontier).

1. **Survivorship approximation.** The universe is *current* S&P 500 constituents
   (`data/sp500_constituents.csv`, ~503 names) plus a hand-maintained 5-name delisted
   overlay (SIVB, FRC, ATVI, SGEN, SPLK in `data/delisted.csv`) — not true
   point-in-time membership. The code flags it on every build (universe.py:3-6,
   138-141) and the banner calls all backtest returns an UPPER BOUND. This is the #1
   credibility gap; the fix campaign is **survivorship-bias-campaign**.
2. **Market-cap is an approximation:** current shares outstanding × as-of price
   ("point-in-time price, current share count — an approximation flagged in the
   notes", universe.py:79-80, 131). Splits/issuance/buybacks between then and now
   distort historical caps. Mostly latent: the mktcap filter only runs with an FMP key
   AND `with_mktcap=True`, and both the backtest and live pipeline pass
   `with_mktcap=False` (backtest.py:285; pipeline.py:19).
3. **ERM is a grade-action proxy,** not true estimate-revision momentum: it counts
   analyst upgrade/downgrade actions and grade-level changes from yfinance
   (scoring.py:7-9, 109-142), not consensus EPS revisions. Coverage thins pre-2023 and
   for smaller names (scoring.py:15-16; backtest.py:12-13). A clean re-test awaits
   ~1 yr of banked weekly snapshots (`weekly.take_snapshot`, weekly.py:40-56).
4. **`universe.index: russell1000` is an aspirational label** (config.yaml:14) — the
   actual implementation is the S&P 500 list (`universe.source: sp500`,
   config.yaml:10; universe.py:31-36). Nothing reads the `index` key for selection;
   don't be misled by it.
5. **In-memory memos are unbounded within a process:** `_RS_MEMO`/`_ERM_MEMO` keyed by
   (as_of, tickers-tuple) (scoring.py:39-40), `_MEM_PRICES` one full OHLCV frame per
   ticker (prices.py:104), plus `_MEM` dicts in fred.py:30, estimates.py:26,
   fmp.py:30. Fine for a weekly run or one backtest; a long-lived process embedding
   this code will grow without bound. (`prices.reset_memory()`, `fred.reset_memory()`,
   `estimates.reset_memory()` exist and the weekly run calls them.)
6. **Single-threaded sequential per-ticker loops are slow:** breadth loops each ticker
   fetching prices one at a time (regime.py:64-78); RS features are computed per
   ticker in a dict comprehension (scoring.py:86); ADV likewise (universe.py:119).
   Fast when the cache is warm; a cold ~500-name run takes minutes. Only
   `prices.prefetch()` batches (chunk 40 via yfinance, prices.py:167-218).
7. **The webapp `JOB` dict is process-local state** (webapp.py:48-49), so the deploy
   REQUIRES `--workers 1` — verified in Dockerfile:21 and render.yaml:12, with the
   rationale comment at Dockerfile:19-20. Two workers would give inconsistent
   status/refresh behaviour with no error message.
8. **No pytest suite.** `pyproject.toml` points `testpaths = ["tests"]` at a directory
   that does not exist. `scripts/test_regime.py` and `scripts/test_scoring.py` are
   script-style checks (2022 → COMPRESSION, 2023/2025 → RISK_ON; Dec-2022 top-10
   should contain 2023 winners), not pytest, and CI (`build-report.yml`) runs no tests
   at all. How to add real tests: **allocator-validation-and-qa**.
9. Related open defect (owned by allocator-failure-archaeology, noted here so you
   don't trip on it): `scripts/smoke_data.py:` calls `fred.fetch_named("hy_spread")`
   but the key in `fred.SERIES` is `"credit_spread"` → KeyError when a FRED key is
   present (verified 2026-07-11).

---

## 5. When NOT to use this skill

- **You want to RUN or DEPLOY something** (weekly run commands, flags, Render/Actions
  operations, artifact locations, cache refresh) → **allocator-run-and-operate**.
- **You want the history** — what broke, when, why, and the evidence (ERM cut,
  cash-drag bug, OOM incident, stooq challenge, destructive prefetch, ...) →
  **allocator-failure-archaeology**. This skill states only the surviving design
  consequence of each incident.
- Config axes, flags, and env vars in detail → **allocator-config-and-flags**.
  Change gating and the R1-R8 laws → **allocator-change-control**. Domain theory
  (momentum, Kelly, ATR, walk-forward) → **quant-domain-reference**.

---

## 6. Provenance and maintenance

Everything above verified against the working tree on **2026-07-11**. Line numbers
drift; re-verify before relying on a citation. One-liners (bash / CI form; on R's
Windows box use `Select-String` in place of `grep`, e.g.
`Select-String -Path src\allocator\*.py -Pattern "workers"`):

- Pipeline order unchanged: `grep -n "run_live\|universe.build_universe\|compute_regime\|score_universe\|classify\|size_allocation\|attach_exits" src/allocator/pipeline.py`
- No M3 module appeared: `grep -rn "M3" src/ scripts/ webapp.py --include="*.py"` (expect no hits)
- Web image still tiny (I2): `grep -iv "^#" requirements-web.txt && grep -n "COPY\|workers" Dockerfile && grep -n "workers" render.yaml`
- Point-in-time slices intact (I1): `grep -n "index <=" src/allocator/data/prices.py src/allocator/regime.py src/allocator/backtest.py`
- Non-destructive prefetch intact (I3): `grep -n "NON-DESTRUCTIVE" src/allocator/data/prices.py`
- Windows untouched (I4): `grep -n "tune_window\|validate_window" config.yaml` (expect 2020-01-01..2023-12-31 / 2024-01-01..2026-06-01)
- Honesty banner present (I5): `grep -n "caveat_banner" src/allocator/backtest.py scripts/run_backtest.py && grep -n "upper bound" src/allocator/report.py`
- Degenerate-universe guard (I7): `grep -n "n_uni < 50" scripts/weekly_run.py`
- RS-only default still holds: `grep -n "ermrs" scripts/weekly_run.py`
- Delisted overlay size: `grep -cv "^#" data/delisted.csv` (expect 6 = header + 5 names)
- pytest gap still open (weak point 8): `grep -n "testpaths" pyproject.toml; ls tests 2>&1`
- smoke_data defect still open (weak point 9): `grep -n "hy_spread" scripts/smoke_data.py src/allocator/data/fred.py`

If any check disagrees with this file, the repo wins — update this skill and note the
date.
