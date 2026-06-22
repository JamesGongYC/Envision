# METHODS

How Envision works, end to end.

## 1. Data flow

```
Open data sources                       Authoritative ground truth
─────────────────                       ─────────────────────────
NASA FIRMS  ─┐                                  GDACS
NWS Alerts  ─┼──► signals                        │
NHC         ─┘                                   ▼
                  │                          ground_truth
                  ▼
                detectors
                  │
                  ▼
                forecasts ◄──┐
                  │           │
                  ▼           │
              evaluator ──────┘
                  │
                  ▼
              evaluations ──► Curator ──► skill_edit_proposals
                                              │
                                              ▼
                                         (human approval gate)
                                              │
                                              ▼
                                         updated skill code on disk
```

## 2. Ingestion

All ingestion runs on **Modal** (`agent/modal_skills/`). Historical Hermes copies are archived under `agent/_archive/skills/`.

| Skill | Source | Cadence | Writes |
|---|---|---|---|
| `firms-active-fires` | NASA FIRMS VIIRS + MODIS (global) | 30 min (Modal) | `signals` (hotspot) |
| `nws-fire-alerts` | NWS Alerts API | 30 min (Modal) | `signals` (fire_warning) |
| `nhc-cyclones` | NHC CurrentStorms.json | 3 h (Modal) | `signals` (cyclone_advisory) |
| `open-meteo-fire-weather` | Open-Meteo forecast API | 3 h (Modal) | `signals` (fire_weather) |
| `jtwc-cyclones` | JTWC ATCF bulletins | 6 h (Modal) | `signals` (cyclone_advisory) |
| `ecmwf-fire-weather-derived` | ECMWF Open Data HRES GRIB | 12 h (Modal) | `signals` (fire_weather_grid) |
| `aifs-cyclone-feature` | ECMWF Open Data AIFS GRIB | 12 h (Modal) | `signals` (cyclone_feature) |
| `aifs-fire-weather-grid` | ECMWF Open Data AIFS GRIB | 12 h (Modal) | `signals` (fire_weather_grid) |
| `aifs-high-wind-corridor` | ECMWF Open Data AIFS GRIB | 12 h (Modal) | `signals` (high_wind_corridor) |
| `aifs-heavy-precipitation-band` | ECMWF Open Data AIFS GRIB | 12 h (Modal) | `signals` (heavy_precipitation_band) |
| `aifs-heat-dome` | ECMWF Open Data AIFS GRIB | 12 h (Modal) | `signals` (heat_dome) |
| `gdacs-ground-truth` | GDACS GeoRSS | 6 h | `ground_truth` |

Every signal is dedup'd via a payload hash trigger (migration 002) and stored in 2D WGS84.

### ECMWF derived fire weather (v2 Day 4)

Modal skill `ecmwf-fire-weather-derived` downloads HRES Open Data at **+24h** for four variables: 2m temperature (`2t`), 2m dewpoint (`2d`), 10m wind components (`10u`/`10v`), and 24h precipitation (`tp`). Per 0.25° grid cell:

```
score = (T > 30°C) + (dewpoint_depression > 15°C) + (wind > 6.9 m/s) + (precip < 1 mm)
```

Cells with `score >= 3` (configurable via `ECMWF_FW_THRESHOLD`) are grouped into contiguous polygons via connected-component labeling and `shapely.unary_union`. Each polygon becomes one `signals` row: `source='ecmwf_open_data'`, `signal_type='fire_weather_grid'`. The signal `timestamp` is the **forecast valid time** (run + 24h), not the model run time.

`wildfire-risk-elevated` (v2.5) intersects clusters with `fire_warning` and `fire_weather_grid` polygons from `nws_alerts`, `ecmwf_open_data`, and `aifs`.

### AIFS signals (v2 Day 5)

Five independent Modal skills read ECMWF **AIFS** Open Data (`model=aifs-single`) and write upstream **`signals`** with `source='aifs'`. This is substrate data for downstream detection (post-v2) and future agentic consumption — not forecast-table output. AIFS skills are excluded from the v3 mutation surface (`aifs-*` skill IDs).

Shared code: [`agent/modal_skills/_shared/`](../agent/modal_skills/_shared/) (`aifs_common.py`, `grid.py`).

