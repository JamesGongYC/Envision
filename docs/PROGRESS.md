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
| curator | Modal: `agent/modal_skills/curator/run.py` (Hermes copy retired Day 4) |

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

---

## v2 Day 4 complete

**Date:** 2026-05-30

### D1 — Modal infrastructure

- Secret `envision-neon` created on Modal (`DATABASE_URL`, `ANTHROPIC_API_KEY`, `ENVISION_CURATOR_ENABLED`).
- [`agent/modal_skills/README.md`](../agent/modal_skills/README.md) documents Modal-native skills (bypass `sync_skills.py`).

### D2 — ECMWF `ecmwf-fire-weather-derived`

- Modal app: GRIB download via `ecmwf-opendata`, cfgrib parse, 0–4 fire weather score, polygon aggregation.
- Smoke + deploy: **93** `ecmwf_open_data` / `fire_weather_grid` polygons (2026-05-30 00Z cycle, valid 2026-05-31).
- Schedule: **04:00 + 16:00 UTC** (`modal.Cron("0 4,16 * * *")`).
- Pin: `cfgrib==0.9.15.0`, `eccodes==2.39.1`.
- Batch insert + reconnect fix for Neon idle drops during polygon processing.

### D3 — Curator migration

- Canonical code: [`agent/modal_skills/curator/run.py`](../agent/modal_skills/curator/run.py).
- Skills staging harness copies detection scripts to `~/.hermes/skills/` in-container.
- Hermes `curate: curator` cron removed; `agent/skills/curator/` deleted; runtime pruned.
- Smoke: 1 proposal inserted (`wildfire_rapid_growth`); 1 skipped (pending proposal exists).
- Schedule: **04:00 UTC** daily.

### D4 — Deploy + verification

| Check | Result |
|---|---|
| ECMWF signals | 93 rows, max valid time 2026-05-31 |
| Pending proposals | 2 |
| `signal_catalog` | `(ecmwf_open_data, fire_weather_grid, 93)` |
| `signals` volume | 7639 rows, **7208 kB** |

Deployed:
- https://modal.com/apps/jamesgongyc/main/deployed/ecmwf-fire-weather-derived
- https://modal.com/apps/jamesgongyc/main/deployed/curator

### D5 — Documentation

- [`docs/METHODS.md`](METHODS.md): ECMWF derived index + Modal curator/kill-switch paths.
- [`docs/SAFETY.md`](SAFETY.md): Modal secret kill-switch instructions.
- [`viewer/lib/signal-sources.ts`](../viewer/lib/signal-sources.ts): `ecmwf_open_data` attribution (CC BY 4.0).

### v2.5 note

Remaining 9 Hermes skills (FIRMS, NWS, detectors, evaluator, housekeeping) migrate to Modal at v2 close. `wildfire-risk-elevated` ECMWF consumption deferred to v2.5.

---

## v2 Day 5 complete

**Date:** 2026-05-30

### D0 — Shared AIFS module

- [`agent/modal_skills/_shared/`](../agent/modal_skills/_shared/): `aifs_common.py` (download, parse, insert), `grid.py` (polygon aggregation), `image.py` (pinned Modal image).

### D1 — Five Modal skills

| Skill | Smoke insert | Schedule (UTC) |
|---|---:|---|
| `aifs-cyclone-feature` | 32 | 05:00, 17:00 |
| `aifs-fire-weather-grid` | 53 | 05:10, 17:10 |
| `aifs-high-wind-corridor` | 33 | 05:15, 17:15 |
| `aifs-heavy-precipitation-band` | 25 | 05:20, 17:20 |
| `aifs-heat-dome` | 8 | 05:25, 17:25 |

All write `source='aifs'` to `signals`. Cyclone vorticity derived from 850 hPa u/v (AIFS has no `vo` on Open Data).

### D3 — Deploy + verification

| Check | Result |
|---|---|
| `signal_catalog` (aifs) | 5 rows: cyclone_feature (32), fire_weather_grid (53), high_wind_corridor (33), heavy_precipitation_band (25), heat_dome (8) |
| Total signals volume | 7824 rows, **7352 kB** |
| Modal deploy | 5/5 apps deployed; **3/5 on cron** (workspace limit 5: ECMWF + curator + cyclone + fire-weather + wind). `heavy-precipitation-band` + `heat-dome` deployed **manual-trigger** until plan upgrade |

