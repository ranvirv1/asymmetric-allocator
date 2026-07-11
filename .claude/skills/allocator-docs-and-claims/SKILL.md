---
name: allocator-docs-and-claims
description: >
  Docs of record, house writing style, and external claims discipline for the Asymmetric
  Allocator. Load when: editing README.md, DEPLOY.md, config.yaml comments, or any module
  docstring; writing a new module/script header; deciding WHERE a fact should be documented
  ("which doc owns this?"); updating documentation after a results change, a new flag, or a
  settled investigation; drafting anything external-facing (blog post, repo description,
  résumé line, message to another person) that states what this project is or what its
  numbers show; asked "can we claim X?", "is this novel?", "how do I share these results?";
  or reproducing/publishing backtest numbers. NOT for writing skills themselves (follow the
  library's own conventions) and NOT for validation thresholds or golden expectations (use
  allocator-validation-and-qa).
---

# Allocator docs and claims

Two jobs in one skill: (A) keep the project's documents of record coherent — one home per
fact, written in the house style — and (B) keep every external statement about the project
inside what the evidence actually supports. Both exist because of the same project law:
**every performance number carries the survivorship/upper-bound caveat, and no claim
outruns its ablation** (non-negotiables R4 and R3 — rationale and incidents in
allocator-change-control).

Background you need: the original spec document ("spec §1–§9", milestones M1–M9) is **NOT
in the repo**. The module docstrings are the surviving design record. Never write "see
spec §X" as if a reader can look it up — restate the content. (As of 2026-07-11.)

---

## 1. The documents of record — who owns which fact

| Document | Owns | Character |
|---|---|---|
| `README.md` | The public promise: what it does, **the validated numbers (with caveats)**, the Safe/Returns dial, the limitations list, script table, data sources | Evidence-led and limitations-forward. Structure: 5-line pitch → decision-support disclaimer → "What it does (and what the evidence says)" → validated result + the dial → "Using it" → scripts table → data sources → "Limitations (read before trusting a number)". The limitations section is load-bearing, not boilerplate. |
| `DEPLOY.md` | The operational walkthrough: phone dashboard, the Render-serves / GitHub-Actions-builds split (and WHY: the 512MB OOM incident), secrets setup, day-to-day operation | Goal-first ("open the dashboard on your phone… with your laptop off"), explains the architecture with an ASCII diagram before the steps, numbered one-time setup, then day-to-day. |
| `config.yaml` comments | The tunable-rationale record: why each threshold has its value, which evidence set it (e.g. `max_anchors: 15  # concentration sweet spot from the out-of-sample sweep`), the PyYAML `1.5e+9` signed-exponent trap, the BAA10Y substitution | Every threshold auditable; comments cite the evidence or the trap, never restate the key name. |
| Module docstrings (`src/allocator/**/*.py`) | The surviving M1–M9 spec: what each module is FOR, the design decision, the incident behind it (ARKK → regime gate in `regime.py`; OKLO round-trip → pre-committed exits in `exits.py`; TTWO slip → catalyst de-rate in `exits.py`) | See house style below. This is the project's architecture doc — treat edits to them as spec edits. |
| Script headers (`scripts/*.py`) | The runnable contract: exact run command, flags, and the one warning that matters (e.g. `weekly_run.py`: "DEFAULT IS RS-ONLY — ERM failed the backtest ablation: it cut CAGR 34%->16%") | Command first, flags enumerated, incidents inline. |
| `.claude/skills/` | This library — the deep operational knowledge, history, and runbooks | One home per fact across skills too: deep story in ONE skill, siblings link with a one-line summary. |

**One home per fact.** A fact lives in exactly one document; everything else points at it.
When two documents state the same fact independently, they drift. Live example found while
verifying this skill (2026-07-11): the `prices.py` module docstring says "stooq EOD primary,
yfinance secondary", but the code it heads (`history()`, `src/allocator/data/prices.py:112`)
says "Source order: FMP (if key) -> stooq -> yfinance", and README.md calls yfinance "the
primary source" (it is — via the bulk `prefetch()` path that fills the cache). Three
statements, one fact, two of them stale or partial. When you touch price-source behaviour,
fix all three; when you document a NEW fact, pick one home.

### Update matrix — "X changed, what do I touch?"

