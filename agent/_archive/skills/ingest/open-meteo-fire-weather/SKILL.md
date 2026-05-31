---
name: open-meteo-fire-weather
description: Ingestion. Queries Open-Meteo daily forecasts for fire-prone region centroids and emits fire_weather signals where a composite dryness/wind score exceeds threshold.
version: 0.1.0
author: Envision
license: MIT
required_environment_variables:
  - DATABASE_URL
---

## When to Use

Run every 3 hours to ingest forecast fire-weather index signals for ~100
fire-prone regions worldwide. Complements FIRMS hotspots and NWS alerts.

## Quick Reference

- Region list: `fire_regions.json` (static centroids)
- Score threshold: >= 3 of 4 boolean factors (temp, RH, wind, precip)
- Source: `open_meteo`, signal_type: `fire_weather`
- No API key required (Open-Meteo free tier)

## Procedure

1. Confirm `DATABASE_URL` is set in `~/.hermes/.env`.
2. Run: `python ${HERMES_SKILL_DIR}/scripts/ingest_open_meteo.py`
3. Report how many fire_weather signals were inserted.

## Pitfalls

- Northern-hemisphere fire season (May–October) yields more signals than winter.
- RH minimum is derived from hourly data (not available as daily aggregate).
- Attribution: CC BY 4.0 — see https://open-meteo.com/

## Verification

- stdout shows inserted count.
- `SELECT count(*) FROM signals WHERE source='open_meteo';` after refresh.
