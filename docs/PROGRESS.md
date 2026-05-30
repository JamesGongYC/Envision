# Envision — Progress log

## v2 Day 1 complete

**Date:** 2026-05-29

### Migration 004

- Added [`db/migrations/004_v2_additions.sql`](../db/migrations/004_v2_additions.sql) (`forecasts.trace`, `skill_edit_proposals.curator_trace`, `signal_catalog` materialized view).
- Updated retention comment block in [`db/migrations/002_hardening.sql`](../db/migrations/002_hardening.sql) to 30d signals / 60d forecasts / indefinite ground_truth, evaluations, proposals.
- **Applied on Neon** (2026-05-30).

### Sync tooling

- [`tools/sync_skills.py`](../tools/sync_skills.py) — dry-run by default; `--apply` syncs repo → `~/.hermes/skills/`; `--prune` removes runtime orphans.
- Uses `rsync` when available; Python shutil fallback on Windows without rsync.
- Pruned runtime orphan `usgs-hello-world` (already deleted from repo).

### Retention skill

- New skill: [`agent/skills/housekeeping/housekeeping-retention/`](../agent/skills/housekeeping/housekeeping-retention/)
- Cron registered: `hermes cron add "24h" "Run the housekeeping-retention skill"`.
- Smoke test (2026-05-30): deleted 0 signals / 0 forecasts; `signal_catalog` refresh OK.

### Skill refactor (`run(now, db)`)

All 10 existing skills refactored to expose `def run(now: datetime, db: Connection)`:

| Skill | Script |
|---|---|
| firms-active-fires | `ingest_firms.py` |
| nws-fire-alerts | `ingest_nws.py` |
| nhc-cyclones | `ingest_nhc.py` |
| gdacs-ground-truth | `ingest_gdacs.py` |
| wildfire-risk-elevated | `detect_wildfire_risk.py` |
| wildfire-rapid-growth | `detect_wildfire_rapid_growth.py` |
| typhoon-intensifying | `detect_typhoon_intensifying.py` |
| typhoon-landfall-imminent | `detect_typhoon_landfall.py` |
| forecast-evaluator | `evaluate_forecasts.py` |
| curator | `run_curator.py` |

Detection skills parameterize SQL `now()` and add `AND timestamp <= %s` on all `signals` queries. Ingestion skills stamp `ingested_at = now`.

### Trace schema

- [`docs/TRACES.md`](TRACES.md) — JSONB shape for `forecasts.trace` and `curator_trace` (population deferred to Day 6).

### v3 note

- TODO added in [`docs/v3_plan.md`](v3_plan.md): renumber `004_evolution.sql` → `005_evolution.sql` when v3 starts.

### Smoke test status

- Ingestion, detection, evaluator: run clean against live Neon (empty/off-season results are normal).
- `from detect_wildfire_risk import run` import verified (v3 harness contract).
- `housekeeping-retention`: smoke test passed after migration 004 applied on Neon.
- Curator: refactor complete; LLM calls may fail until Anthropic API access is fixed (HTTP 403 observed).

---

## v2 Day 2 complete

**Date:** 2026-05-30

### D1 — Global FIRMS

- Refactored [`agent/skills/ingest/firms-active-fires/scripts/ingest_firms.py`](../agent/skills/ingest/firms-active-fires/scripts/ingest_firms.py): 6 continental bboxes × `VIIRS_NOAA20_NRT` + `MODIS_NRT`, 8000 row cap per call, partial failure tolerance.
- `run(now, db) -> tuple[int, int]` (inserted, queries_succeeded); exit 1 only if all 12 queries fail.
- SKILL.md bumped to v0.2.0.

### D2 — Open-Meteo fire weather

- New skill: [`agent/skills/ingest/open-meteo-fire-weather/`](../agent/skills/ingest/open-meteo-fire-weather/)
- 118 fire-prone region centroids in `fire_regions.json`; daily/hourly forecast scoring (threshold ≥3).
- Smoke test: **64** `open_meteo` / `fire_weather` signals inserted.
- Neon idle-connection fix: per-region insert with reconnect on `OperationalError`.
- Cron registered: `hermes cron add "3h" "Run the open-meteo-fire-weather skill"`.

### D3 — JTWC cyclones

