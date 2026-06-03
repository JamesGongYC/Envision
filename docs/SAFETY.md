# Envision — Safety controls

## Kill switch — evolution only

The Curator evolution pass MUST check `ENVISION_CURATOR_ENABLED` before mutating.

| State | `ENVISION_CURATOR_ENABLED` value |
|---|---|
| Evolution runs normally (default) | `true`, `1`, unset, or absent |
| Evolution halted | `false`, `0`, `no`, `off` |

The kill switch does **not** stop:
- Existing pending/shadow proposals from being reviewed
- Production detection skills from running
- Shadow runner / evaluator (already-deployed candidates continue until promoted/discarded)
- Ingestion skills from running
- The public viewer

To halt evolution:

**Modal:**

```sh
python -m modal secret create envision-neon \
  DATABASE_URL='...' \
  ANTHROPIC_API_KEY='...' \
  ENVISION_CURATOR_ENABLED=false
```

Verify: `python tools/check_status.py`

## v3 evolution gates

| Gate | What it blocks |
|---|---|
| AST + sandbox validation | Non-executable or persistence-laden mutants |
| No-persistence check | Candidates that write forecasts/signals in skill code |
| Cross-window selection | Candidates that beat parent in only some backtest windows |
| Thin ground truth | Selector refuses when <3 scorable windows |
| Shadow observation | Promotion eligibility requires ≥20 shadow evaluations |
| Noise floor (0.03) | Shadow Brier must beat parent live 14d Brier by ≥0.03 |
| Operator `promote` | No automatic path to production `run.py` |
| Manual `modal deploy` | Even after promote, operator must deploy |

**Tiered auto-approve** (auto-promote parametric edits below a threshold) is **explicitly deferred** — all production promotion is human-gated in v3.0.

## Per-skill disable

Stop a single Modal detection app via the Modal dashboard (`modal app stop <name>`) or pause its cron schedule.

## Probability cap

A CHECK constraint on `forecasts.probability` enforces `<= 0.85`.

## Approval queue

Mutator proposals land in `skill_edit_proposals` with linked `skill_lineage` rows. None auto-promote. `tools/review_proposals.py promote` is the only sanctioned path to production code; it writes `run.py` but does not deploy.

## Brier signal

The evaluator scores live `forecasts` and shadow `forecasts_shadow` separately. Mean Brier per skill drives worst-K targeting; shadow Brier drives promotion eligibility.
