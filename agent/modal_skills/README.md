# Modal-native skills

All Envision skills run on [Modal](https://modal.com/) as of v2.5. The retired Hermes tree lives in [`agent/_archive/skills/`](../_archive/skills/).

Shared helpers:

- [`_shared/`](_shared/) — AIFS GRIB helpers (`aifs_common.py`, `grid.py`, `image.py`)
- [`../lib/`](../lib/) — `trace_builder.py`, `reasoning_llm.py`, `reasoning_prompts.py` (mounted at `/root/agent_lib` on detection images)

Detection apps fill LLM prompts from **trace `inputs` / `intermediate`** after `TraceBuilder` is populated — see [`reasoning_prompts.py`](../lib/reasoning_prompts.py). `generate_reasoning()` in [`reasoning_llm.py`](../lib/reasoning_llm.py) calls Sonnet (`max_tokens=200`) and falls back to templated `build_reasoning()` on any failure.

## Prerequisites

1. Modal CLI: `pip install modal` then `python -m modal setup`
2. Secret (recreate replaces entirely — include every field):

```bash
python -m modal secret create envision-neon \
  DATABASE_URL='<neon-url>' \
  ANTHROPIC_API_KEY='<key>' \
  ENVISION_CURATOR_ENABLED=true \
  NWS_USER_AGENT='envision-monitor (you@example.com)' \
  FIRMS_MAP_KEY='<firms-map-key>'
```

Optional: `JTWC_USER_AGENT` (browser-like string) if JTWC returns 403 from Modal.

## Deployed apps (v2.5)

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
| `forecast-evaluator` | 07:00 daily | Match expired forecasts to ground truth |
| `open-meteo-fire-weather` | every 3h | Open-Meteo fire weather index → `signals` |
| `nhc-cyclones` | every 3h | NHC CurrentStorms.json → `cyclone_advisory` |
| `jtwc-cyclones` | every 6h | JTWC ATCF WP cyclones → `cyclone_advisory` |
| `nws-fire-alerts` | every 30m | NWS fire-weather alerts → `fire_warning` |
| `firms-active-fires` | every 30m | FIRMS VIIRS+MODIS 6-bbox global → `hotspot` |
| `wildfire-rapid-growth` | every 30m | Grid growth detection → `forecasts` |
| `wildfire-risk-elevated` | every 30m | DBSCAN + NWS/ECMWF/AIFS polygons → `forecasts` |
| `typhoon-intensifying` | every 3h | NHC pressure trend → `forecasts` |
| `typhoon-landfall-imminent` | every 3h | Cone vs populated places → `forecasts` |

\* **Modal cron limit:** upgrade workspace plan before deploying all scheduled apps (~17+ crons with full v2.5 stack).

## Commands

```bash
# One-off smoke (PYTHONUTF8=1 on Windows)
python -m modal run agent/modal_skills/wildfire-rapid-growth/app.py
python -m modal run agent/modal_skills/wildfire-risk-elevated/app.py
python -m modal run agent/modal_skills/typhoon-intensifying/app.py
python -m modal run agent/modal_skills/typhoon-landfall-imminent/app.py
python -m modal run agent/modal_skills/open-meteo-fire-weather/app.py
python -m modal run agent/modal_skills/firms-active-fires/app.py
# ... plus housekeeping, gdacs, evaluator, curator, AIFS/ECMWF apps

# Production deploy (after plan upgrade if needed)
python -m modal deploy agent/modal_skills/wildfire-rapid-growth/app.py
python -m modal deploy agent/modal_skills/wildfire-risk-elevated/app.py
python -m modal deploy agent/modal_skills/typhoon-intensifying/app.py
python -m modal deploy agent/modal_skills/typhoon-landfall-imminent/app.py
# ... all apps above

python -m modal app logs wildfire-rapid-growth
```

Disable a single AIFS signal type: `modal app stop <name>` without affecting others.

## Hermes retirement (v2.5 Day 3)

- Repo: `agent/skills` → `agent/_archive/skills`; `tools/sync_skills.py` → `tools/_archive/sync_skills.py`
- Operator: archive `~/.hermes/skills` if desired; keep `~/.hermes/.env`
- Verify: `python -c "import sys; sys.argv=['hermes','cron','list']; from hermes_cli.main import main; main()"` → **empty**
