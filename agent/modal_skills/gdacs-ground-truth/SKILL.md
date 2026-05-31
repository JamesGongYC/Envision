---
name: gdacs-ground-truth
description: Modal-only. Polls GDACS GeoRSS for TC/WF events and writes ground_truth rows for the evaluator. Every 6 hours UTC.
---

# gdacs-ground-truth (Modal)

Ingests confirmed disaster events from [GDACS](https://www.gdacs.org/) GeoRSS.

## Defaults

- Event types: `TC`, `WF` (env `GDACS_EVENT_TYPES`)
- Geometry: `ST_Force2D` on insert
- 0 rows off-season is normal

## Schedule

**Every 6 hours** (`modal.Cron("0 */6 * * *")`).

## Deploy

```bash
python -m modal run agent/modal_skills/gdacs-ground-truth/app.py
python -m modal deploy agent/modal_skills/gdacs-ground-truth/app.py
```
