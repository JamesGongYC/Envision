---
name: nhc-cyclones
description: Ingestion. Reads the NHC current-storms feed (Atlantic + East Pacific) and writes one point Signal per active tropical cyclone at its current center, into the Postgres `signals` table.
version: 0.1.0
author: Envision
license: MIT
required_environment_variables:
  - DATABASE_URL
---

## When to Use

Run on the cyclone ingestion cadence (every ~3 h). Feeds the Day-3 cyclone
detection skills (`typhoon_intensifying`, `typhoon_landfall_imminent`). The full
storm record — intensity, pressure, movement, forecast track/cone URLs — is kept
in each signal's payload for those skills to use.

## Quick Reference

No arguments. Reads `https://www.nhc.noaa.gov/CurrentStorms.json`.

## Procedure

1. Confirm `DATABASE_URL` is set in `~/.hermes/.env`.
2. Run: `python ${HERMES_SKILL_DIR}/scripts/ingest_nhc.py`
3. Report how many cyclone signals were inserted and which storms are active.

## Pitfalls

- Off-season the feed legitimately lists zero active storms — that is a normal
  result, not a failure. The Atlantic season runs Jun 1–Nov 30; East Pacific
  from May 15.
- Coordinates may arrive as numbers (`latitudeNumeric`) or strings (`"20.5N"`);
  the script handles both.
- Re-runs re-insert the same storms (no dedup yet) — hardened later with FIRMS.
- Geometry is forced to 2D on insert to match the column type.

## Verification

- stdout shows either an inserted count with storm names, or a clear
  zero-active-storms note.
- `SELECT count(*) FROM signals WHERE source = 'nhc';` returns >= 0.
