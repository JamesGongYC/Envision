---
name: open-meteo-fire-weather
description: Modal-only. Open-Meteo forecast API fire-weather scoring for 118 regions. Every 3 hours UTC.
---

# open-meteo-fire-weather (Modal)

Writes `signals` with `source=open_meteo`, `signal_type=fire_weather`.

## Env

- `DATABASE_URL` (via `envision-neon` secret)
- `fire_regions.json` bundled in this directory

## Schedule

**Every 3 hours** (`modal.Cron("0 */3 * * *")`).

## Deploy

```bash
python -m modal run agent/modal_skills/open-meteo-fire-weather/app.py
python -m modal deploy agent/modal_skills/open-meteo-fire-weather/app.py
```
