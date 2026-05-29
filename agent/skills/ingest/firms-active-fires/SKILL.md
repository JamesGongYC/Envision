---
name: firms-active-fires
description: Ingestion. Fetches NASA FIRMS near-real-time active fire hotspots (MODIS/VIIRS) for a bounding box and writes each as a point Signal in the Postgres `signals` table.
version: 0.1.0
author: Envision
license: MIT
required_environment_variables:
  - DATABASE_URL
  - FIRMS_MAP_KEY
---

## When to Use

Run on the wildfire ingestion cadence (every ~30 min) to pull the latest active
fire detections into `signals`. Downstream wildfire detection skills cluster
these hotspots.

## Quick Reference

No arguments. Reads config from environment:
- `FIRMS_SOURCE` (default `VIIRS_NOAA20_NRT`)
- `FIRMS_AREA` (default western US bbox `-125,31,-103,49`; `world` for global)
- `FIRMS_DAYS` (default `1`)
- `FIRMS_MAX_ROWS` (default `2000`, a safety cap)

## Procedure

1. Confirm `DATABASE_URL` and `FIRMS_MAP_KEY` are set in `~/.hermes/.env`.
2. Run: `python ${HERMES_SKILL_DIR}/scripts/ingest_firms.py`
3. Report how many hotspots were inserted.

## Pitfalls

- `FIRMS_AREA=world` for VIIRS can return tens of thousands of rows per day —
  the `FIRMS_MAX_ROWS` cap protects the free-tier database; raise it deliberately.
- The MAP_KEY limit is 5000 transactions per 10 minutes; a multi-day request
  counts as several transactions.
- Re-runs re-insert overlapping hotspots (no dedup yet) — see README for the
  planned unique-index + retention hardening.
- Geometry is forced to 2D on insert to match the column type.

## Verification

- stdout shows `Inserted N FIRMS hotspots`.
- `SELECT count(*) FROM signals WHERE source LIKE 'firms_%';` returns > 0.
