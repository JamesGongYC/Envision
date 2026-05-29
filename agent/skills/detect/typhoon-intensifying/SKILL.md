---
name: typhoon-intensifying
description: Detects tropical cyclones whose central pressure dropped more than 5 hPa over a ~12h window. Writes one forecast per intensifying storm.
---

# typhoon-intensifying

Detection skill — third of four for Envision Day 3.

## What it does
1. Pulls NHC cyclone advisories from `signals` for the last 24h.
2. Groups them by storm id (fallback chain: `id` → `stormId` →
   `binNumber` → `atcfId` → `name`).
3. For each storm, compares its most recent pressure reading against
   the bulletin closest to 12h ago (±2h tolerance).
4. If pressure dropped by more than 5 hPa, emits one forecast.

## Inputs (read)
- `signals` where `source = 'nhc'` and `signal_type = 'cyclone_advisory'`,
  last 24h.

## Outputs (write)
- `forecasts` rows with:
  - `disaster_class = 'typhoon'`
  - `valid_from = now()`, `valid_until = now() + 48h` (within plan's 6–72h envelope)
  - `geometry` = ~200km circular buffer (`1.8°`) around the storm's current position
  - `probability` ∈ [0.50, 0.85]: 0.50 at the 5 hPa threshold, +0.04 per hPa above
  - `reasoning` = templated string with storm name, classification, before/after pressure, elapsed hours
  - `contributing_signal_ids` = the two bulletin signal IDs (earlier + latest)
  - `skill_id = 'typhoon_intensifying'`, `skill_version = 1`, `is_baseline = false`

## Cadence
3 h, after NHC ingestion. NHC publishes new advisories on a 3h cycle
(more frequently for active landfalling storms), so detection can ride
the same tick as ingestion.

## How to run
```sh
python scripts/detect_typhoon_intensifying.py
```

Requires `DATABASE_URL` in env.

## Dependencies
- `psycopg`, `shapely`

## Expected behaviour
- Off-season (most of the year for the Atlantic): no advisories → script
  prints "no NHC advisories" and exits cleanly.
- Active season but no rapid intensification: "tracking N storm(s) ..." then
  "wrote 0 forecasts" — the storms are tracked but none are dropping pressure
  fast enough.
- A rapidly intensifying storm: one forecast row per qualifying storm.

## Notes / known shortcuts (v1)
- Field-name lookups are defensive (`id`/`stormId`/`binNumber`/`atcfId`/`name`,
  `pressure`/`minimumPressure`/`minPressure`/`centralPressure`,
  `latitudeNumeric`/`longitudeNumeric` with string-form fallback). Tighten
  once we see real NHC payloads in the DB.
- Geometry is a fixed 1.8° (~200km) circular buffer. Real cyclone wind fields
  are asymmetric; refining this is v2.
- No baseline twin (cut for MVP).
- The 12h±2h window assumes NHC's ~3h advisory cadence. If a storm has
  patchy bulletin coverage, the script will skip it rather than guess.
