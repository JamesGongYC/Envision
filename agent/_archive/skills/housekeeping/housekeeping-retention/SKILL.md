---
name: housekeeping-retention
description: Deletes aged signals and forecasts on a schedule and refreshes signal_catalog. Housekeeping only — not gated by ENVISION_CURATOR_ENABLED.
---

# housekeeping-retention

Daily retention for the Neon database. Keeps the free tier lean as signal volume grows in v2.

## Retention windows

| Table | Window | Action |
|---|---|---|
| `signals` | 30 days | Delete where `ingested_at < now - 30d` |
| `forecasts` | 60 days | Delete where `issued_at < now - 60d` |
| `ground_truth` | indefinite | never deleted |
| `evaluations` | indefinite | never deleted |
| `skill_edit_proposals` | indefinite | never deleted |

After deletes, runs `REFRESH MATERIALIZED VIEW CONCURRENTLY signal_catalog`.

## Cadence

24 h. Daily.

## Kill switch

This skill is **not** affected by `ENVISION_CURATOR_ENABLED`. It performs no mutation of skill code or proposals — only row deletes on ephemeral tables.

## How to run

```sh
python scripts/run_retention.py
python scripts/run_retention.py --now 2026-05-25T00:00:00Z
```

Requires `DATABASE_URL` in env. Migration 004 must be applied (`signal_catalog` view).

## Dependencies

- `psycopg`
