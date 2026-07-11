---
name: allocator-validation-and-qa
description: >
  What counts as EVIDENCE in the Asymmetric Allocator, the acceptance thresholds a change
  must clear, the golden/certified expectations (regime verdicts by date, winner-recall
  cases, headline backtest numbers), and the recipe for adding a real pytest suite (none
  exists today). Load when: judging whether a result justifies a change, "is this good
  enough to merge/adopt", quoting or updating performance numbers, a golden expectation
  looks violated, writing or planning tests, or asked "how do I test this". Includes four
  verified offline pytest examples. Not the measurement tools themselves
  (allocator-diagnostics-and-tooling) and not research methodology
  (allocator-research-methodology).
---

# Allocator Validation and QA

When NOT to use: running diagnostics → `allocator-diagnostics-and-tooling`. Turning a hunch
into an experiment → `allocator-research-methodology`. Gating/merging mechanics →
`allocator-change-control`.

## 1. The evidence hierarchy (descending strength)

1. **Validate-window walk-forward metrics** (2024-01-01..2026-06-01, untouched out-of-sample)
   — the only evidence that can promote a change to default. One look per question (R1).
2. **Full-window walk-forward with ablation deltas** (`run_backtest.py`) — establishes what
   a rule is worth.
3. **Tune-window results** (2020..2023) — suggestive only; where iteration happens.
4. **Live-book observations** (`reports/history/`) — anecdote until months accumulate.
5. **Eyeballed charts** — never evidence.

Every quoted number carries: the window, the strategy variant, and the survivorship caveat
("universe = current S&P 500 + delisted overlay → upper bound"). That banner is printed by
every backtest (`backtest.caveat_banner`); external claims discipline is in
`allocator-docs-and-claims`.

## 2. Acceptance thresholds

