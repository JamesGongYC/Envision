---
name: firms-active-fires
description: Ingestion. Fetches NASA FIRMS near-real-time active fire hotspots (MODIS/VIIRS) globally via six continental bounding boxes and writes each as a point Signal in the Postgres `signals` table.
version: 0.2.0
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
- `FIRMS_DAYS` (default `1`)
- `FIRMS_MAX_ROWS` (default `8000` per bbox/source API call)
- `FIRMS_AREA` / `FIRMS_SOURCE` (optional debug overrides for a single bbox/source)

Production path queries **6 continental bboxes × 2 sources** (VIIRS + MODIS):
North America, South America, Europe, Africa, Asia, Oceania. Overlap at
region boundaries is handled by the dedup trigger (migration 002).

## Procedure

1. Confirm `DATABASE_URL` and `FIRMS_MAP_KEY` are set in `~/.hermes/.env`.
2. Run: `python ${HERMES_SKILL_DIR}/scripts/ingest_firms.py`
3. Report how many hotspots were inserted.

## Pitfalls

- Global volume is much higher than the old US-only bbox. Monitor Neon storage;
  retention runs daily via `housekeeping-retention`.
- Per-bbox failures (timeout, rate limit) are logged and skipped; the run
  succeeds if at least one bbox/source query succeeds.
- The MAP_KEY limit is ~5000 transactions per 10 minutes; 12 requests per
  30-min cycle is well within budget.
- Geometry is forced to 2D on insert to match the column type.

## Verification

- stdout shows per-region fetch counts and total inserted.
- `SELECT count(*) FROM signals WHERE source LIKE 'firms_%';` returns > 0.
- Global runs should insert substantially more rows than the old western-US bbox.