| Event | Update |
|---|---|
| An investigation settles (root cause found, fix merged) | allocator-failure-archaeology (the chronicle is its home); a one-line WHY comment at the fix site; nothing else re-tells the story |
| A new config key or script flag | `config.yaml` comment (rationale + evidence) AND allocator-config-and-flags; script header if it's a flag |
| Backtest results change (new sweep, new default, window moved) | README.md numbers + caveats; `config.yaml` comments that cite old numbers (e.g. the `live.use_regime_gate` comment cites −15.7%/−20.7% DD); golden expectations in allocator-validation-and-qa; the honesty banner text in `backtest.py` if its factual content changed |
| A design decision changes (module contract, signal added/cut) | The module docstring (it IS the spec record) + allocator-architecture-contract; route the change itself through allocator-change-control first |
| Deployment/ops change | DEPLOY.md; allocator-run-and-operate |
| Anything external-facing | Section 3 (claims discipline) + Section 4 (reproducibility standard) below |

---

## 2. House style — derived from the actual documents

These conventions are extracted from README.md, DEPLOY.md, and the docstrings as they exist
(all quotes verified 2026-07-11). Match them; don't import generic docs style.

**S1. Limitations before trust.** The README's limitations heading is literally
"Limitations (read before trusting a number)" and the disclaimer ("Decision-support only —
not financial advice and not an autotrader") appears in line 7, before any result. New
user-facing docs follow the same order: what it is → what it is NOT → then numbers.

**S2. Numbers always travel with their caveat.** The README never states "+34% CAGR"
without the survivorship upper-bound context and the vs-benchmark comparison ("~+34% CAGR
vs S&P +14.5%, with −16% max drawdown vs the market's −25%"). Bare performance numbers are
a style violation and an R4 violation. Numbers come from `backtest.metrics` output only —
never eyeballed, never from memory.

**S3. Plain-English evidence framing.** The README's core section is titled "What it does
(and what the evidence says)" — every capability sentence is paired with its evidential
status, including negative results stated proudly: "ERM … was tested and **cut** — it hurt
returns out-of-sample". Negative results are features of the writing, not embarrassments to
bury.

**S4. Docstrings state WHY and cite the incident.** The pattern (see `regime.py`,
`exits.py`, `backtest.py`):
- First line: milestone tag + role in one clause ("M2 — Regime gate (the master switch…)").
- Then the design rationale with the named incident: "This is the lesson from the ARKK
  study: one −67% year erases three good ones" (regime.py); "Pre-commit the exit BEFORE
  entry so winners don't round-trip (the OKLO +250% -> flat lesson)" (exits.py).
- Then the contract: inputs, outputs, invariants (point-in-time rules stated explicitly).
- Honest weakness stated in place: "coverage is partial pre-2023 → RS-only is the
  fully-clean baseline" (backtest.py).

**S5. Comments record history, not narrate code.** Good (sizer.py:85–88): "regime gate but
NO satellites found (RS-only) -> fold the idle satellite budget into anchors instead of
leaving it in cash (this was a real ~40% cash-drag bug)". Good (prices.py prefetch):
explains that delete-then-fetch once wiped the cache under a rate limit. Bad: "# loop over
tickers". A comment must tell a future reader something the code cannot.

**S6. Decision-support disclaimer on anything user-facing.** It appears in the package
docstring (`__init__.py`), the sizer's output notes (sizer.py:141), the HTML report banner
(report.py:288: "Decision-support, not advice — it proposes, you place manually…"), and the
README. Any NEW user-facing surface (page, export, message, email) carries it. Non-negotiable
R2: no broker integration, no auto-orders, ever.

### Template: module docstring

```python
"""M<k> — <Role in one clause> (<what problem it kills>).

<Design decision and WHY, citing the incident or evidence that forced it — restate the
lesson, never point at "spec §X"; the spec doc is not in the repo.>

<Contract: inputs -> outputs. Point-in-time rule if any computation is dated: "at date t,
uses only data timestamped <= t".>

<Honest weakness, stated plainly: what this module does NOT handle, and where the caveat
is surfaced (banner / rationale field / notes list).>
"""
```

### Template: README results paragraph

```markdown
**Out-of-sample validated result (<signal>, <concentration>, <gate state>):** ~**<X% CAGR>**
vs S&P **<Y%>**, with **<−Z% max drawdown>** vs the market's <−W%>.
<One sentence naming the biggest caveat that applies to this number — survivorship upper
bound at minimum — or linking to the Limitations section.>
```

Both templates are distilled from the current README results block (README.md lines 25–27)
and the `backtest.py` / `regime.py` / `exits.py` docstrings.

---

## 3. Claims discipline — external positioning

Everything below is "as of 2026-07-11". Claims have expiry dates; re-verify numbers against
a fresh `run_backtest.py` output before publishing (Section 4).

### What the project MAY claim today

- **The exact validated claim:** a walk-forward, cost-modelled (8 bps/side), regime-gated
  momentum backtest on ~500 current large-caps (S&P 500 membership + a small delisted
  overlay) beat buy-and-hold out-of-sample — ~+34% CAGR vs +14.5%, −16% max DD vs −25%, on
  the untouched 2024-01-01..2026-06-01 validate window — **with the survivorship
  upper-bound caveat stated in the same breath**. The caveat is part of the claim, not a
  footnote.
- Gate-off variant: +41% CAGR / −21% DD, same caveat.
- **The honesty protocol itself**: ablation-gated defaults (a spec-anchored signal, ERM,
  was cut when the evidence said so), quarantined validate window, banner on every backtest,
  limitations-first docs.
- **Free-data reproducibility**: FRED + yfinance + stooq + Wikipedia; FMP/Finnhub optional.
  Anyone with free keys can re-run the whole pipeline.

### What the project may NOT claim

| Forbidden claim | Why not | What would license it |
|---|---|---|
| "Alpha net of survivorship" / "beats the market" unqualified | Universe = *current* S&P 500 + a 5-name delisted overlay (`data/delisted.csv`), not true point-in-time membership; every result is an upper bound (README Limitation 1, honesty banner) | True point-in-time universe → run the **survivorship-bias-campaign** skill; only its promoted result upgrades the claim |
| Live / real-money performance | None accumulated publicly. The system proposes; R places manually; there is no published live track record | ≥ ~1 year of live books tracked against the backtest (weekly `alloc_<date>.json` history exists for this; see allocator-research-frontier, live-vs-backtest tracking) |
| Novelty of momentum or regime gating | Both are well-documented factors in the quant literature, not inventions of this project (background in quant-domain-reference). The implementation discipline is the contribution, not the factor | Nothing — do not make this claim; position the honesty protocol and PIT engineering instead |
| "ERM (analyst revisions) adds value" | Tested and it **hurt**: the walk-forward ablation showed ERM cut out-of-sample CAGR 34%→16% (grade-action proxy, thin pre-2023 coverage). It is opt-in (`ermrs`), not default | A clean re-test on ~1 year of self-banked weekly estimate snapshots (`data/snapshots/`), passed through change control |
| Turn-calling / crash prediction | Own evidence against it: catch-rate on each year's top-10 movers is 0–20%. Honest framing: "it rides trends and dodges crashes, it doesn't call turns" (README Limitation 2) | Nothing foreseeable — keep the honest framing |

### What is genuinely differentiating (positioning that IS supported)

1. **The honesty protocol as a feature.** Most hobby backtests hide their biases; this one
   prints them (`caveat_banner`), leads metrics with median + max drawdown, quarantines the
   validate window (R1), and cut its own spec-anchored signal on evidence (R3). Sell the
   discipline.
2. **Free-data reproducibility.** Full pipeline on free sources; total setup cost is two
   free API keys.
3. **The self-banked point-in-time estimate dataset.** The weekly snapshot job
   (`weekly.take_snapshot()` → `data/snapshots/estimates_<date>.csv`) is building a true
   point-in-time estimate-revision series that cannot be bought free anywhere — a growing
   asset, honestly labelled "cleaner test in ~a year" (README Limitation 3).

### The proof ladder — stronger claim ⇒ named prerequisite

Never step up a rung early; each promotion goes through allocator-change-control.

```
today:  "upper-bound backtest beats buy-and-hold OOS, caveats stated"
  └─ true PIT universe (survivorship-bias-campaign)      → "backtest beats buy-and-hold, survivorship-controlled"
       └─ ~1yr live books vs backtest tracking           → "live results consistent with backtest"
            └─ ERM re-test on banked snapshots (positive)→ "revision signal adds value"  (may also stay retired)
```

---

## 4. Reproducibility standard — anything shared externally

If a number leaves this repo (post, message, slide), the following must accompany it, so a
stranger can reproduce or refute it:

1. **Pin the config.** State the commit (or paste the relevant `config.yaml` block —
   `caps`/`cuts`/`live.use_regime_gate`/`costs_bps`/`backtest` at minimum). The dial matters:
   Safe vs Returns is ±7 points of CAGR.
2. **State the window.** Full window 2020-01-01..2026-06-01, monthly rebalance; and which
   window the headline number comes from — the untouched validate window
   2024-01-01..2026-06-01 for any "out-of-sample" wording. Never quote a tune-window number
   as out-of-sample.
3. **Publish the commands.** PowerShell (R's dev box; `PYTHONUTF8=1` needed on Windows) and
   Linux/CI forms. All three need network; backtest/sweep need `.env` keys (FRED at minimum,
   FMP optional) — they cannot run keyless.

   ```powershell
   $env:PYTHONUTF8=1
   .venv\Scripts\python.exe scripts\fetch_universe.py     # constituents + bulk price cache
   .venv\Scripts\python.exe scripts\run_backtest.py rs    # walk-forward + ablations + banner
   .venv\Scripts\python.exe scripts\sweep.py              # concentration x gate, tune vs validate
   ```
   ```bash
   python scripts/fetch_universe.py
   python scripts/run_backtest.py rs
   python scripts/sweep.py
   ```
4. **Include the honesty banner verbatim.** `run_backtest.py` prints it
   (`backtest.caveat_banner`, src/allocator/backtest.py:250); its factual content, quoted
   from source as of 2026-07-11:

   > HONESTY BANNER (spec §6/§7):
   > * Universe = seed + delisted overlay, NOT true point-in-time membership →
   >   SURVIVORSHIP BIAS remains; treat returns as an UPPER BOUND.
   > * RS is point-in-time clean (prices). ERM uses dated grade actions (point-in-time)
   >   but coverage is partial pre-2023 → RS-only is the fully-clean baseline.
   > * Costs modelled; cash sleeve earns 0% (conservative). Not financial advice.

   Paste the banner your run actually printed, not this copy.
5. **Numbers from `backtest.metrics` only** — copy from the run output. No hand-adjusted,
   remembered, or blended figures (R4).

---

## When NOT to use this skill

- **Writing or editing skills in `.claude/skills/`** — follow the library's own authoring
  conventions (frontmatter, provenance sections, one-home-per-fact across skills), not the
  README/docstring house style in Section 2.
- **Deciding validation thresholds, golden expectations, or what counts as evidence** →
  allocator-validation-and-qa.
- **Making the change that the docs will describe** — classification and gating live in
  allocator-change-control; this skill only covers writing it up and talking about it.
- **The deep story behind an incident you're citing** → allocator-failure-archaeology
  (cite one line here, link there).

---

## Provenance and maintenance

All quotes, paths, line numbers, and numbers verified against the repo on 2026-07-11
(branch claude/skill-library-handoff-vm2gku). Re-verify before relying on drift-prone items:

| Fact | Re-verify with |
|---|---|
| README structure, numbers, limitations wording | `sed -n '1,75p' README.md` |
| Honesty banner text | `grep -n -A 10 "def caveat_banner" src/allocator/backtest.py` |
| Report disclaimer banner | `grep -n "Decision-support, not advice" src/allocator/report.py` |
| Price source order vs docstring drift | `grep -n "Source order\|primary" src/allocator/data/prices.py README.md` |
| Cash-drag fix comment | `sed -n '85,98p' src/allocator/sizer.py` |
| Backtest windows / costs / dial | `grep -n -B1 -A3 "tune_window\|use_regime_gate\|costs_bps" config.yaml` |
| ERM-cut warning + weekly flags | `head -13 scripts/weekly_run.py` |
| Snapshot banking (dataset claim) | `grep -n "snapshots" src/allocator/weekly.py src/allocator/data/estimates.py` |
| Delisted overlay size (currently 5 names) | `wc -l data/delisted.csv` |
| Headline numbers before ANY external use | re-run `scripts/run_backtest.py rs` (requires `.env` keys) and quote its output |

If any re-verification disagrees with this skill, the repo wins — update this file and check
whether README / config comments / docstrings drifted too (Section 1, one home per fact).
