---
name: curator
description: Reads 14-day Brier-score data per detection skill, asks Claude for small parameter tweaks, and writes proposals to skill_edit_proposals. Gated by ENVISION_CURATOR_ENABLED.
---

# curator

The self-evolving engine. Day 6 of Envision.

## What it does
1. Aborts immediately if `ENVISION_CURATOR_ENABLED` is set to anything truthy-negative (`false`, `0`, `no`, `off`).
2. Queries `evaluations` for the last 14 days, grouped by `skill_id`, computing mean Brier, hits, and false positives per skill.
3. For each mutable skill with at least 5 evaluations and no already-pending proposal:
   - Reads the current `detect_*.py` from `~/.hermes/skills/<skill-id>/scripts/`.
   - Calls Claude (`claude-sonnet-4-6`) with strict scope rules: only numeric constants and templated reasoning strings may change.
   - Receives a structured response via the `propose_skill_edit` tool.
   - Validates the proposed code is syntactically valid Python and isn't a literal no-op.
   - Inserts the proposal into `skill_edit_proposals` with `status='pending'`.
4. Never modifies live skill files. Promotion is manual via `tools/review_proposals.py`.

## Scope of mutation (enforced by prompt, not by sandbox)
**Allowed:** numeric constants (thresholds, time windows, buffer sizes), templated reasoning strings, base probabilities.
**Not allowed:** function signatures, control flow, imports, SQL, schema/column names. The validator only checks Python syntax; semantic safety is the operator's responsibility at review time.

## Inputs (read)
- `evaluations` joined with `forecasts`, last 14 days
- `skill_edit_proposals` (for idempotency check)
- Live skill source files on disk

## Outputs (write)
- `skill_edit_proposals` rows with `status='pending'`

## Cadence
24 h. Nightly.

## How to run
```sh
python scripts/run_curator.py
```

Requires both `DATABASE_URL` and `ANTHROPIC_API_KEY` in env.

## Dependencies
- `psycopg`, `anthropic`

## Kill switch
`ENVISION_CURATOR_ENABLED=false` in `~/.hermes/.env` halts mutation
immediately. The Curator exits with code 0 (no error). See
`docs/SAFETY.md`.

## Budget
One LLM call per eligible skill per day. With ~5 detection skills × ~5–10K context tokens × Sonnet rates, that's ~$0.10–0.25/day, or ~$1–2/week. Largest LLM line item in Envision.

## Mutable skills (hardcoded list)
- `wildfire_risk_elevated`
- `wildfire_rapid_growth`
- `typhoon_intensifying`
- `typhoon_landfall_imminent`

The evaluator and ingestion skills are intentionally excluded.

## Observation mode (cold start)
Plan §14 calls for proposals to be logged but not promoted for the first 14 days. This skill produces proposals from day 1; the "observation mode" is enforced operationally by the human refusing to approve via the CLI. Once 14 days of evaluation data accumulate, the operator can begin reviewing.

## Notes / known shortcuts (v1)
- No baseline twin (cut in Day 3 MVP). If a deployed mutation makes a skill worse, manual rollback is the only recovery.
- Brier averaging is unweighted by recency; plan §8 called for recency weighting.
- The `is_valid_python` check is syntax-only; it doesn't verify the script still produces well-formed forecasts. Review the diff before promoting.
- The LLM is not given diff context or version history; each proposal is one-shot off the current code.
