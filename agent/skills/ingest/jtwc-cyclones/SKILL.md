---
name: jtwc-cyclones
description: Ingestion. Fetches JTWC Western Pacific ATCF bulletins and writes cyclone_advisory signals compatible with NHC downstream detectors.
version: 0.1.0
author: Envision
license: MIT
required_environment_variables:
  - DATABASE_URL
---

## When to Use

Run every 6 hours to ingest active Western Pacific tropical cyclone advisories
from JTWC ATCF `.dat` files. Uses the same `cyclone_advisory` signal type as NHC.

## Quick Reference

- Source: `jtwc`
- Live index: https://www.metoc.navy.mil/jtwc/products/
- Fixture test: `python scripts/ingest_jtwc.py --fixture fixtures/sample_wp.dat`
- Pre-season (May-June) often returns 0 active WP storms — normal.

## Procedure

1. Confirm `DATABASE_URL` is set in `~/.hermes/.env`.
2. Run fixture test first, then live: `python scripts/ingest_jtwc.py`
3. Report how many cyclone_advisory signals were inserted.

## Pitfalls

- JTWC index page HTML may change; parser fails gracefully (log + 0 inserts).
- One signal row per storm per advisory (not per forecast point).
- Public domain US Government work.

## Verification

- Fixture run parses without error and inserts >= 1 row.
- Live run: check https://www.metoc.navy.mil/jtwc/jtwc.html for active storms.
