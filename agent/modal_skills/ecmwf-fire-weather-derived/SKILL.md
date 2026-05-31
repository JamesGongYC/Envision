---
name: ecmwf-fire-weather-derived
description: Modal-only. Downloads ECMWF HRES Open Data GRIB (+24h), computes a 0–4 fire weather index per grid cell, aggregates contiguous high-score cells into polygons, and writes fire_weather_grid signals.
version: 0.1.0
---

# ecmwf-fire-weather-derived

**Modal-native** — not synced by `tools/sync_skills.py`.

## Score (per 0.25° cell)

Sum of four booleans (threshold default **3** via `ECMWF_FW_THRESHOLD`):

- 2m temperature > 30°C
- Dewpoint depression (2t − 2d) > 15°C
- 10m wind > 6.9 m/s (25 km/h)
- 24h precipitation < 1 mm

## Signal shape

- `source`: `ecmwf_open_data`
- `signal_type`: `fire_weather_grid`
- `timestamp`: forecast **valid time** (run + 24h)
- `geometry`: polygon(s) from contiguous high-score cells

## Cadence

Modal cron **04:00 and 16:00 UTC** (4h after 00/12 HRES cycles).

## Run

```bash
python -m modal run agent/modal_skills/ecmwf-fire-weather-derived/app.py
python -m modal deploy agent/modal_skills/ecmwf-fire-weather-derived/app.py
```

Requires Modal secret `envision-neon` with `DATABASE_URL`.
