# v2 Day 2 — Substrate Widening

**Scope.** Global FIRMS (drop the US-only bbox), two net-new ingestion skills (Open-Meteo fire weather, JTWC cyclones), `signal_catalog` verification. Ingestion only — no detection, evaluator, or viewer logic changes beyond attribution entries.

## Canonical context

Attach via `@`:

- `@docs/envision_plan.md`
- `@docs/v2_plan.md`
- `@docs/v2_day1_ticket.md` (for conventions to inherit; don't re-explain them)
- `@docs/PROGRESS.md`
- `@db/schemas.py`
- `@agent/skills/ingest/firms-active-fires/scripts/ingest_firms.py` (target of D1 refactor)

## Pre-decided

**Inherited from Day 1** (apply without re-deciding): `run(now, db)` signature; hyphenated dir names; `tools/sync_skills.py --apply` deploy gate; per-skill smoke test before moving to the next skill; `ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(...), 4326))` on geometry inserts; cron stays in agent mode (no-agent conversion deferred by operator).

**New for Day 2:**

1. **FIRMS 6-bbox split.** Continent chunks in FIRMS's `W,S,E,N` order:

   | Region | Bbox |
   |---|---|
   | North America | `-170, 15, -50, 80` |
   | South America | `-90, -60, -30, 15` |
   | Europe | `-15, 35, 60, 80` |
   | Africa | `-20, -40, 55, 40` |
   | Asia | `60, -10, 180, 80` |
   | Oceania | `110, -50, 180, 10` |

   Slight overlap (Asia/Oceania at the dateline, Europe/Africa at the Mediterranean) is fine — md5-payload dedup trigger handles duplicates. Per-bbox row cap raised from 2000 to 8000.

2. **Open-Meteo query strategy.** Static list of ~80–120 fire-prone region centroids in `agent/skills/ingest/open-meteo-fire-weather/fire_regions.json`. Coverage: western North America (CA, OR, WA, CO, NM, AZ, BC, AB); Mediterranean basin (Spain, Portugal, France, Italy, Greece, Turkey); Australia (NSW, VIC, WA, NT, QLD); Amazon (Acre, Rondônia, Mato Grosso); Southern Africa (SA, Mozambique, Botswana); Siberia (Yakutia, Krasnoyarsk); Indonesia (Sumatra, Kalimantan). One entry per region: `{name, lat, lon}`. Cursor populates centroids.

3. **Open-Meteo fire weather index.** Use Open-Meteo's daily forecast endpoint (verify exact variable names via Open-Meteo API docs — daily aggregates of `temperature_2m_max`, RH min, `wind_speed_10m_max`, `precipitation_sum`; if RH isn't available daily, aggregate hourly). Compute a basic score per region: `score = (temp_max > 30°C) + (rh_min < 30%) + (wind_max > 25 km/h) + (precip_sum < 1mm)` — sum of booleans, range 0–4. Emit `fire_weather` signal where `score >= 3`. Threshold subject to tuning during smoke test.

4. **JTWC source.** ATCF current-storm bulletins from `https://www.metoc.navy.mil/jtwc/products/`. Parser reads index page, fetches each active storm's `.dat` ATCF file, emits `cyclone_advisory` signals (same `signal_type` as NHC — interoperable; downstream detectors care about type, not source). Cadence 6h. WP pre-season returns 0 storms; include a saved bulletin fixture for offline parser verification.

5. **EFFIS/GWIS deferred.** Cut-list #5. FIRMS + Open-Meteo + JTWC sufficient for v2 substrate target (≥8 signal types by end of v2 per dependency contract). Revisit in Day 3 only if `signal_catalog` feels thin.

6. **Volume budget.** Global FIRMS pushes signals/day from ~5k to ~50k–200k peak. Neon free tier (~0.5GB) may saturate within v2 timeline. Per v2_plan §10: upgrade to paid if `signals` table > 0.4GB; check daily once D1 lands.

## Deliverables

### D1 — Refactor `firms-active-fires` for global

Existing skill, refactor in place:

- Replace single-bbox config with 6-bbox loop per pre-decided (1).
- Iterate each bbox, query both VIIRS and MODIS sources (existing behavior), parse CSV, insert via dedup trigger.
- Per-call row cap: 8000 (was 2000).
- `run(now, db)` returns total rows inserted across all bboxes.
- **Per-bbox failure tolerance:** if FIRMS times out for one region, log warning and continue. Don't fail the run if 5/6 succeed. Return code reflects partial success.
- Source strings unchanged from Day 1 (whatever the current skill uses — keep dedup keys consistent).

**Acceptance:** dry-run sync clean; smoke test inserts ≥5× the previous US-only run's row count (assuming comparable fire activity globally vs. western US).

### D2 — New skill `open-meteo-fire-weather`

Net-new at `agent/skills/ingest/open-meteo-fire-weather/`:

