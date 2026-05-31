# Envision — Safety controls (Day 4)

## Kill switch — Curator mutation

The Curator (Day 6) MUST check this before proposing any skill edit.

| State | `ENVISION_CURATOR_ENABLED` value |
|---|---|
| Curator runs normally (default) | `true`, `1`, unset, or absent |
| Curator halts all mutation | `false`, `0`, `no`, `off` |

The kill switch does **not** stop:
- Existing pending proposals from being reviewed
- Detection skills from running
- Ingestion skills from running
- The evaluator from running

To halt Curator mutation right now:

**Modal (production curator since v2 Day 4):**

```sh
python -m modal secret create envision-neon \
  DATABASE_URL='...' \
  ANTHROPIC_API_KEY='...' \
  ENVISION_CURATOR_ENABLED=false
```

Include all keys — Modal replaces the entire secret.

**Legacy local env** (Hermes curator retired; kept for reference):

```sh
echo 'ENVISION_CURATOR_ENABLED=false' >> ~/.hermes/.env
```

To re-enable:

```sh
# Modal: recreate envision-neon with ENVISION_CURATOR_ENABLED=true (or omit the key)
python -m modal secret create envision-neon DATABASE_URL='...' ANTHROPIC_API_KEY='...' ENVISION_CURATOR_ENABLED=true

# Legacy local env only:
# Edit ~/.hermes/.env and set ENVISION_CURATOR_ENABLED=true (or remove the line)
```

Verify current state:

```sh
python tools/check_status.py
```

## Per-skill disable (no env var; do it via cron)

If a single skill misfires:

```sh
hermes cron list                # find the offending job ID
hermes cron remove <id>         # stop scheduling it
```

The skill files stay on disk, the table data stays untouched — only the
scheduled execution is gone. Re-add with `hermes cron add` once fixed.

## Probability cap

A CHECK constraint on `forecasts.probability` enforces `<= 0.85`. Already
in place from migration 001. No detector code can write a higher value
without raising a database error — verified Day 1.

## Approval queue

Curator-proposed edits land in `skill_edit_proposals` with `status='pending'`.
None auto-apply. The review tool (`tools/review_proposals.py`) is the only
sanctioned path to promote a proposal; it marks the row approved but does
not overwrite skill files — that step is manual on purpose.

## Probability + outcome → Brier signal

The evaluator runs nightly. Every closed-out forecast gets one
`evaluations` row whose `brier_contribution` is `(probability - outcome)²`.
Mean Brier per `skill_id` is the gradient the Curator will follow.

A skill that grows worse over time (mean Brier rising for a fixed
`skill_version`) will not be auto-corrected — that's a Day 6 concern.
For Day 4 the data just accumulates.
