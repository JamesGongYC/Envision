---
name: typhoon-landfall-imminent
description: Detects active tropical cyclones whose 72h projected track covers populated areas (>=10⁴). Writes one forecast per qualifying storm.
---

# typhoon-landfall-imminent

Detection skill — fourth of four for Envision Day 3.

## What it does
1. Pulls the latest NHC advisory per storm (within last 6h).
2. For each storm with position + heading + speed:
   - Projects its position forward at t = 0, 6, 12, 24, 36, 48, 60, 72h.
   - Buffers each forecast point by a growing radius (40 → 200 km).
   - Unions the buffers into an approximated cone polygon.
3. Queries `populated_places` for cities (pop ≥ 10⁴) intersecting the cone.
4. Emits one `forecasts` row per storm with at least one city inside.

## Inputs (read)
- `signals` where `source = 'nhc'` and `signal_type = 'cyclone_advisory'`, last 6h.
- `populated_places` (loaded once via `bootstrap_populated_places.py`).

## Outputs (write)
- `forecasts` rows with:
  - `disaster_class = 'typhoon'`
  - `valid_from = now()`, `valid_until = now() + 72h`
  - `geometry` = approximated cone polygon
  - `probability` ∈ [0.45, 0.85]: base + city-count bonus + log-scaled population bonus
  - `reasoning` = template listing top 5 affected cities, heading, speed, total population
  - `contributing_signal_ids` = the latest NHC advisory ID
  - `skill_id = 'typhoon_landfall_imminent'`, `skill_version = 1`, `is_baseline = false`

## Cadence
3 h, after NHC ingestion. Same tick as `typhoon-intensifying`.

## One-time setup (BEFORE first run)

### Step 1 — Apply migration 003
In the Neon SQL editor, paste the contents of
`db/migrations/003_populated_places.sql` and run it. Confirm with:
```sql
\dt populated_places
```
(or `SELECT count(*) FROM populated_places;` which should return 0.)

### Step 2 — Run the bootstrap loader
From Git Bash with `DATABASE_URL` exported:
```sh
python ~/.hermes/skills/typhoon-landfall-imminent/scripts/bootstrap_populated_places.py
```
Downloads ~10MB from GeoNames, filters to pop ≥ 10⁴, inserts ~30k rows.
Takes 1–2 minutes. Idempotent (safe to re-run).

After it finishes:
```sql
SELECT count(*) FROM populated_places;
-- expect ~30,000 (varies slightly with GeoNames updates)
```

## How to run (after setup)
```sh
python scripts/detect_typhoon_landfall.py
```

## Dependencies
- `psycopg`, `shapely` (already installed for skill 2)
- No `scikit-learn` needed for this skill.

## Expected behaviour
- Off-season: "no active NHC advisories in last 6h" — clean exit.
- Active storm over open ocean: "cone covers no populated places".
- Storm with a populated-coast trajectory: one forecast row, geometry is the cone.

## Notes / known shortcuts (v1)
- **Cone is approximated** from a single bulletin's heading + speed.
  Real NHC cones are derived from ensemble forecast tracks and account
  for steering uncertainty; ours assumes constant velocity. Refining to
  use NHC's actual cone KMZ is v2.
- **Buffer radii** are a coarse approximation of NHC's 5-year average
  track error (40→200 km from t=0 to t=72h). Real NHC cones at 72h are
  ~180 km radius, so we're in the right ballpark.
- **Population data** is GeoNames cities5000 filtered to pop ≥ 10⁴.
  Plan §7 called for GHSL raster; we substituted point cities for v1
  simplicity. Loses sub-city resolution but matches the population threshold.
- **No coastline filter.** Plan §7 specifies "coastline with population
  within 50km". We dropped the coastline check — a cone over inland
  cities is still a valid landfall hazard once the storm makes landfall.
- **Latitude correction** on buffer ellipses prevents east–west squish
  at high latitudes but is still approximate.
- No baseline twin (cut for MVP).
