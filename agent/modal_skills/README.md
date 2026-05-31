# Modal-native skills

Skills in this directory run on [Modal](https://modal.com/) — not via Hermes and **not** synced by [`tools/sync_skills.py`](../../tools/sync_skills.py).

Hermes skills live under `agent/skills/` and deploy to `~/.hermes/skills/`. Modal skills deploy with `modal deploy`.

Shared helpers for AIFS skills live in [`_shared/`](_shared/) (`aifs_common.py`, `grid.py`, `image.py`).

## Prerequisites

1. Modal CLI: `pip install modal` then `python -m modal setup`
2. Secret (once):

```bash
python -m modal secret create envision-neon \
  DATABASE_URL='<neon-url>' \
  ANTHROPIC_API_KEY='<key>' \
  ENVISION_CURATOR_ENABLED=true
```

## Deployed apps

| App | Schedule (UTC) | Purpose |
|---|---|---|
| `ecmwf-fire-weather-derived` | 04:00, 16:00 | ECMWF HRES GRIB → fire weather grid polygons |
| `curator` | 04:00 daily | Brier-driven skill edit proposals |
| `aifs-cyclone-feature` | 05:00, 17:00 | AIFS MSLP + 850hPa vorticity → cyclone_feature points |
| `aifs-fire-weather-grid` | 05:10, 17:10 | AIFS +24h → fire_weather_grid polygons |
| `aifs-high-wind-corridor` | 05:15, 17:15 | AIFS +24h wind → high_wind_corridor polygons |
| `aifs-heavy-precipitation-band` | manual* | AIFS +24h tp → heavy_precipitation_band polygons |
| `aifs-heat-dome` | manual* | AIFS multi-horizon 2t → heat_dome polygons |
| `housekeeping-retention` | 06:00 daily | Delete aged signals/forecasts; refresh `signal_catalog` |
| `gdacs-ground-truth` | every 6h | GDACS GeoRSS → `ground_truth` |
| `forecast-evaluator` | 07:00 daily | Match expired forecasts to ground truth; write `evaluations` |

\* **Modal cron limit:** starter workspace allows **5** scheduled crons. v2.5 Day 1 adds three scheduled apps (8 total with ECMWF + curator + 3 AIFS). Upgrade the workspace plan, then deploy the Day 1 apps (and optionally enable schedules on `heavy-precipitation-band` / `heat-dome`).

## Commands

```bash
# One-off smoke (set PYTHONUTF8=1 on Windows if console encoding errors)
python -m modal run agent/modal_skills/housekeeping-retention/app.py
python -m modal run agent/modal_skills/gdacs-ground-truth/app.py
python -m modal run agent/modal_skills/forecast-evaluator/app.py
python -m modal run agent/modal_skills/aifs-cyclone-feature/app.py
python -m modal run agent/modal_skills/aifs-fire-weather-grid/app.py
python -m modal run agent/modal_skills/aifs-high-wind-corridor/app.py
python -m modal run agent/modal_skills/aifs-heavy-precipitation-band/app.py
python -m modal run agent/modal_skills/aifs-heat-dome/app.py
python -m modal run agent/modal_skills/ecmwf-fire-weather-derived/app.py
python -m modal run agent/modal_skills/curator/app.py

# Production deploy (after plan upgrade for new scheduled apps)
python -m modal deploy agent/modal_skills/housekeeping-retention/app.py
python -m modal deploy agent/modal_skills/gdacs-ground-truth/app.py
python -m modal deploy agent/modal_skills/forecast-evaluator/app.py
python -m modal deploy agent/modal_skills/aifs-cyclone-feature/app.py
python -m modal deploy agent/modal_skills/aifs-fire-weather-grid/app.py
python -m modal deploy agent/modal_skills/aifs-high-wind-corridor/app.py
python -m modal deploy agent/modal_skills/aifs-heavy-precipitation-band/app.py
python -m modal deploy agent/modal_skills/aifs-heat-dome/app.py
python -m modal deploy agent/modal_skills/ecmwf-fire-weather-derived/app.py
python -m modal deploy agent/modal_skills/curator/app.py

# Logs
python -m modal app logs housekeeping-retention
```

Disable a single AIFS signal type: stop that Modal app (`modal app stop <name>`) without affecting the others.

## v2.5 note

Remaining Hermes ingestion/detection skills migrate in v2.5 Days 2–3. Hermes skill tree is archived on Day 3 after all migrations land.
