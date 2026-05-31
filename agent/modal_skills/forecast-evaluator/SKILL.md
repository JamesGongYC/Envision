---
name: forecast-evaluator
description: Modal-only. Matches expired forecasts to GDACS ground truth and writes Brier evaluations. Daily at 07:00 UTC.
---

# forecast-evaluator (Modal)

Pure DB skill — no external APIs. Preserves class aliases (`WF`/`fire` → wildfire, `TC`/`cyclone` → typhoon).

## Schedule

**07:00 UTC** daily (`modal.Cron("0 7 * * *")`) — 1h after housekeeping-retention.

## Deploy

```bash
python -m modal run agent/modal_skills/forecast-evaluator/app.py
python -m modal deploy agent/modal_skills/forecast-evaluator/app.py
```
