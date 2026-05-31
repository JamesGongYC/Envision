---
name: wildfire-rapid-growth
description: Detects 50km grid cells where FIRMS hotspot count grew >50% day-over-day for 2 consecutive days. Writes one forecast per qualifying cell.
---

# wildfire-rapid-growth

Detection skill — second of four for Envision Day 3.

## What it does
1. Pulls FIRMS hotspots from `signals` for the last 72h.
2. Snaps each hotspot into a 50km grid cell (EPSG:3857 Web Mercator).
3. Counts hotspots per cell across three consecutive 24h windows:
   `day_t-2`, `day_t-1`, `day_t`.
4. Emits a forecast for any cell where:
   - `day_t-2 ≥ 1` (need a baseline to grow from)
   - `day_t-1 > 1.5 × day_t-2`
   - `day_t   > 1.5 × day_t-1`
5. Geometry of each forecast = the 50km cell envelope.

## Inputs (read)
- `signals` where `signal_type = 'hotspot'` and `source LIKE 'firms%'`, last 72h.

## Outputs (write)
- `forecasts` rows with:
  - `disaster_class = 'wildfire'`
  - `valid_from = now()`, `valid_until = now() + 24h`
  - `geometry` = 50km cell polygon (EPSG:4326)
  - `probability` ∈ [0.45, 0.85] from base + count bonus + compound-growth bonus
  - `reasoning` = templated string showing the `t-2 → t-1 → t` progression
  - `contributing_signal_ids` = FIRMS hotspot IDs from the last 48h in that cell
  - `skill_id = 'wildfire_rapid_growth'`, `skill_version = 1`, `is_baseline = false`

## Cadence
30 min, after FIRMS ingestion. Same cadence as `wildfire-risk-elevated` —
detectors can share a cron tick.

## How to run
```sh
python scripts/detect_wildfire_rapid_growth.py
```

Requires `DATABASE_URL` in env.

## Dependencies
- `psycopg`, `shapely` (no `scikit-learn` needed for this one — all the
  spatial bucketing is done in PostGIS).

## Expected behaviour early in deployment
This skill needs at least ~72h of FIRMS history with sustained growth in
the same 50km cell. Until the database has that, every run will print
`no cells matched growth rule` — that's correct, not a bug.

## Notes / known shortcuts (v1)
- Web Mercator distorts at high latitudes; cells shrink toward the poles.
  Fine for wildfire activity which concentrates in 30–60° latitudes.
- No baseline twin (cut for MVP per Day 3 decisions).
- Scoring is heuristic. Curator may tune the threshold and weights later.
- Cell boundaries are fixed to the Web Mercator origin grid; fires straddling
  a boundary will register as two smaller cells. Acceptable for v1.