- `SKILL.md` — purpose, region list reference, threshold.
- `fire_regions.json` — static centroid list per pre-decided (2). Plain JSON array of `{name, lat, lon}`.
- `scripts/ingest_open_meteo.py`:
  - `run(now, db)` loads region list, queries Open-Meteo daily forecast for each (forecast horizon: today + 2 days; one HTTP call per region).
  - Compute index per pre-decided (3).
  - Emit `fire_weather` signal per region where threshold met. Payload includes raw variables, computed score, region name.
  - Geometry: Point at region centroid. `timestamp` = forecast valid date at 00 UTC.
  - Source string: `open_meteo`.

Register cron after smoke: `hermes cron add "3h" "Run the open-meteo-fire-weather skill"`.

**Acceptance:** smoke test produces 5–20 signals depending on season; `signal_catalog` shows new `source=open_meteo, signal_type=fire_weather` row after refresh.

### D3 — New skill `jtwc-cyclones`

Net-new at `agent/skills/ingest/jtwc-cyclones/`:

- `SKILL.md` — purpose, ATCF format note, pre-season expectation.
- `fixtures/sample_wp.dat` — one saved ATCF bulletin for offline parser test (Cursor downloads from any historical WP storm in JTWC's archive).
- `scripts/ingest_jtwc.py`:
  - `run(now, db)` fetches JTWC product index, finds active WP storms, fetches each `.dat`.
  - Parse ATCF: storm name, advisory time, lat/lon, max wind, central pressure, forecast points (12/24/36/48/72h).
  - Emit `cyclone_advisory` signal per storm (one row per advisory, not per forecast point). `timestamp` = advisory time. Payload includes full forecast track and intensity history.
  - Geometry: Point at current storm position.
  - Source string: `jtwc`.
  - Test against fixture in unit-test fashion before live run.

Register cron: `hermes cron add "6h" "Run the jtwc-cyclones skill"`.

**Acceptance:** offline run against `fixtures/sample_wp.dat` parses without error and would insert ≥1 row. Live run during pre-season may emit 0 signals — confirm by checking `https://www.metoc.navy.mil/jtwc/jtwc.html` shows 0 active WP storms.

### D4 — `signal_catalog` post-Day-2 check

After all three skills have ticked at least once, run in Neon SQL Editor:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY signal_catalog;
SELECT source, signal_type, row_count, last_seen FROM signal_catalog ORDER BY source;
```

Expected: existing FIRMS/NWS/NHC/GDACS rows (with FIRMS row counts noticeably higher), plus new `open_meteo`/`fire_weather` and `jtwc`/`cyclone_advisory` (likely 0 rows pre-season).

### D5 — Viewer attribution

Add entries to `viewer/lib/signal-sources.ts`:

- `open_meteo` — Open-Meteo, https://open-meteo.com/, CC BY 4.0.
- `jtwc` — Joint Typhoon Warning Center, https://www.metoc.navy.mil/jtwc/, public domain (US Government work).

Existing FIRMS attribution unchanged.

## Out of scope (Day 2)

- ECMWF GRIB derived index — Day 4.
- AIFS overlay — Day 5.
- EFFIS/GWIS — cut-list #5, deferred.
- Trace JSONB *population* — Day 6 (column was added Day 1).
- Frontend ops surface — Day 7.
- Curator no-agent mode conversion — explicitly deferred by operator.

## Notes / gotchas

- **FIRMS rate limits.** ~1000 requests / 10min per MAP_KEY. 6 bboxes × 2 sources = 12 reqs / 30min cycle = 576/day. Comfortable.
- **Open-Meteo rate limits.** Free tier 10k calls/day. 100 regions × 8 runs/day = 800 calls. Comfortable.
- **JTWC fragility.** ATCF format is stable since the 1980s, but the JTWC index page HTML may shift. Build the parser to fail gracefully — log + return 0 if the index page doesn't match expected structure; don't crash the run.
- **Volume monitoring.** End of D1, run `SELECT pg_size_pretty(pg_total_relation_size('signals'));`. If approaching 0.4 GB, tighten retention from 30d → 14d in the housekeeping skill before Day 4's ECMWF lands.
- **Signal type consistency.** JTWC reuses NHC's `cyclone_advisory` type intentionally. Open-Meteo introduces `fire_weather` — distinct from FIRMS `hotspot` and NWS `fire_warning`. Three fire-related types now; detection skills in Day 3 (already shipped in v1) will need to learn to consume `fire_weather` in future, but that's not Day 2's problem.
- **Pre-season JTWC.** May–June WP basin is typically quiet. 0 active storms is a legitimate result, not a parser failure. Verify live skill against the JTWC index page before treating empty as a bug.

## Done definition

- D1–D5 acceptance criteria met.
- `hermes cron list` shows 11 jobs (was 9 end of Day 1; +2 for Open-Meteo and JTWC).
- `signal_catalog` shows ≥6 distinct `(source, signal_type)` pairs.
- `git status` clean from `~/Downloads/envision/`.
- `PROGRESS.md` updated with a "v2 Day 2 complete" section: global FIRMS live, Open-Meteo + JTWC skills registered, `signals` table size noted for volume tracking.
