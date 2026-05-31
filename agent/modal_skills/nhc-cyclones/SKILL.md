---
name: nhc-cyclones
description: Modal-only. NHC CurrentStorms.json -> cyclone_advisory point signals. Every 3 hours UTC.
---

# nhc-cyclones (Modal)

Off-season 0 rows is normal.

## Schedule

`modal.Cron("0 */3 * * *")`

## Deploy

```bash
python -m modal run agent/modal_skills/nhc-cyclones/app.py
python -m modal deploy agent/modal_skills/nhc-cyclones/app.py
```
