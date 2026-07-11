---
name: allocator-research-methodology
description: >
  The discipline that turns a hunch into an accepted result in the Asymmetric Allocator:
  the evidence bar (one mechanism must explain ALL observations including negatives, and
  survive an assigned adversarial-refutation pass), hypothesis-predicts-numbers-before-
  running, the idea lifecycle from experiment flag to adopted default or documented
  retirement (with ERM as the complete worked lifecycle), multiple-comparisons and
  validate-window budgeting, and the research-log template. Load when: starting ANY
  research idea ("what if we…", "I think X would improve returns"), interpreting a
  surprising backtest result, reviewing someone else's finding, deciding whether an idea is
  dead or dormant, or writing up an investigation.
---

# Allocator Research Methodology

When NOT to use: the specific open problems → `allocator-research-frontier`; the analysis
recipes (ablation/sweep/PIT-audit mechanics) → `allocator-proof-and-analysis-toolkit`; the
merge gate → `allocator-change-control`.

## 1. The evidence bar

Three tests, all mandatory:

**(a) Predict numbers BEFORE running.** Write down the hypothesis and its predicted effect
— direction AND rough magnitude — on CAGR, maxDD, and Sortino, per window, before the
experiment executes. A result whose sign you couldn't have predicted teaches nothing; it
selects noise. (The survivorship campaign models this: "honest CAGR should DROP; if it
rises, suspect your data" — `survivorship-bias-campaign`.)

**(b) One mechanism must explain ALL observations, including the negatives.** If your story
explains why the new signal helps in 2024 but not why it hurt in 2022, you don't have a
mechanism, you have a fit. Worked example: ERM's failure had a mechanism that explained
everything — grade actions LAG price (RS already owns the move), and pre-2023 coverage is
thin, so deep-history ERM percentiles rank a biased subsample. That mechanism predicted the
observed pattern (worst damage in early windows) and survived scrutiny; the cut stuck.

**(c) Survive an ASSIGNED adversarial refutation.** Before any promotion, a second session
(or a deliberately re-prompted fresh agent) gets one job: break the finding. Its checklist
for this repo:
- **Look-ahead leak** — run Recipe 3 (PIT audit, `allocator-proof-and-analysis-toolkit`)
  on every new data path. A too-good result is the #1 leak symptom.
- **Coverage artifact** — does the signal only exist for a biased subsample? (The ERM
  precedent: thin pre-2023 grade history. Check coverage counts per date, as
  `test_scoring.py` prints.)
- **Window cherry-pick** — does the effect hold on tune AND validate, and across per-year
  rows? A one-year wonder is noise.
- **Multiple comparisons** — how many variants were tried before this one "worked"? (§4.)
- **Turnover eaten** — is the gross improvement net of the 8bps × extra turnover?
- **Survivorship interaction** — does the idea profit specifically from the universe's
  known bias (e.g. buying beaten-down names that "always recover" because the dead ones
  aren't in the sample)?
If the refuter finds nothing, they must say what evidence WOULD falsify the result — and
that goes in the log.

## 2. The idea lifecycle

```
hunch
 └─ written hypothesis + predicted numbers  (research log, §5)
     └─ cheapest discriminating experiment  (TUNE window only)
         ├─ dead → log it, stop
         └─ alive → walk-forward ablation   (new Strategy variant; Recipe 1)
             └─ single validate-window look (budgeted, §4)
                 ├─ fails → DOCUMENTED RETIREMENT:
                 │    entry in allocator-failure-archaeology
                 │    (symptom/cause/evidence/status + re-test trigger if any)
                 └─ passes → adversarial refutation (§1c)
                     └─ survives → PROMOTION via allocator-change-control:
                          flag → default, README + goldens updated
```

Two invariants: **no idea dies silently** (retirement is a written artifact — that's what
makes this repo's history navigable), and **no idea ships un-ablated** (rule R3).

## 3. The worked lifecycle: ERM, end to end

1. **Hypothesis** (spec-era): analyst estimate revisions lead price; weight 0.30, the
   anchor signal.
2. **Proxy implementation**: dated grade actions from yfinance (true PIT estimates aren't
   free) — an honest, disclosed downgrade of the hypothesis.
3. **Ablation verdict**: ERM+RS vs RS-only, walk-forward: CAGR 34% → 16% out-of-sample.
4. **Retirement, documented**: default `active=("RS",)`; `ermrs` opt-in retained; comments
   in weekly_run.py/README record the number and the reason.
5. **Re-test trigger defined**: the weekly snapshot job banks TRUE PIT revision data;
   re-test after ~1 year of snapshots (frontier item F2).

The lesson to internalize: the project's most-believed signal was cut on evidence, **and
the retirement is reversible on better evidence**. That reversibility is what makes cutting
a beloved idea psychologically possible — build every retirement with a re-test trigger
where one exists.

## 4. Multiple comparisons and the validate-window budget

Every variant you evaluate against the validate window consumes it: with enough looks, the
"best" variant is guaranteed to look good by chance. House discipline:
- Iterate freely on the TUNE window (2020–2023).
- Batch your candidates and spend ONE validate look per question, via the sweep's robust
  pick (best validate Sortino among above-median tune Sortino — `scripts/sweep.py`).
- Never re-tune after seeing validate results (rule R1). If you must revisit, the honest
  statement is "the validate window is now partially spent for this question" — write it
  in the log.
- Per-year rows are your free robustness check: an effect that lives in one year is noise.

## 5. Research log template

Keep one markdown file per investigation (suggested home: a `research/` dir or the PR
description; the format matters more than the location):

```markdown
# <idea name> — research log
Date opened: <date>   Owner: <who/which session>
## Hypothesis
<one sentence: mechanism, not outcome>
## Predicted numbers (BEFORE running)
tune window: CAGR __, maxDD __, Sortino __ (direction + rough size)
validate:    __ (to be looked at ONCE, after tune iteration ends)
## Experiments
| date | variant | window | CAGR | maxDD | Sortino | note |
## Mechanism check
Does one mechanism explain every row above, including the bad ones? <write it>
## Adversarial refutation
Refuter: <session/agent> — findings: <...> — what would falsify: <...>
## Verdict
ADOPTED (change-control PR link) | RETIRED (archaeology entry A__, re-test trigger: __)
```

## 6. Where good ideas historically came from (mine these veins)

- **Post-mortems of real losses/misses**: ARKK (−67% year) → the regime gate; OKLO
  round-trip → pre-committed exits; TTWO slip → catalyst de-rating. Pain → rule, with the
  story kept in the docstring.
- **Accounting identities**: the 40% cash-drag bug was found by comparing the printed
  deploy-% against the regime budget — two numbers that had to agree and didn't. Instrument
  reality, then read the discrepancies.
- **Data constraints forcing better designs**: FMP's 250/day quota → yfinance dated grades
  → the snapshot bank (now the project's most defensible asset). When a source blocks you,
  ask what durable asset the workaround could build.
- **The honesty protocol itself**: every disclosed weakness (survivorship, exit-blind
  backtest, current-shares mktcap) is a ranked research agenda — that's literally how
  `allocator-research-frontier` was written.

## Provenance and maintenance

Written 2026-07-11. The ERM lifecycle and cash-drag stories verified against
`scripts/weekly_run.py`, `src/allocator/sizer.py`, README; the robust-pick rule against
`scripts/sweep.py`. This skill is mostly discipline, not facts — it drifts only if the
project's windows or gates change. Re-verify on touch:
- windows: `grep -n -A2 tune_window config.yaml`
- robust pick: `grep -n tune_median scripts/sweep.py`
- ERM status: `grep -n ermrs scripts/weekly_run.py`
- retirement ledger intact: `ls .claude/skills/allocator-failure-archaeology/`
