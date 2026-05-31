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

Four Modal detection apps (`agent/modal_skills/`) convert raw signals into probabilistic forecasts. Each writes one or more `forecasts` rows per cycle, with `probability` capped at 0.85 by a database `CHECK` constraint.

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

## 5. Curation

Once daily, the Curator skill reads 14-day Brier statistics per detection skill and proposes parameter adjustments via Claude (`claude-sonnet-4-6`).

**Runtime:** Curator runs on **Modal** (`agent/modal_skills/curator/`), scheduled 04:00 UTC. Detection skills are separate Modal apps; Hermes runtime retired v2.5.

**Scope is enforced by prompt, not by sandbox.** The Curator is told it may only change numeric constants and templated reasoning strings — not function signatures, control flow, imports, SQL, or schema. The output is validated for Python syntax but not for semantic safety. Human review at promotion time is the real safety bar.

Every proposal lands in `skill_edit_proposals` with `status='pending'` and a populated `curator_trace` (Brier stats observed, AST validation, prompt hash, LLM response text). The Curator never writes to skill files on disk.

## 6. Approval workflow

```
curator → skill_edit_proposals (status='pending')
                │
                ▼
       tools/review_proposals.py list
                │
                ▼
       tools/review_proposals.py show <id>     ← human reads the diff
                │
                ▼
       tools/review_proposals.py approve <id>  ← row marked approved
                │
                ▼
       operator manually copies the proposed_code into the live
       skill file, increments the version, restarts cron.
```

The `approve` command does not overwrite files. This is intentional. The CLI marks the row's status and prints the deployment path; the operator does the file replacement manually. Rollback is also manual: revert the script, decrement the version.

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