Deployed (all five):
- https://modal.com/apps/jamesgongyc/main/deployed/aifs-cyclone-feature
- https://modal.com/apps/jamesgongyc/main/deployed/aifs-fire-weather-grid
- https://modal.com/apps/jamesgongyc/main/deployed/aifs-high-wind-corridor
- https://modal.com/apps/jamesgongyc/main/deployed/aifs-heavy-precipitation-band (manual cron)
- https://modal.com/apps/jamesgongyc/main/deployed/aifs-heat-dome (manual cron)

### D4 — Viewer

- [`viewer/lib/signal-sources.ts`](../viewer/lib/signal-sources.ts): `aifs` attribution entry.
- `cd viewer && npm run build` — clean.

### D5 — Documentation

- [`docs/METHODS.md`](METHODS.md): AIFS five-skill table + algorithms.
- [`agent/modal_skills/README.md`](../agent/modal_skills/README.md): 7 Modal apps documented.

### v2 substrate note

`signal_catalog` gains **5** `(aifs, signal_type)` pairs. Combined with Day 4 ECMWF, substrate now includes model-derived fire weather from two sources intentionally.

---

## v2 Day 6 complete

**Date:** 2026-05-30

### D1 — Authoritative trace schemas

- [`docs/TRACES.md`](TRACES.md) finalized: per-skill sub-fields, 12 KB soft cap / 16 KB hard cap, truncation order, do-not-include list.

### D2 — Shared `TraceBuilder`

- New [`agent/lib/trace_builder.py`](../agent/lib/trace_builder.py): `TraceBuilder`, `CuratorTraceBuilder`.
- Tests: [`agent/lib/test_trace_builder.py`](../agent/lib/test_trace_builder.py) (6 cases, all pass).
- [`tools/sync_skills.py`](../tools/sync_skills.py): copies `trace_builder.py` into each `detect/` skill `scripts/` on `--apply`.
- [`agent/modal_skills/curator/app.py`](../agent/modal_skills/curator/app.py): mounts `agent/lib` at `/root/agent_lib`.

### D3 — Detection skill instrumentation

All four Hermes detection skills insert `forecasts.trace` via `TraceBuilder`:

| Skill | Script |
|---|---|
| `wildfire_rapid_growth` | `detect_wildfire_rapid_growth.py` |
| `typhoon_intensifying` | `detect_typhoon_intensifying.py` |
| `typhoon_landfall_imminent` | `detect_typhoon_landfall.py` |
| `wildfire_risk_elevated` | `detect_wildfire_risk.py` |

Run after deploy: `python tools/sync_skills.py --apply`, then each `detect_*.py` script; spot-check with `tools/validate_traces.py`.

Smoke (2026-05-30): `sync_skills.py --apply` copies `trace_builder.py` to detect skills; DB round-trip insert with full trace JSONB succeeded; live detector runs exit 0 (no matching cells/alerts this cycle — traces appear on next forecast write). `validate_traces.py --hours 168` passes with WARN on legacy `{}` traces and off-season typhoon rows.

### D4 — Curator trace

- [`agent/modal_skills/curator/run.py`](../agent/modal_skills/curator/run.py): `curator_trace` on insert (`brier_stats_observed`, `ast_validation`, prompt hash, LLM response).
- Redeploy: `python -m modal deploy agent/modal_skills/curator/app.py`

### D5 — Validation tooling

- New [`tools/validate_traces.py`](../tools/validate_traces.py): samples 5 rows per component / 24h window.

### D6 — Documentation

- [`docs/METHODS.md`](METHODS.md): §4b traces.
- v3 prerequisite **#2** satisfied ([`docs/v3_plan.md`](v3_plan.md) §11): mutator can read `forecasts.trace` and `curator_trace` on new rows.

---

## v2 Day 7 complete

**Date:** 2026-05-30

### D1 — Status header

- [`viewer/components/status-header.tsx`](../viewer/components/status-header.tsx): skills active (24h), last ingestion, curator activity inferred from `max(proposed_at)` (stale if &gt;30h).
- [`viewer/lib/time-ago.ts`](../viewer/lib/time-ago.ts), new queries in [`viewer/lib/agent-queries.ts`](../viewer/lib/agent-queries.ts).
- Wired in [`viewer/app/layout.tsx`](../viewer/app/layout.tsx) above disclaimer; `revalidate = 60`.

### D2 — Skill metadata

- [`viewer/lib/skill-metadata.ts`](../viewer/lib/skill-metadata.ts): 16 entries (4 detection, 8 ingestion incl. `aifs-overlay`, evaluator, curator, housekeeping).

### D3–D5 — `/agent` ops surface

