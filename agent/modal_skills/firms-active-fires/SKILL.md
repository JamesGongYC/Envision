---
name: firms-active-fires
description: Modal-only. FIRMS VIIRS+MODIS 6-bbox global ingest. Every 30 minutes. Requires FIRMS_MAP_KEY.
---

# firms-active-fires (Modal)

`FIRMS_MAP_KEY` on `envision-neon` secret. 6 continental bboxes, 8000 row cap per bbox/source.

## Schedule

`modal.Cron("*/30 * * * *")` with `cpu=2.0`, `memory=2048`.

## Deploy

```bash
python -m modal run agent/modal_skills/firms-active-fires/app.py
python -m modal deploy agent/modal_skills/firms-active-fires/app.py
```
