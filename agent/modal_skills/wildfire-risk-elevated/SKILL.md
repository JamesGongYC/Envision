---
name: wildfire-risk-elevated
description: Modal-only. FIRMS clusters intersecting NWS fire warnings OR ECMWF/AIFS fire weather grids. LLM reasoning. Every 30m UTC.
---

## Generalization (v2.5 Day 3)

Consumes `fire_warning` (NWS) and `fire_weather_grid` (ECMWF + AIFS) polygons globally.

## Deploy

```bash
python -m modal run agent/modal_skills/wildfire-risk-elevated/app.py
python -m modal deploy agent/modal_skills/wildfire-risk-elevated/app.py
```
