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

---

## v2.5 Day 2 — Ingestion migrations + point signal layers

**Date:** 2026-05-30

### Track A — Five ingestion Modal apps

| App | Schedule (UTC) | Smoke |
|---|---|---|
| [`open-meteo-fire-weather`](../agent/modal_skills/open-meteo-fire-weather/) | `0 */3 * * *` | 61 `fire_weather` signals from 118 regions — https://modal.com/apps/jamesgongyc/main/ap-TQrAPIzGGZS895iTajJvze |
| [`nhc-cyclones`](../agent/modal_skills/nhc-cyclones/) | `0 */3 * * *` | 0 storms (off-season OK) — https://modal.com/apps/jamesgongyc/main/ap-ps5sQuCQ6DJaxsX3yRTeUH |
| [`jtwc-cyclones`](../agent/modal_skills/jtwc-cyclones/) | `0 */6 * * *` | **HTTP 403** from `metoc.navy.mil` on Modal US IP (browser UA default did not unblock); 0 inserts; fixture parser unchanged — https://modal.com/apps/jamesgongyc/main/ap-Z8TCJxynOq9msaMjj3frBX |
| [`nws-fire-alerts`](../agent/modal_skills/nws-fire-alerts/) | `*/30 * * * *` | 0 matching fire-weather alerts (seasonal OK) — https://modal.com/apps/jamesgongyc/main/ap-QiLxvPw1eCj5iRJSgJAcdv |
| [`firms-active-fires`](../agent/modal_skills/firms-active-fires/) | `*/30 * * * *` | **Blocked:** `FIRMS_MAP_KEY` not on `envision-neon` secret — recreate secret per README |

**Operator:** Add `NWS_USER_AGENT` + `FIRMS_MAP_KEY` to `envision-neon`, upgrade Modal plan, `modal deploy` Day 1 + Day 2 apps.

**Hermes cron retirement:** removed FIRMS `4a6ddd35247a`, NWS `dcdedefb21fb`, NHC `3a51f8809e4c`. **`hermes cron list` → 4 jobs** (detection only).

### Track B — Point signal layers

- [`viewer/lib/signal-queries.ts`](../viewer/lib/signal-queries.ts), [`layer-config.ts`](../viewer/lib/layer-config.ts), [`signal-styling.ts`](../viewer/lib/signal-styling.ts)
- [`viewer/app/api/signals/route.ts`](../viewer/app/api/signals/route.ts) — bbox + `layer_id`, 30s cache
- [`viewer/components/signal-layer.tsx`](../viewer/components/signal-layer.tsx), [`ground-truth-layer.tsx`](../viewer/components/ground-truth-layer.tsx), [`signal-marker.tsx`](../viewer/components/signal-marker.tsx)
- FIRMS clustering via `react-leaflet-cluster`; truncation badge in [`map-layer-panel.tsx`](../viewer/components/map-layer-panel.tsx)
- Seven layers enabled in [`layer-state.ts`](../viewer/lib/layer-state.ts); wired in [`forecast-map-impl.tsx`](../viewer/components/forecast-map-impl.tsx)

**Build:** `cd viewer && npm run build` — passed (includes `/api/signals`).

**Manual smoke:** toggle each point layer; pan map for refetch; FIRMS cluster + truncation subtitle when capped. Vercel preview — operator.

---

## v2.5 Day 3 — Detection + reasoning + polygons + Hermes decommission

**Date:** 2026-05-30

### Track A — Four detection Modal apps + LLM reasoning

**Shared libs:**

- [`agent/lib/reasoning_llm.py`](../agent/lib/reasoning_llm.py) — `generate_reasoning(prompt, fallback)` via Anthropic Sonnet, `max_tokens=200`, never raises.
- [`agent/lib/reasoning_prompts.py`](../agent/lib/reasoning_prompts.py) — locked prompts filled from trace `inputs` / `intermediate` after `TraceBuilder` is populated.

