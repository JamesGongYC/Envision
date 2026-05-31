---
name: nws-fire-alerts
description: Ingestion. Pulls active NWS fire-weather alerts (Red Flag Warning, Fire Weather Watch, Fire Warning), resolves their geometry, and writes each as a Signal in the Postgres `signals` table.
version: 0.1.0
author: Envision
license: MIT
required_environment_variables:
  - DATABASE_URL
---

## When to Use

Run on the wildfire ingestion cadence (every ~30 min) alongside FIRMS. These
alert polygons are what the `wildfire_risk_elevated` detection skill intersects
fire-hotspot clusters against.

## Quick Reference

No arguments. Optional environment:
- `NWS_EVENTS` (comma list; default `Fire Weather Watch,Red Flag Warning,Fire Warning`)
- `NWS_USER_AGENT` (set this to your app name + a contact email — the NWS API
  requires a User-Agent and uses it to reach you about heavy usage)

## Procedure

1. Confirm `DATABASE_URL` is set in `~/.hermes/.env`. Set `NWS_USER_AGENT` too.
2. Run: `python ${HERMES_SKILL_DIR}/scripts/ingest_nws.py`
3. Report how many signals were inserted.

## Pitfalls

- Many alerts have `geometry: null` and only list `affectedZones`; this skill
  resolves those zone polygons and emits one signal per zone, so a single alert
  can produce several rows. That's expected.
- Fire-weather alerts are seasonal and regional — an empty result is normal
  outside active fire weather, not a bug.
- Re-runs re-insert overlapping alerts (no dedup yet) — hardened later with FIRMS.
- Geometry is forced to 2D on insert to match the column type.

## Verification

- stdout shows `Inserted N NWS fire-weather signals` (or a clear empty-result note).
- `SELECT count(*) FROM signals WHERE source = 'nws_alerts';` returns >= 0.