| Modal skill | signal_type | Extraction |
|---|---|---|
| `aifs-cyclone-feature` | `cyclone_feature` | MSLP local minima (<1005 hPa) + 850 hPa relative vorticity (from u/v); track across +0/+24/+48/+72h within 300 km; ≥2h persistence; Point geometry |
| `aifs-fire-weather-grid` | `fire_weather_grid` | Same 0–4 fire weather score as ECMWF HRES at +24h; polygon aggregates (dual provenance with `ecmwf_open_data`) |
| `aifs-high-wind-corridor` | `high_wind_corridor` | 10m wind > 16.7 m/s at +24h; polygon aggregates |
| `aifs-heavy-precipitation-band` | `heavy_precipitation_band` | 24h `tp` > 50 mm at +24h; polygon aggregates |
| `aifs-heat-dome` | `heat_dome` | `2t` > 35°C at ≥3 of 4 steps (+0/+24/+48/+72h); polygon aggregates |

**Disable one signal type:** stop that Modal app (`modal app stop <app-name>`) without affecting the others.

**Cadence:** staggered within 05:00–05:25 and 17:00–17:25 UTC (5–25 min offsets to reduce concurrent ECMWF downloads).

Note: AIFS Open Data does not expose `vo` at 850 hPa directly; cyclone vorticity is computed from `u`/`v` at 850 hPa.

## 3. Detection

Four Modal detection apps (`agent/modal_skills/`) convert raw signals into probabilistic forecasts. Each exposes **`run(now, db) -> list[Forecast]`** (pure detection); persistence is **`emit_forecasts()`** in [`agent/lib/forecast_writer.py`](../agent/lib/forecast_writer.py) (not mutation surface — v2 §12). Each writes one or more `forecasts` rows per cycle, with `probability` capped at 0.85 by a database `CHECK` constraint.

| Skill | Logic |
|---|---|
| `wildfire-risk-elevated` | DBSCAN cluster (eps=10km, min_samples=5) on last-24h FIRMS hotspots; cluster geometry intersected with `fire_warning` or `fire_weather_grid` from NWS, ECMWF, or AIFS. |
| `wildfire-rapid-growth` | 50km grid cell in EPSG:3857; hotspot count must grow >50% day-over-day for 2 consecutive days. |
| `typhoon-intensifying` | NHC bulletin central pressure dropping >5 hPa over a ~12h window (±2h tolerance). |
| `typhoon-landfall-imminent` | Forward-extrapolated 72h cone from heading + speed, buffered with growing radii (40km → 200km), intersected with GeoNames cities of pop ≥ 10⁴. |

Forecast geometry is GeoJSON polygon. **Reasoning (v2.5):** after `TraceBuilder` is populated, locked prompts in `agent/lib/reasoning_prompts.py` are filled from trace fields; `generate_reasoning()` calls Claude Sonnet (`max_tokens=200`) and falls back to templated `build_reasoning()` on API failure. Validity windows are 24h for wildfires, 48–72h for cyclones.

## 4. Evaluation

A nightly evaluator skill matches expired forecasts against GDACS ground-truth events:

- Disaster class must match (with aliases for GDACS code variants)
- Event must have occurred between `valid_from - 6h` and `valid_until + 12h`
- Geometries must intersect (`ST_Intersects`)

Each evaluation writes one row with `outcome ∈ {'hit', 'false_positive'}` and `brier_contribution = (probability − outcome_value)²`. `outcome_value` is 1 for hit, 0 for false positive. `miss` is a defined value but not computed in v1 because we don't generate low-probability forecasts.

The evaluator waits 12h past `valid_until` before scoring, so GDACS has time to publish.

**Operator-facing definitions** (also shown as hover tooltips on `/agent` skill cards):

- **Brier score:** calibration metric for probabilistic forecasts. Lower is better. A perfect skill scores 0; random guessing scores around 0.25.
- **Hit:** forecast issued and a matching ground-truth event occurred within the validity window.
- **False positive:** forecast issued but no matching ground-truth event occurred within the validity window.

## 4b. Traces (v2 Day 6)

Detection skills write structured **`forecasts.trace`** JSONB on every new forecast. The Modal Curator writes **`skill_edit_proposals.curator_trace`** on every new proposal. These are the v3 mutator's primary reading material for understanding *why* a skill made a given choice.

