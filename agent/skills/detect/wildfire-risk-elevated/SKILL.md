---
name: wildfire-risk-elevated
description: Detects clusters of FIRMS hotspots that intersect active NWS fire-weather alerts and writes a Forecast row per qualifying cluster.
---

# wildfire-risk-elevated

Detection skill — first of four for Envision Day 3.

## What it does
1. Reads FIRMS hotspots from `signals` (last 24h).
2. Reads active NWS fire-weather alerts from `signals` (last 24h, `signal_type = 'fire_warning'`).
3. Runs DBSCAN on hotspot lat/lon (haversine metric, `eps=10km`, `min_samples=5`).
4. For each non-noise cluster, buffers the convex hull and asks PostGIS which active alert polygons it intersects.
5. Writes one `forecasts` row per cluster that intersects ≥1 alert. Skips clusters with no overlap.

## Inputs (read)
- `signals` where `signal_type = 'hotspot'` and `source LIKE 'firms%'`
- `signals` where `source = 'nws_alerts'` and `signal_type = 'fire_warning'`

## Outputs (write)
- `forecasts` rows with:
  - `disaster_class = 'wildfire'`
  - `valid_from = now()`, `valid_until = now() + 24h`
  - `geometry` = buffered convex hull of the cluster (GeoJSON polygon)
  - `probability` ∈ [0.40, 0.85] from a crude additive score (capped by DB CHECK)
  - `reasoning` = templated string, no LLM call
  - `contributing_signal_ids` = the FIRMS hotspot IDs plus the intersected alert IDs
  - `skill_id = 'wildfire_risk_elevated'`, `skill_version = 1`, `is_baseline = false`

## Cadence
30 min, immediately after the FIRMS/NWS ingestion cycle.

## How to run
```sh
python scripts/detect_wildfire_risk.py
```

Requires `DATABASE_URL` in env (`~/.hermes/.env` is read by Hermes; standalone
runs need `export` first).

## Dependencies
- `psycopg`, `shapely`, `scikit-learn`, `numpy`

## Notes / known shortcuts (v1)
- Scoring is heuristic; calibration is explicit non-scope (plan §2).
- Cluster geometry is buffered convex hull, not a true fire-shape estimate.
- No baseline twin in v1 — cut for MVP.
- Reasoning is templated; LLM-generated reasoning is a v2 affordance.