- [`viewer/components/skill-card.tsx`](../viewer/components/skill-card.tsx) grid replaces stats table.
- [`viewer/app/agent/page.tsx`](../viewer/app/agent/page.tsx): locked 4-sentence explainer; 30-day Brier/hits/FP via `buildSkillCards()`.

### D4 — Sparkline

- [`viewer/components/brier-sparkline.tsx`](../viewer/components/brier-sparkline.tsx): bars (2–3 versions), polyline (≥4), y-cap at 0.5 with clip marker.

### D6 — Tooltips

- [`viewer/lib/tooltips.ts`](../viewer/lib/tooltips.ts); mirrored on [`viewer/app/about/page.tsx`](../viewer/app/about/page.tsx) and [`docs/METHODS.md`](METHODS.md).

### D7 — Build

- `cd viewer && npm run build` — verify locally before Vercel deploy.
- Deploy: push to Vercel-connected branch or `vercel deploy` from `viewer/`.

---

## v2.5 Day 1 — Foundation (Track A + Track B)

**Date:** 2026-05-30

### Track A — Modal migrations

Three Hermes skills copied to Modal (`run.py` unchanged; `app.py` uses `envision-neon` + `add_local_dir`):

| App | Schedule (UTC) | Smoke (2026-05-30) |
|---|---|---|
| [`housekeeping-retention`](../agent/modal_skills/housekeeping-retention/) | `0 6 * * *` | `deleted 0 signals, 0 forecasts; refreshed signal_catalog` |
| [`gdacs-ground-truth`](../agent/modal_skills/gdacs-ground-truth/) | `0 */6 * * *` | inserted 1 GDACS event (13 feed items) |
| [`forecast-evaluator`](../agent/modal_skills/forecast-evaluator/) | `0 7 * * *` | wrote 2 evaluations (0 hits, 2 fp) |

Modal smoke runs (workspace `jamesgongyc`):

- housekeeping: https://modal.com/apps/jamesgongyc/main/ap-4rQatJkW8J9yoJkRD1zZPr
- gdacs: https://modal.com/apps/jamesgongyc/main/ap-7io1LqP3gPx3BotkuQtbVV
- evaluator: https://modal.com/apps/jamesgongyc/main/ap-EhH5fj8bVo6IuiQrS7gaxe

**Deploy:** `modal deploy` for all three failed with *reached limit of 5 cron jobs* (5 already deployed). Upgrade workspace plan, then:

```bash
python -m modal deploy agent/modal_skills/housekeeping-retention/app.py
python -m modal deploy agent/modal_skills/gdacs-ground-truth/app.py
python -m modal deploy agent/modal_skills/forecast-evaluator/app.py
```

**Hermes cron retirement** (this machine): removed `f41076a4d5ca` (housekeeping-retention), `3fbdbad81f17` (GDACS ground truth), `5637caebb1df` (forecast_evaluator). `hermes cron list` → **7** active jobs (FIRMS, NWS, NHC, 4 detectors). Open-Meteo / JTWC crons were not registered here (plan baseline 12 assumed full v2 Day 2 set).

Hermes CLI on Windows: `python -c "import sys; sys.argv=['hermes','cron','list']; from hermes_cli.main import main; main()"` (wrong `pip install hermes` shadows `hermes-agent`; avoid).

`agent/skills/` and `sync_skills.py` **not** archived (v2.5 Day 3).

### Track B — Map layer architecture

- [`viewer/lib/layer-state.ts`](../viewer/lib/layer-state.ts): `LAYER_TREE`, `DEFAULT_VISIBILITY` (forecasts on; signals off).
- [`viewer/components/layer-visibility-provider.tsx`](../viewer/components/layer-visibility-provider.tsx): context + `localStorage['envision.layers']`.
- [`viewer/components/map-layer-panel.tsx`](../viewer/components/map-layer-panel.tsx): collapsible panel, disabled placeholders for Day 2+ layers.
- [`viewer/components/forecasts-layer.tsx`](../viewer/components/forecasts-layer.tsx): extracted forecast polygons/markers; gated in [`forecast-map-impl.tsx`](../viewer/components/forecast-map-impl.tsx) via `visibility.forecasts`.
- [`viewer/components/providers.tsx`](../viewer/components/providers.tsx) mounted in [`viewer/app/layout.tsx`](../viewer/app/layout.tsx).
- [`viewer/app/page.tsx`](../viewer/app/page.tsx): `<MapLayerPanel />`; legend moved to left under status badge.

**Build:** `cd viewer && npm run build` — passed (Next.js 16.2.6).

**Manual smoke:** toggle Active forecasts off/on; reload persists `envision.layers`. Vercel preview deploy — operator.