- **Schema:** [`docs/TRACES.md`](TRACES.md) (authoritative per-skill shapes)
- **Builder:** [`agent/lib/trace_builder.py`](../agent/lib/trace_builder.py) — `TraceBuilder` (detection), `CuratorTraceBuilder` (curator)
- **Soft cap:** 12 KB serialized JSON; sets `_truncated: true` when trimming
- **Hard cap:** 16 KB (`trace_size_cap` CHECK on `forecasts.trace`)
- **Validation:** `python tools/validate_traces.py` (read-only Neon spot-check)
- **Backfill:** none — older rows keep empty `{}`

Modal detection and curator apps mount `agent/lib/` at `/root/agent_lib` on the container image.

## 5. Evolution loop (v3)

Once daily (04:00 UTC), the Curator orchestrates the **automatic** half of the evolution loop. The **operator** half is manual via `tools/review_proposals.py`.

**Automatic path** (halted by `ENVISION_CURATOR_ENABLED=false`):

1. **Pick worst-K** (K=3) detection skills by 14-day live Brier; tie-break by version spread.
2. **Mutate** — Sonnet/Haiku rewrites the skill surface; seven-stage validation (AST, signature lock, no-persistence, signal catalog, import allowlist, sandbox).
3. **Select** — cross-window backtest on ≥3 disjoint GT windows with `occurred_at >= BACKTEST_EPOCH` (2026-06-04 UTC); windows starting before that epoch are rejected. Candidate must beat parent by ≥0.03 Brier in **every** window; top-3 advance to `status='shadow'`.
4. **Shadow run** — generic shadow-runner cron executes candidates into `forecasts_shadow` (public map never sees these).
5. **Shadow evaluate** — forecast-evaluator writes `shadow_evaluations`.

**Gates on the automatic path:** kill switch; validation pipeline; cross-window selection; shadow rate limit (50/tick); $5/pass LLM budget (Sonnet→Haiku fallback, then stop).

**Human path** (never automated):

```
tools/review_proposals.py list / show
        │
        ▼
tools/review_proposals.py promote   ← requires shadow n≥20 + Brier beat parent
        │
        ▼
operator: python -m modal deploy agent/modal_skills/<skill>/app.py
```

`promote` writes `agent/modal_skills/<skill>/run.py` and updates DB lineage — but **does not** run Modal deploy. No evolution cron writes production files.

**Deferred:** diversity penalty in selector, tiered auto-approve for parametric edits.

### v3.2 — LLM status layer + generator

All Anthropic HTTP traffic routes through [`agent/lib/llm_client.py`](../agent/lib/llm_client.py) (`mutator`, `generator`, `narrator`, `probe`). Each attempt logs one row to `llm_call_log` (migration 011) with `call_group_id`, `request_id`, and token counts.

**Health gate** ([`agent/lib/health_gate.py`](../agent/lib/health_gate.py)): pre-flight probe at curator entry; rolling 10-minute 529-rate abort mid-cycle (`min_samples=5`, threshold 0.5). Independent of `ENVISION_CURATOR_ENABLED`.

**Generator** ([`agent/evolution/generator.py`](../agent/evolution/generator.py)): operator-seeded via `ENVISION_GENERATOR_ENABLED` + `ENVISION_GENERATOR_DISASTER_CLASS` (+ optional `ENVISION_GENERATOR_PROMPT`). Fires only when uncovered signal types exist for that class — not on the daily worst-K tick. Writes `generation_method='generated'`, `parent_skill_id=NULL` lineage rows; `app.py` scaffold stored in `skill_md` until human promote.

**Generated promotion bar (A1):** `shadow_brier < base_rate_brier − 0.03` at N≥20 — absolute base-rate comparison, no parent incumbent. Mutant path unchanged (parent 14d Brier).

**Load control (A2↔A3):** generator is condition-gated and operator-seeded; no per-parent child cap.

Implementation: [`agent/evolution/orchestrator.py`](../agent/evolution/orchestrator.py), [`agent/evolution/generation_trigger.py`](../agent/evolution/generation_trigger.py), [`agent/modal_skills/curator/run.py`](../agent/modal_skills/curator/run.py). v2 param-tweak curator archived at `_archived_v2_param_tweak.py`.

