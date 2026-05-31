# v2 Day 5 — AIFS Multi-Source Signal Producer

**Scope.** Ship AIFS as a multi-source signal producer on Day 4's Modal infrastructure. One skill, one GRIB download per cycle, multiple signal types emitted. Each signal type is an independent feature extraction from the same underlying AIFS forecast. Substantive substrate widening — AIFS contributes 4 distinct (source, signal_type) pairs by end of Day 5.

## Canonical context

Attach via `@`:

- `@docs/envision_plan.md`
- `@docs/v2_plan.md`
- `@docs/v2_day4_ticket.md` (Modal infrastructure + polygon aggregation patterns to reuse)
- `@docs/PROGRESS.md`
- `@db/schemas.py`
- `@agent/modal_skills/ecmwf-fire-weather-derived/` (template for Modal-native skill structure)

## Pre-decided

**Inherited from Day 4:** Modal-native skill, `agent/modal_skills/<id>/` location, reuses `envision-neon` secret, `cfgrib` + `eccodes` + `xarray` deps in image, `shapely.unary_union` for polygon aggregation.

**New for Day 5:**

1. **One skill, multiple signal types.** Single AIFS skill downloads a multi-variable GRIB subset once per cycle and emits four distinct `signal_type` values. Justification: same source data, same cadence, same forecast horizons, same download — splitting into 4 skills would just multiply download cost. Per-signal-type logic lives in dedicated functions inside `run.py` for clean extension and individual disablement.

2. **AIFS writes to `signals`, not `forecasts`.** All AIFS output is upstream signal data, consumed downstream by detection skills (rule-based now, agentic in v4). Same `source='aifs'` across all signal types; `signal_type` distinguishes the feature kind.