- New skill: [`agent/skills/ingest/jtwc-cyclones/`](../agent/skills/ingest/jtwc-cyclones/)
- ATCF a-deck parser + `fixtures/sample_wp.dat` (WP storm MALOU).
- Fixture smoke test: 1 `jtwc` / `cyclone_advisory` signal inserted.
- Live fetch: JTWC products page returned HTTP 403 from this environment (pre-season zero-storm path still OK via fixture).
- Cron registered: `hermes cron add "6h" "Run the jtwc-cyclones skill"`.

### D4 — signal_catalog

- Migration 004 applied; `REFRESH MATERIALIZED VIEW CONCURRENTLY signal_catalog` succeeded.
- **6** `(source, signal_type)` pairs after Day 2 smoke runs:

| source | signal_type | row_count |
|---|---|---|
| firms_modis | hotspot | 1130 |
| firms_viirs | hotspot | 681 |
| jtwc | cyclone_advisory | 1 |
| nws_alerts | fire_warning | 162 |
| open_meteo | fire_weather | 64 |
| usgs_quake_test | earthquake | 1 |

- `signals` table size: **3568 kB** (well under 0.4 GB watch threshold).

### D5 — Viewer attribution

- Extended [`viewer/lib/signal-sources.ts`](../viewer/lib/signal-sources.ts): `SIGNAL_SOURCE_ATTRIBUTION`, labels and URLs for `open_meteo` and `jtwc`.

### Hermes cron

- **13** active Hermes cron jobs (including housekeeping-retention 24h).

### Operator notes

- Re-run `python tools/sync_skills.py --apply` after pulling Day 2 changes.
- JTWC live ingest may need a network path that can reach `metoc.navy.mil` without 403; fixture path validates parser offline.
- Open-Meteo full run takes ~4 min (118 API calls); expect intermittent Neon SSL drops if inserting in one batch — fixed in repo via reconnect helper.

---

## v2 Day 3 complete — six sources validated, signals at 5792 kB, retention 30d

**Date:** 2026-05-30

### D1 — signal_catalog refresh

- Manual run: `[housekeeping-retention] deleted 0 signals, 0 forecasts; refreshed signal_catalog.`
- Catalog snapshot after refresh:

| source | signal_type | row_count | last_seen (UTC) |
|---|---|---:|---|
| firms_modis | hotspot | 1332 | 2026-05-30 06:10 |
| firms_viirs | hotspot | 3811 | 2026-05-30 08:06 |
| nws_alerts | fire_warning | 162 | 2026-05-29 19:00 |
| open_meteo | fire_weather | 64 | 2026-06-01 00:00 |
| jtwc | cyclone_advisory | 1 | 2023-05-25 00:00 (fixture) |
| usgs_quake_test | earthquake | 1 | stale test row (informational) |

Active sources (FIRMS ×2, NWS, Open-Meteo) have recent data; NHC absent (pre-season); JTWC fixture row only.

### D2 — `tools/validate_signals.py`

- New read-only validator: row count, geometry validity, alias-aware payload shape, dedup health.
- All 6 sources pass (exit 0):

| source | rows_24h | status |
|---|---:|---|
| firms_viirs | 3217 | PASS |
| firms_modis | 973 | PASS |
| nws_alerts | 25 | PASS |
| nhc | 0 | INFO (pre-season) |
| open_meteo | 64 | PASS |
| jtwc | 1 | PASS |

- Open-Meteo payload shape OK with suffixed keys (`temp_max_c`, `rh_min_pct`, `wind_max_kmh`, `precip_sum_mm`, `region`) — hourly RH aggregation confirmed via `rh_min_pct`.

### D3 — Volume + retention

| rows | total_size | bytes/row |
|---:|---|---:|
| 5371 | 5792 kB | 1104 |

**Decision:** < 0.2 GB → no change. Retention stays **signals 30d / forecasts 60d**.

### D4 — Viewer attribution

- Reviewed [`viewer/lib/signal-sources.ts`](../viewer/lib/signal-sources.ts): `open_meteo` (CC BY 4.0) and `jtwc` (public domain) entries present with correct URLs.
- `cd viewer && npm run build` — clean (Next.js 16.2.6, TypeScript OK).