**Ground truth dedup:** GDACS events upsert on `(source, payload.eventid)`; advisory updates refresh payload/geometry without duplicating rows or moving `occurred_at`. Rows without `eventid` keep md5 payload dedup from migration 002.

**Backtest misses:** `_score_window` counts unmatched ground-truth rows per window (not per-forecast false positives). Run `tools/purge_seed_data.py` before applying migration 009; record `wildfire_rapid_growth` 14d Brier before/after purge in deploy notes.

## 6. Approval workflow

```
curator → mutate → validate → select → shadow (forecasts_shadow)
                │
                ▼
       tools/review_proposals.py list    ← blocked_on reasons visible
                │
                ▼
       tools/review_proposals.py show <id>   ← diff + backtest + shadow metrics
                │
                ▼
       tools/review_proposals.py promote <id>   ← human gate; writes run.py
                │
                ▼
       operator: modal deploy (manual)
```

`discard` archives rejected candidates. `approve`/`reject` are deprecated aliases for `promote`/`discard`.

## 7. Probability cap

`forecasts.probability` has a `CHECK (probability >= 0.0 AND probability <= 0.85)` constraint. Any skill that tries to write a higher value raises a database error. This is the hard ceiling on confidence.

## 8. Kill switch

**Modal curator:** Set `ENVISION_CURATOR_ENABLED=false` in the Modal secret `envision-neon`. Re-create the secret with all keys (`DATABASE_URL`, `ANTHROPIC_API_KEY`, `ENVISION_CURATOR_ENABLED`):

```sh
python -m modal secret create envision-neon \
  DATABASE_URL='...' ANTHROPIC_API_KEY='...' ENVISION_CURATOR_ENABLED=false
```

**Legacy / local:** `ENVISION_CURATOR_ENABLED=false` in `~/.hermes/.env` still applies to any Hermes-process curator copy (retired Day 4).

When disabled, the Curator exits immediately at the top of its cycle. It does not stop:
- Detection skills from running
- The evaluator from running
- The viewer from displaying data
- Pending proposals from being reviewed

To halt detection, stop the Modal app (`modal app stop <name>`) or pause its schedule in the Modal dashboard. To halt the viewer, undeploy from Vercel.

## 9. Known limitations

- **No baseline twin.** Plan §8 called for a frozen `is_baseline=true` copy of every skill running in parallel as a regression floor. This was cut for MVP. If a promoted mutation makes a skill worse, only manual rollback recovers.
- **No recency weighting.** Plan §8 called for Brier scores weighted by recency. We use a flat 14-day mean.
- **No JMA.** Plan §11 cut JMA Western Pacific ingestion. NHC covers Atlantic and East Pacific only.
- **NHC cone is approximated.** Real NHC cones come from ensemble track-error statistics; we extrapolate from heading + speed buffered with rough radii.
- **GHSL substitute.** Plan §7 called for the GHSL population raster; we substituted GeoNames cities with pop ≥ 10⁴.
- **Reasoning fallback.** Detection uses Sonnet with templated fallback; empty or failed LLM calls still produce operator-readable text.
- **Probability calibration not validated.** No published calibration plots. Brier scores accumulate but the threshold for "well-calibrated" is not formally defined for v1.

## 10. Operational defaults

| Setting | Value | Where |
|---|---|---|
| Ingestion cadence (FIRMS, NWS) | 30 min | Modal |
| Ingestion cadence (NHC) | 3 h | Modal |
| Ingestion cadence (GDACS) | 6 h | Modal |
| Detection cadence (wildfire) | 30 min | Modal |
| Detection cadence (typhoon) | 3 h | Modal |
| Evaluator cadence | 24 h | Modal |
| Curator cadence | 24 h | Modal cron (04:00 UTC) |
| ECMWF derived cadence | 12 h | Modal cron (04:00 + 16:00 UTC) |
| AIFS skills cadence | 12 h | Modal crons (05:00–05:25 + 17:00–17:25 UTC) |
| Probability cap | 0.85 | DB constraint |
| Evaluation grace period | 12 h after valid_until | evaluator |
| Brier window | 14 days | curator |
| Min evaluations for curation | 5 | curator |
| ISR revalidation (viewer) | 60 s | Next.js |