| App | Schedule (UTC) | Smoke (2026-05-30) |
|---|---|---|
| [`wildfire-rapid-growth`](../agent/modal_skills/wildfire-rapid-growth/) | `*/30 * * * *` | 2 forecasts — https://modal.com/apps/jamesgongyc/main/ap-5xagLXw5LfOgufqnOEC0he |
| [`typhoon-intensifying`](../agent/modal_skills/typhoon-intensifying/) | `0 */3 * * *` | 0 (off-season OK) — https://modal.com/apps/jamesgongyc/main/ap-yBulgIiDfTrZVWBSuDaziE |
| [`typhoon-landfall-imminent`](../agent/modal_skills/typhoon-landfall-imminent/) | `0 */3 * * *` | 0 (off-season OK) — https://modal.com/apps/jamesgongyc/main/ap-F0cWq8wG2chi4OzZ9QtJev |
| [`wildfire-risk-elevated`](../agent/modal_skills/wildfire-risk-elevated/) | `*/30 * * * *` | 16 forecasts; polygons from `fire_warning` + `fire_weather_grid` (NWS/ECMWF/AIFS) — https://modal.com/apps/jamesgongyc/main/ap-zEzhbRcToIStMhElJecEnk |

**Deploy:** all four detectors deployed to Modal (`wildfire-rapid-growth`, `wildfire-risk-elevated`, `typhoon-intensifying`, `typhoon-landfall-imminent`). Day 1–2 ingest/housekeeping apps still need operator `modal deploy` if not yet on workspace.

**Hermes cron retirement:** removed `e64e6752c68d`, `b3eeb5b0bb9e`, `0663e2ec5de8`, `521e41e0686e`. **`hermes cron list` → empty.**

**Repo archive:** `agent/skills` → `agent/_archive/skills`; `tools/sync_skills.py` → `tools/_archive/sync_skills.py`. README + METHODS + modal README updated for Modal-only runtime.

### Track B — Polygon layers + forecast dropdown

- [`viewer/lib/signal-styling.ts`](../viewer/lib/signal-styling.ts) — `POLYGON_STYLES` (ECMWF/AIFS fire grid + stretch wind/precip).
- [`viewer/lib/layer-config.ts`](../viewer/lib/layer-config.ts) + [`layer-state.ts`](../viewer/lib/layer-state.ts) — four polygon layers enabled.
- [`viewer/components/polygon-signal-layer.tsx`](../viewer/components/polygon-signal-layer.tsx) — bbox fetch, zoom ≥ 4 gate, GeoJSON popups.
- [`viewer/components/typing-text.tsx`](../viewer/components/typing-text.tsx), [`forecast-dropdown.tsx`](../viewer/components/forecast-dropdown.tsx) — typing reasoning in forecast popups; `bringToFront` on markers.
- Wired in [`forecast-map-impl.tsx`](../viewer/components/forecast-map-impl.tsx).

**Build:** `cd viewer && npm run build` — passed.

**Operator closeout:** Vercel deploy from `viewer/`; git tag `v2.5.0`; confirm `envision-neon` includes `ANTHROPIC_API_KEY`, `FIRMS_MAP_KEY`, `NWS_USER_AGENT`; deploy remaining Day 1–2 Modal apps if cron quota allows.

---

## v2.5 complete

All 12+ core Modal apps (ingest, detect, evaluate, housekeeping, GDACS, curator) documented in [`agent/modal_skills/README.md`](../agent/modal_skills/README.md). Hermes runtime retired. Viewer ships polygon layers and LLM reasoning dropdown.

---

## v2.6 — Frontend design sprint

**Date:** 2026-05-30

### Backend

- Migration [`db/migrations/005_wind_fields.sql`](../db/migrations/005_wind_fields.sql) — gzipped leaflet-velocity payloads (`wind_fields`).
- [`agent/modal_skills/_shared/wind_field.py`](../agent/modal_skills/_shared/wind_field.py) — `build_wind_field_json` + `emit_wind_field`; called from [`aifs-fire-weather-grid/run.py`](../agent/modal_skills/aifs-fire-weather-grid/run.py) when `AIFS_EMIT_WIND_FIELD` is true (default).
- [`viewer/app/api/wind/route.ts`](../viewer/app/api/wind/route.ts) — latest field, gunzip, 6h cache.
- [`housekeeping-retention`](../agent/modal_skills/housekeeping-retention/run.py) — 14d `wind_fields` retention.

**Operator:** Apply migration 005 on Neon before wind API works. `modal run aifs-fire-weather-grid` still inserts fire grids if `wind_fields` is missing (logs warning). After 005: re-run to seed wind row (~2–5 MB `size_bytes`).

