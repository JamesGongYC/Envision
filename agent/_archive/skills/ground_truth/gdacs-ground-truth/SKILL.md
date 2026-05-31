---
name: gdacs-ground-truth
description: Ground truth. Polls the GDACS GeoRSS feed for confirmed disaster events (tropical cyclones and wildfires by default) and writes them to the Postgres `ground_truth` table for the evaluator.
version: 0.1.0
author: Envision
license: MIT
required_environment_variables:
  - DATABASE_URL
---

## When to Use

Run on the ground-truth cadence (every ~6 h). This is the only writer to
`ground_truth`; the Day-4 evaluator matches forecasts against these events to
compute Brier scores. It does NOT write to `signals`.

## Quick Reference

No arguments. Optional environment:
- `GDACS_EVENT_TYPES` (comma list of short codes; default `TC,WF`). Codes:
  TC, WF, EQ, FL, DR, VO, TS.

## Procedure

1. Confirm `DATABASE_URL` is set in `~/.hermes/.env`.
2. Run: `python ${HERMES_SKILL_DIR}/scripts/ingest_gdacs.py`
3. Report how many ground-truth events were inserted.

## Pitfalls

- Defaults to tropical cyclones (`TC`) and wildfires (`WF`) to match Envision's
  forecast classes; widen `GDACS_EVENT_TYPES` only if you intend to.
- Coordinates in GeoRSS are lat,lon but stored as lon,lat (PostGIS order).
- Re-runs re-insert the same events (no dedup yet) — hardened later with the
  signals dedup migration.
- Geometry is forced to 2D on insert to match the column type.

## Verification

- stdout shows `Inserted N GDACS ground-truth events`.
- `SELECT disaster_class, severity, count(*) FROM ground_truth GROUP BY 1, 2;`
  returns rows.