A change that affects the book becomes default only if (rule R3):
- the walk-forward **ablation delta is positive out-of-sample** — better CAGR *without*
  materially worse max drawdown (the go/no-go framing in `backtest.py`'s docstring: "if it
  doesn't beat the S&P out-of-sample, stop and rethink rather than piling on factors");
- for parameter choices, the **sweep robustness rule** holds (from `scripts/sweep.py`,
  verified): rank variants by **validate-window Sortino**, but only among variants whose
  **tune-window Sortino is at or above the median** of all variants. Best validate
  performance alone = curve-fitting the test set.
- **the mechanism explains the result** — a number with no story fails review (see
  `allocator-research-methodology`).

Failing changes get a documented retirement entry in `allocator-failure-archaeology` (the
ERM precedent).

## 3. Golden / certified inventory (as of 2026-07-11 — regenerate, don't trust blindly)

| Golden | Expected | Regenerate with |
|---|---|---|
| Regime verdicts | 2022 quarter-ends → COMPRESSION; 2023-06-30, 2023-12-29, 2025-02-28 → RISK_ON; 2025-06-02 borderline | `python scripts/test_regime.py` (needs FRED key + price cache) |
| Winner recall | Dec-2022 top-10 contains some of NVDA/META/AMD/PLTR/CRM/TSM/AVGO; Dec-2023 some of NVDA/VST/PLTR/AVGO/GEV/CEG/AMZN | `python scripts/test_scoring.py` |
| Headline (gate ON) | ~+34% CAGR / ~−16% maxDD vs S&P +14.5% / −25% | `python scripts/run_backtest.py rs` |
| Headline (gate OFF) | ~+41% CAGR / ~−21% maxDD | `python scripts/sweep.py` (no-reg rows) |
| Concentration | n15 the robust pick among n8/12/15/20 | `python scripts/sweep.py` |
| Catch-rate | 0–20% of each year's top-10 movers | `python scripts/run_backtest.py rs` |
| Config sanity | config_lint CLEAN | `python .claude/skills/allocator-diagnostics-and-tooling/scripts/config_lint.py` |

These DRIFT as new months accrue and the constituent list updates — a small move is data
drift; a large move (sign flips, verdict pattern breaks) is a defect or a real regime event.
Update this table (and README numbers) only through `allocator-change-control`.

## 4. The testing gap — and the recipe to close it

**There is no pytest suite.** `pyproject.toml` already configures
`pythonpath = ["src"]` and `testpaths = ["tests"]` (verified), but `tests/` does not exist
(open item O2). CI (`build-report.yml`) runs zero tests. To close the gap: create `tests/`,
add the files below, and add `pip install pytest && python -m pytest -q` as a CI step —
route the change through `allocator-change-control`.

All four examples below were **executed and passed 2026-07-11** against the current code
(offline, no keys):

```python
# tests/test_scoring.py
import pandas as pd

def test_regime_weights_renormalise():
    from allocator.scoring import regime_weights
    cfg = {"weights": {"ERM": 0.30, "RS": 0.25},
           "regime_modifiers": {"RISK_ON": {"RS": 1.4}}}
    w = regime_weights(cfg, "RISK_ON", ["ERM", "RS"])
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert w["RS"] > w["ERM"]          # 0.25*1.4 = 0.35 outweighs 0.30
```

```python
# tests/test_sizer.py
import pandas as pd

def test_kelly_tilt_bounds():
    from allocator.sizer import _kelly_tilt
    s = pd.Series([0.0, 50.0, 100.0, -500.0, 500.0])
    t = _kelly_tilt(s, 0.25)
    assert (t >= 0.5).all() and (t <= 1.5).all()   # hard clip
    assert t.iloc[1] == 1.0                        # score 50 = no tilt
```

```python
# tests/test_cache.py — DATA_DIR is read at import time, so reload after monkeypatching
import importlib
import pandas as pd

def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import allocator.config as config; importlib.reload(config)
    import allocator.data.cache as cache; importlib.reload(cache)
    df = pd.DataFrame({"close": [1.0, 2.0]},
                      index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    cache.put_df("prices", "TEST|full", df)
    out = cache.get_df("prices", "TEST|full")
    assert out is not None and list(out["close"]) == [1.0, 2.0]
```

```python
# tests/test_classifier.py — synthetic frame, no network
import pandas as pd

def test_classifier_buckets():
    from allocator.classifier import classify
    scored = pd.DataFrame({"RS": [95.0, 90.0, 20.0],
                           "winner_score": [90.0, 85.0, 30.0]},
                          index=pd.Index(["LEAD", "MID", "LAG"], name="ticker"))
    members = pd.DataFrame({"ticker": ["LEAD", "MID", "LAG"],
                            "adv": [5e9, 1e9, 1e7]})
    cfg = {"cuts": {"A_cut": 80, "S_cut": 75, "E_hi": 65, "E_lo": 40,
                    "max_anchors": 15, "max_satellites": 6}}
    b = classify(scored, members, cfg)
    assert "LEAD" in b.anchors.index
    assert "LAG" in b.watch.index
```

Test-writing rules for this repo: offline-first (no keys, no network — mock or synthesize);
pure-math functions first (they're the invariants); anything touching `DATA_DIR`/cache uses
`tmp_path` + reload as above; never assert exact backtest returns (they drift) — assert
structure, bounds, and invariants instead.

## 5. Pre-merge checklist by change class

| Change class | Must run / show |
|---|---|
| config threshold | config_lint CLEAN + the sweep/ablation that justifies the value |
| new/enabled signal | full ablation suite, OOS delta positive (R3) |
| data-source change | smoke sections 1–4, price_coverage ≥ current level, one weekly_run |
| exit/risk rule | ablation + the exits table renders (run_allocation.py on a cached date) |
| deploy/CI | the workflow runs green once manually; web image still pandas-free |
| docs/numbers | numbers regenerated from the commands in §3, caveats attached |

## Provenance and maintenance

Written 2026-07-11. Robust-pick rule restated from `scripts/sweep.py:71-75`; golden values
from README/script sources; the four pytest examples executed against the working tree.
Re-verify on touch:
- goldens: run the commands in §3 (needs keys + cache)
- tests/ still absent: `ls tests 2>&1`
- pyproject test config: `grep -n testpaths pyproject.toml`
- CI still testless: `grep -n pytest .github/workflows/build-report.yml` (no hits = still open)
- snippets still pass: copy to a temp dir and `python -m pytest -q`
