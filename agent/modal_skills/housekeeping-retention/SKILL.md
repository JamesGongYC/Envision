---
name: housekeeping-retention
description: Modal-only. Deletes aged signals (30d) and forecasts (60d), then refreshes signal_catalog. Runs daily at 06:00 UTC.
---

# housekeeping-retention (Modal)

Housekeeping skill — not gated by `ENVISION_CURATOR_ENABLED`.

## Retention windows

| Table | Retention |
|-------|-----------|
| `signals` | 30 days (`ingested_at`) |
| `forecasts` | 60 days (`issued_at`) |
| `ground_truth`, `evaluations`, `skill_edit_proposals` | indefinite |

Also runs `REFRESH MATERIALIZED VIEW CONCURRENTLY signal_catalog`.

## Schedule

**06:00 UTC** daily (`modal.Cron("0 6 * * *")`).

## Deploy

```bash
python -m modal run agent/modal_skills/housekeeping-retention/app.py
python -m modal deploy agent/modal_skills/housekeeping-retention/app.py
```
