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

\* **Modal cron limit:** free/starter workspace allows 5 scheduled crons (currently ECMWF + curator + 3 AIFS). `heavy-precipitation-band` and `heat-dome` deploy without schedule until plan upgrade; run via `modal run` or enable `schedule=` in `app.py` after upgrading.

## Commands

```bash
# One-off smoke
python -m modal run agent/modal_skills/aifs-cyclone-feature/app.py
python -m modal run agent/modal_skills/aifs-fire-weather-grid/app.py
python -m modal run agent/modal_skills/aifs-high-wind-corridor/app.py
python -m modal run agent/modal_skills/aifs-heavy-precipitation-band/app.py
python -m modal run agent/modal_skills/aifs-heat-dome/app.py
python -m modal run agent/modal_skills/ecmwf-fire-weather-derived/app.py
python -m modal run agent/modal_skills/curator/app.py

# Production deploy
python -m modal deploy agent/modal_skills/aifs-cyclone-feature/app.py
python -m modal deploy agent/modal_skills/aifs-fire-weather-grid/app.py
python -m modal deploy agent/modal_skills/aifs-high-wind-corridor/app.py
python -m modal deploy agent/modal_skills/aifs-heavy-precipitation-band/app.py
python -m modal deploy agent/modal_skills/aifs-heat-dome/app.py
python -m modal deploy agent/modal_skills/ecmwf-fire-weather-derived/app.py
python -m modal deploy agent/modal_skills/curator/app.py

# Logs
python -m modal app logs aifs-fire-weather-grid
```

Disable a single AIFS signal type: stop that Modal app (`modal app stop <name>`) without affecting the others.

## v2.5 note

Remaining Hermes skills (FIRMS, NWS, detectors, etc.) migrate to Modal in the v2.5 sprint after v2 close.