### Frontend

- **D1:** FIRMS measle dots — Canvas renderer on `signalsPane`; removed `react-leaflet-cluster`.
- **D2:** Polygon layers at all zooms with `dynamicOpacity()`; `polygonsPane` + Canvas GeoJSON.
- **D3b:** [`wind-layer.tsx`](../viewer/components/wind-layer.tsx) + `leaflet-velocity`; layer `aifs_wind_field` under “Atmospheric flow” (default off).
- **Panes:** [`map-panes.tsx`](../viewer/components/map-panes.tsx) — signals 400, polygons 500, forecasts 600; wind on default tile pane (~200).

**Build:** `cd viewer && npm run build` — verify locally.

**Operator:** Vercel deploy; visual smoke — FIRMS dots, global polygon tint, wind particles when toggled.

---

## v3 Day 1 — Migration 006 + backtest harness

**Date:** 2026-05-30

### Schema

- [`db/migrations/006_evolution.sql`](../db/migrations/006_evolution.sql) — `skill_lineage`, `backtest_run`, `forecasts_shadow`, `skill_edit_proposals.lineage_id`
- [`db/schemas.py`](../db/schemas.py) / [`agent/lib/forecast_model.py`](../agent/lib/forecast_model.py) — `Forecast`, `SkillLineage`, `BacktestRun`, `ShadowForecast`

**Operator:** Apply `006_evolution.sql` in Neon before `backfill_lineage` or harness.

### Refactor

- [`agent/lib/forecast_writer.py`](../agent/lib/forecast_writer.py) — `emit_forecasts()` for `forecasts` / `forecasts_shadow`
- Four detectors: pure `run(now, db) -> list[Forecast]`; Modal `app.py` → `emit_forecasts(run(...), conn)`
- [`agent/lib/scoring.py`](../agent/lib/scoring.py) — shared match + Brier; [`forecast-evaluator/run.py`](../agent/modal_skills/forecast-evaluator/run.py) imports it

### Evolution package

- [`agent/evolution/backtest_harness.py`](../agent/evolution/backtest_harness.py) — replay by cadence, no live INSERTs, leakage audit, LLM bypass
- [`agent/evolution/backtest_connection.py`](../agent/evolution/backtest_connection.py) — `BacktestConnection` proxy enforces `SKILL_LOOKBACK` on all `signals` SELECTs
- [`agent/lib/signal_temporal.py`](../agent/lib/signal_temporal.py) — trailing window + NWS active-as-of-`t` SQL helpers
- [`agent/evolution/backfill_lineage.py`](../agent/evolution/backfill_lineage.py) — manual lineage for 4 skills
- [`agent/evolution/test_backtest_sanity.py`](../agent/evolution/test_backtest_sanity.py) — trailing 7d, all 4 detection skills vs live evaluations (±0.02; UNVERIFIED if &lt;10 evals)
- [`tools/compare_detection_emission.py`](../tools/compare_detection_emission.py), [`tools/compare_evaluator_output.py`](../tools/compare_evaluator_output.py)

### v3 backtest window fix (2026-05-30)

**Ticket:** [`docs/v3_fix_backtest_window.md`](v3_fix_backtest_window.md)

- `wildfire-risk-elevated`: polygon queries use `timestamp` lookback (not `ingested_at`); NWS `effective`/`expires` as-of-`t`
- `typhoon-intensifying`: SQL lookback 14h (12h window + 2h tolerance)
- Harness: full-window guard via `BacktestConnection` (past + future edge)

**Deploy gate:** Do **not** `modal deploy` refactored detection skills until `test_backtest_sanity.py` PASS for all verifiable skills.

**Run sanity (local):**

```bash
python agent/evolution/backfill_lineage.py
python agent/evolution/test_backtest_sanity.py
```

---

## v3 Day 2 — Mutator + validation pipeline

**Date:** 2026-06-01

### Schema

- [`db/migrations/007_lineage_candidates.sql`](../db/migrations/007_lineage_candidates.sql) — nullable `version`, `status` lifecycle, partial unique on promoted rows

**Operator:** Apply after 006:

```bash
psql $DATABASE_URL -f db/migrations/007_lineage_candidates.sql
```