3. **Four signal types emitted:**

   | signal_type | Geometry | Variables | Threshold | Purpose |
   |---|---|---|---|---|
   | `cyclone_feature` | Point | `msl`, `vo`@850hPa | mslp<1005hPa AND \|vo\|>1e-4 s⁻¹ | Tropical/sub-tropical low-pressure systems |
   | `fire_weather_grid` | Polygon | `2t`, `2d`, `10u`, `10v`, `tp` | 4-component score ≥3 | AI-derived fire weather (complement to ECMWF's rule-based version) |
   | `high_wind_corridor` | Polygon | `10u`, `10v` | wind_speed > 60 km/h (16.7 m/s) | Storm-force wind regions — drives fire spread, signals storm danger |
   | `heavy_precipitation_band` | Polygon | `tp` (24h accumulation) | tp_24h > 50 mm | Heavy rainfall — suppresses fire, indicates cyclone landfall impact |

4. **Forecast horizons.** All signal types extracted from +24h forecast (alignment with ECMWF Day 4). Cyclone features additionally tracked across +0/+24/+48/+72h to compute persistence. Other signal types: +24h only for v2; multi-horizon analysis is v2.1+.

5. **Per-signal timestamps.** `timestamp` = forecast valid time (run_time + horizon). For `cyclone_feature` signals, one row per persisted feature per forecast hour. For polygon signal types, one row per polygon per forecast horizon used.

6. **Variables to fetch.** Combined subset from AIFS:
   - `msl` (mean sea level pressure)
   - `vo` at 850 hPa
   - `2t` (2-meter temperature)
   - `2d` (2-meter dewpoint temperature)
   - `10u`, `10v` (10-meter wind components)
   - `tp` (total precipitation, 24h accumulation)
   
   Estimated subset size: ~150–300 MB per cycle. Still manageable.

7. **Feature-extraction details:**

   **`cyclone_feature`:** Same as previous draft.
   - Gaussian-smooth `msl` (sigma=2). Local minima where `msl < 1005 hPa`.
   - Retain where `|vo_850| > 1e-4 s⁻¹` at the minimum.
   - Persist features across forecast hours via spatial proximity (greedy match within 300 km).
   - Emit per feature per forecast hour (≥2-hour persistence required).
   - Payload includes `feature_id` UUID per persisted feature, `mslp_hpa`, `vorticity_850_s-1`, `feature_strength` (0–1).

   **`fire_weather_grid`:** Same algorithm as ECMWF Day 4.
   - Per cell: `score = (temp_2m > 30°C) + (dewpoint_depression > 15°C) + (wind_10m > 25 km/h) + (precip_24h < 1mm)`.
   - Aggregate contiguous cells where `score ≥ 3` via `shapely.unary_union`.
   - One polygon signal per aggregate region.
   - Payload includes per-polygon mean of each variable + `score`.

   **`high_wind_corridor`:**
   - Per cell: `wind_speed = sqrt(10u² + 10v²)` in m/s.
   - Mask cells where `wind_speed > 16.7 m/s` (60 km/h).
   - Aggregate contiguous high-wind cells via `unary_union`.
   - One polygon signal per aggregate region.
   - Payload: max wind speed in polygon, mean wind direction, polygon area km².

   **`heavy_precipitation_band`:**
   - Per cell: 24h-accumulated precipitation from `tp`.
   - Mask cells where `tp_24h > 50 mm`.
   - Aggregate contiguous cells via `unary_union`.
   - One polygon signal per aggregate region.
   - Payload: max precip in polygon, mean precip, polygon area km².

8. **Cadence: 12h, offset from ECMWF.** Schedule Modal cron at 05:00 and 17:00 UTC. Single cron fires all four extractions in one container run.

9. **Polygon validity.** Run `make_valid()` on every aggregated polygon before insert, or use PostGIS `ST_MakeValid()` at the DB layer. `unary_union` can produce self-intersecting polygons in complex contiguous regions.

10. **No probability, no reasoning, no `is_baseline`.** Forecast-table semantics, not signal-table. Feature/extraction strength becomes a payload field where applicable; downstream skills decide what to do with it.

11. **Per-type disablement.** Each emission path in `run.py` should be in its own function and gated by an env var (`AIFS_EMIT_CYCLONE_FEATURE=true`, etc.). If one extraction is pathological (volume spike, bad geometry), operator disables it via Modal secret update without disabling the whole skill.

## Deliverables

### D1 — Skill scaffolding: `agent/modal_skills/aifs-overlay/`

Net-new Modal-native skill. Same pattern as Day 4's ECMWF skill, expanded image:

- `SKILL.md` — describes the skill: AIFS as multi-source signal producer, 4 signal types, downstream consumption (rule-based + future agentic).
- `app.py`:
  - Image: `modal.Image.debian_slim().apt_install("libeccodes-dev").pip_install("cfgrib", "xarray", "eccodes", "scipy", "shapely", "psycopg[binary]", "numpy", "httpx")`. Same as ECMWF Day 4 plus `scipy`.
  - Secret: `modal.Secret.from_name("envision-neon")` (reused).
  - Function: `@modal.function(image=image, secrets=[...], schedule=modal.Cron("0 5,17 * * *"))` calling `run.run(now, db)`.
- `run.py` — orchestrator exposing `def run(now: datetime, db: Connection) -> dict` returning `{signal_type: count}`. Inside:
  - `_download_and_parse(now)` — single GRIB fetch + parse into xarray Datasets per variable.
  - `_emit_cyclone_features(ds, db, now)` — per pre-decided (7).
  - `_emit_fire_weather_grid(ds, db, now)` — per pre-decided (7).
  - `_emit_high_wind_corridor(ds, db, now)` — per pre-decided (7).
  - `_emit_heavy_precipitation_band(ds, db, now)` — per pre-decided (7).
  - Each emission function gated by env var per pre-decided (11).

**Acceptance:** `modal run agent/modal_skills/aifs-overlay/app.py` executes one cycle without errors. With all 4 emission paths enabled, returns a dict with counts for each.

### D2 — Multi-extraction pipeline

Per pre-decided (7). Each emission function:

- Reads the relevant xarray DataArrays.
- Applies thresholds.
- Emits signals via `ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(...), 4326))` geometry.
- Returns row count for orchestrator's summary dict.

Per-signal payload includes a `forecast_hour` field (24, or 0/24/48/72 for cyclones), a `run_time` field (ECMWF cycle timestamp), and signal-type-specific fields per pre-decided (7).

**Acceptance per signal type:**

- `cyclone_feature`: pre-season may emit 0 features (legitimate). Verify by inspecting MSLP field.
- `fire_weather_grid`: at any time of year, some regions globally should meet criteria. Expect 5–50 polygons per cycle.
- `high_wind_corridor`: similar, 5–30 polygons per cycle in any season (mid-latitude storm tracks, jet stream).
- `heavy_precipitation_band`: variable; tropical convergence zones and mid-latitude systems typically yield 10–40 polygons per cycle.

If a path emits zero rows AND the input field has no values meeting the threshold, that's correct, not failure.

### D3 — Deploy + verification

- `modal deploy agent/modal_skills/aifs-overlay/app.py`.
- Verify in Modal dashboard: function listed, schedule `0 5,17 * * *`.
- Manual trigger via `modal run`.
- Check Neon:
  ```sql
  SELECT signal_type, count(*), count(DISTINCT payload->>'feature_id') AS distinct_features,
         min(timestamp), max(timestamp)
  FROM signals WHERE source = 'aifs'
  GROUP BY signal_type
  ORDER BY signal_type;
  ```
- Refresh `signal_catalog`: 4 rows visible with `source='aifs'`.

**Acceptance:** all 4 signal types appear in `signal_catalog`. If `cyclone_feature` has 0 rows, that's acceptable for pre-season; the other three should have non-zero counts under normal global weather.

### D4 — Viewer attribution

Add `aifs` entry to `viewer/lib/signal-sources.ts`:

- Display name: "AIFS (ECMWF AI Forecasting System)"
- URL: `https://www.ecmwf.int/en/about/media-centre/news/2024/aifs-our-new-ml-model`
- License: per ECMWF Open Data terms.
- Description: "Model-derived weather signals from ECMWF's AIFS AI model. Multiple signal types (cyclone features, fire weather grid, high wind corridors, heavy precipitation bands). Upstream input for downstream detection skills."

Single attribution entry covers all 4 signal_types since they share source.

### D5 — Documentation

- `docs/METHODS.md` — append AIFS section covering:
  - Source description (ECMWF AIFS model)
  - All 4 signal types and their extraction algorithms
  - Why AIFS is a signal producer (not forecast producer) — positioned for downstream consumption, aligns with v4 agent-team direction
  - Per-type disablement mechanism
  - Exclusion from v3 mutation surface (skill_id pattern `aifs-*` not generated by v3 generator)
- `docs/PROGRESS.md` — Day 5 closeout: AIFS multi-source signal producer live, `signal_catalog` advances by 4 (source, signal_type) pairs.

## Out of scope

- **Heat dome detection** (multi-day persistent extreme heat) — v2.1+. Requires cross-horizon temperature analysis; meaningful enough to warrant its own design pass.
- **AIFS atmospheric river detection** (integrated vapor transport) — v2.1+. Useful but outside v2 substrate-widening goals.
- **Multi-horizon analysis for non-cyclone signal types** — v2.1+. Currently +24h only for fire-weather/wind/precip.
- AIFS-direct forecast skill (yardstick) — v2.1+ stretch.
- v3 mutation-surface enforcement — v3.
- Detection skills consuming AIFS signals — explicitly post-v2.
- Trace JSONB *population* — Day 6.

## Notes / gotchas

- **AIFS endpoint may differ from HRES.** Verify exact URL pattern via ECMWF Open Data docs. AIFS path likely uses `/aifs/` instead of `/ifs/`.
- **AIFS publication delay.** ML inference adds time; 5h post-cycle is conservative. Verify against actual file listing.
- **Hemisphere sign for vorticity.** Use `abs(vo)` in `cyclone_feature` threshold check — NH positive, SH negative.
- **`signal_type='cyclone_feature'` vs `'cyclone_advisory'`.** Distinct semantics. `cyclone_advisory` (NHC, JTWC) = human-issued bulletin (high confidence). `cyclone_feature` (AIFS) = model-detected possible center (lower confidence). Downstream weights differently.
- **`fire_weather_grid` from AIFS vs ECMWF.** Same signal_type, different sources. Both contribute rows; consumers filter by source if provenance matters. This is intentional — gives the future v3 mutator material to combine sources.
- **Polygon volume from multiple extraction paths.** Per cycle, all 4 signal types together might emit 30–150 polygons globally. Multiplied by 2 cycles/day = ~60–300 rows/day from this skill alone. Modest compared to FIRMS volume; watch `signals` table size after Day 5 anyway.
- **Per-type kill switch via env var.** Setting `AIFS_EMIT_HIGH_WIND_CORRIDOR=false` in the Modal secret disables just that emission path; others continue. Useful if one type proves pathological without disabling all of AIFS.
- **`feature_id` only for cyclone_feature.** Polygon-based signal types don't have a feature_id; they're per-cycle aggregates. If cross-cycle grouping is needed downstream, that's a v4 agentic concern.
- **Container image reuse with ECMWF Day 4.** AIFS image is ECMWF image + scipy. Worth defining a shared base in `agent/modal_skills/_shared/image.py` to save repeated builds. Optional optimization.
- **Pre-season `cyclone_feature` may be 0.** Verify by inspecting MSLP field — if no minima below 1005 hPa exist with associated vorticity, 0 is correct. Other signal types should always emit nontrivial counts.

## Done definition

- D1–D5 acceptance criteria met.
- Modal dashboard shows `aifs-overlay` scheduled at 05:00 and 17:00 UTC.
- `signal_catalog` advances by 4 (source, signal_type) pairs: `(aifs, cyclone_feature)`, `(aifs, fire_weather_grid)`, `(aifs, high_wind_corridor)`, `(aifs, heavy_precipitation_band)`.
- Modal hosts 3 skills: ECMWF, curator, AIFS.
- `PROGRESS.md` "v2 Day 5 complete" section: AIFS multi-source signal producer live, 4 signal types contributing to substrate-widening goal.