### Code

- [`agent/evolution/mutator.py`](../agent/evolution/mutator.py) — `mutate_skill()` → Sonnet/Haiku `propose_skill_mutation`, persist proposal + candidate lineage
- [`agent/evolution/skill_validator.py`](../agent/evolution/skill_validator.py) — 7-stage validation (AST → sandbox via `BacktestConnection`)
- [`agent/evolution/test_mutator.py`](../agent/evolution/test_mutator.py) — unit + integration tests; live mutate skipped without `ANTHROPIC_API_KEY`

**Run:**

```bash
python agent/evolution/test_mutator.py
python agent/evolution/mutator.py --skill-id wildfire_risk_elevated
python tools/review_proposals.py list
```

**Out of scope this ticket:** backtest scoring/selection (Day 4), shadow deploy (Day 3), auto-promotion.

---

## v3 — Mutator acceptance path

**Date:** 2026-06-01 · Ticket: [`docs/v3_fix_mutator_acceptance.md`](v3_fix_mutator_acceptance.md)

### Changes

- [`agent/evolution/skill_surface.py`](../agent/evolution/skill_surface.py) — `extract_mutation_surface()`, `assert_parent_surface_clean()` (validator check #4 on parent before LLM)
- [`agent/evolution/mutator.py`](../agent/evolution/mutator.py) — surface-only parent from disk/lineage; positive `return list[Forecast]` contract; `MAX_ATTEMPTS=3` retry with feedback; `attempts` in `curator_trace`; injectable `llm_fn`
- Detection `run.py` files — persistence/CLI removed (entrypoint stays in `app.py` via `emit_forecasts(run(...))`)
- [`agent/evolution/backfill_lineage.py`](../agent/evolution/backfill_lineage.py) — stores surface-only in `skill_lineage.source_code`
- [`agent/evolution/test_mutator.py`](../agent/evolution/test_mutator.py) — stubbed happy path, retry, give-up, parent guard; `test_mutate_wildfire_live` smoke (warn + skip on reject)

**Run (no network for happy path):**

```bash
python -m unittest agent.evolution.test_mutator.ValidatorUnitTests agent.evolution.test_mutator.ValidatorIntegrationTests agent.evolution.test_mutator.MutatorStubTests -v
```

---

## v3 Day 3 — Selector + shadow deployment

**Date:** 2026-06-01 · Ticket: [`docs/v3_day3_ticket.md`](v3_day3_ticket.md)

### Schema

- [`db/migrations/008_shadow_evaluations.sql`](../db/migrations/008_shadow_evaluations.sql) — mirror of `evaluations` for `forecasts_shadow`

**Operator:** Apply after 007:

```bash
psql $DATABASE_URL -f db/migrations/008_shadow_evaluations.sql
```

### Code

- [`agent/lib/forecast_writer.py`](../agent/lib/forecast_writer.py) — `emit_forecasts(..., table=, lineage_id=)` shadow sink
- [`agent/evolution/selector.py`](../agent/evolution/selector.py) — disjoint-window backtest, top-3 → `status='shadow'`
- [`agent/evolution/shadow_runner.py`](../agent/evolution/shadow_runner.py) — cadence-bucketed live shadow runs + rate limit
- [`agent/modal_skills/shadow-runner/app.py`](../agent/modal_skills/shadow-runner/app.py) — Modal crons `*/30` + `0 */3`
- [`agent/modal_skills/forecast-evaluator/run.py`](../agent/modal_skills/forecast-evaluator/run.py) — additive `shadow_evaluations` scan
- [`agent/evolution/shadow_stats.py`](../agent/evolution/shadow_stats.py) — shadow Brier readout for Day 4
- [`agent/evolution/test_selector.py`](../agent/evolution/test_selector.py) — Day 3 acceptance tests (9 cases)

**Run:**

```bash
python agent/evolution/test_selector.py
python agent/evolution/selector.py --dry-run
python agent/evolution/shadow_runner.py --cadence-minutes 30
python -m modal deploy agent/modal_skills/shadow-runner/app.py
python -m modal deploy agent/modal_skills/forecast-evaluator/app.py
```

**Manual shadow test** (before selector has candidates):

```sql
UPDATE skill_lineage SET status = 'shadow' WHERE id = '<candidate_lineage_id>';
```

**Deploy note:** Modal workspace may be at cron limit — upgrade plan or pause a manual-only app before shadow-runner deploy (adds 2 crons).

**Out of scope this ticket:** operator review surface, promotion decision, curator orchestration (Day 4/5).

---

## v3 Day 4 — Orchestration + operator surface + closeout

**Date:** 2026-06-01 · Ticket: [`docs/v3_day4_ticket.md`](v3_day4_ticket.md)

### Code

- [`agent/evolution/budget.py`](../agent/evolution/budget.py) — $5/pass cap, Sonnet→Haiku switch at 70%
- [`agent/evolution/orchestrator.py`](../agent/evolution/orchestrator.py) — worst-K → mutate → select → shadow
- [`agent/modal_skills/curator/run.py`](../agent/modal_skills/curator/run.py) — v3 evolution pass (v2 archived)
- [`agent/evolution/proposal_review.py`](../agent/evolution/proposal_review.py) — blocked_on, diff, promote/discard
- [`agent/evolution/promotion.py`](../agent/evolution/promotion.py) — write `run.py` + print modal deploy command
- [`tools/review_proposals.py`](../tools/review_proposals.py) — list/show/promote/discard CLI
- [`agent/evolution/test_day4.py`](../agent/evolution/test_day4.py) — 11 acceptance tests

**Run:**

```bash
python agent/evolution/test_day4.py
python agent/evolution/orchestrator.py          # local evolution pass
python -m modal run agent/modal_skills/curator/app.py
python tools/review_proposals.py list
python tools/review_proposals.py show <id>
python tools/review_proposals.py promote <id>   # refuses until shadow n≥20
python -m modal deploy agent/modal_skills/curator/app.py
```

**First real run checklist** (success = clean loop, not a promotion):

1. Harness sanity + mutator acceptance fixes green
2. Migrations 006–008 applied
3. Run curator pass; verify mutator candidate OR selector clean refuse
4. No writes to live `forecasts` from evolution components
5. Pass spend ≤ $5; `promote` refuses on cold-start (`evals N/20`)

**v3 closeout deviations:** generator → v3.1; diversity penalty cut; tiered auto-approve deferred; `/agent` shadow display optional (CLI is operator surface).

**Open:** cold-start backlog until ≥20 shadow evals accumulate; Modal cron budget for curator + shadow-runner deploy.

## v3.1 — Frontend refactor (viewer-only)

**Date:** 2026-05-30

Dark commercial pass on `viewer/` only — no agent, Modal, or schema changes.

### Routes & naming (avoid confusion with evolution backlog “v3.1”)

| Old | New |
|-----|-----|
| `/` (map only) | `/` — hero + Forecasts map (stacked) |
| `/agent` | `/evolution` (redirect permanent) |
| `/about` | `/how-it-works` (redirect permanent); nav label **About** |
| — | `/disclaimer` — locked §12 + non-goals (footer link) |

### Map layers (Option C)

- **Forecasts** — model forecast polygons (default ON)
- **Detections** — all signal layers incl. `high_wind_corridor`, grids, hotspots, advisories, GDACS (default ON)
- **Atmosphere** — AIFS surface-wind velocity field only (`WindLayer` / `/api/wind`; default OFF, lazy-mount)

Layer prefs key: `envision.layers.v31`.

### Day 1 shipped

- Dark monochrome tokens, Space Grotesk + IBM Plex Mono
- Landing hero (ghost wildfire skill source, scroll to map)
- 3-layer panel, signal de-dup on forecast card + `/forecast/[id]`
- Global disclaimer banner retained

### Day 2 shipped

- **`/evolution`** — React Flow + dagre lineage tree; live Brier from `evaluations` (not backtest); shadow nodes `evaluating · N/20`; `metric-legend.tsx`
- **`/how-it-works`** — Ingest → Forecast → Evolve pipeline panels; telemetry from former `StatusHeader` queries; data sources relocated from old `/about`
- **`/disclaimer`** — §12 verbatim + non-goals only

**Deps added:** `@xyflow/react`, `@dagrejs/dagre`.

**Deploy:** Vercel Root Directory `viewer/`; `DATABASE_URL` required in all envs.
