# Trace JSONB schemas (authoritative)

Structured trace columns on `forecasts` and `skill_edit_proposals`. The database stores JSONB only — shape is documented here and enforced in application code via `TraceBuilder` / `CuratorTraceBuilder` ([`agent/lib/trace_builder.py`](../agent/lib/trace_builder.py)).

**Purpose:** v3's mutator reads traces to understand *why* skills succeed or fail, not only Brier scores. Humans may inspect traces in Day 8 viewer surfaces.

**Backfill:** None. Existing rows keep `trace='{}'` / `curator_trace='{}'`. Only new writes populate traces.

**Ingestion:** No trace column on `signals`. Ingestion skills do not write traces in v2.

---

## Size limits

| Layer | Limit |
|-------|-------|
| DB hard cap | `octet_length(trace::text) <= 16384` on `forecasts.trace` (`trace_size_cap` CHECK) |
| Application soft cap | 12_288 bytes serialized JSON (`json.dumps`, default separators) |
| Headroom | 4 KB for serialization variance |

If serialized size exceeds 12 KB, `TraceBuilder` / `CuratorTraceBuilder` truncates deterministically and sets top-level `_truncated: true`.

### Truncation order (deterministic)

**Detection (`TraceBuilder`):** repeatedly drop/truncate the largest list-valued field in this order until under 12 KB:

1. `intermediate.growing_cells`
2. `intermediate.selected_clusters`
3. `intermediate.populated_places_in_cone`
4. `intermediate.pressure_history`
5. `geometry_steps` (shorten arrays, keep step names)
6. `inputs.active_storms` (cap to 20 entries)

**Curator (`CuratorTraceBuilder`):**

1. `llm_response_full` (truncate string tail first)
2. `brier_stats_observed` (never dropped if possible)
3. `ast_validation` (never dropped)

---

## Do not include

- Raw GeoJSON coordinate arrays or full polygons
- Full `signals.payload` blobs (use signal UUIDs and key scalar fields only)
- Full LLM prompts (curator: `llm_input_prompt_hash` only)
- Secrets or API keys

Use bbox tuples `[min_lon, min_lat, max_lon, max_lat]`, counts, centroids, and named geometry-step summaries instead.

---

## `run(now, db)` contract

Every skill script exposes:

```python
def run(now: datetime, db: Connection) -> ...:
    ...
```

Detection skills use `now` as a query cutoff (`AND timestamp <= %s`). Traces record `now` as ISO8601 UTC.

---

## Detection traces (`forecasts.trace`)

### Required top-level keys (all detection skills)

| Key | Type | Description |
|-----|------|-------------|
| `now` | string | ISO8601 UTC — parametrized cutoff passed to `run()` |
| `inputs` | object | What was read (counts, storm lists, filters) |
| `intermediate` | object | In-memory computation results |
| `geometry_steps` | array | Named steps: `{name, ...summary fields}` |
| `probability_components` | object | Breakdown of probability calculation |
| `_truncated` | boolean | Optional; `true` if soft-cap truncation ran |

---

### `wildfire_rapid_growth`

| Section | Required fields |
|---------|-----------------|
| `inputs` | `hotspot_count_last_24h` (int), `hotspot_count_prior_24h` (int) — global counts in 72h window |
| `intermediate` | `growing_cells`: `[{cell_id, growth_ratio, days_consecutive}]`, `threshold_met_count` (int) |
| `geometry_steps` | One step `cell_boundaries_emitted`: `{bboxes: [[min_lon, min_lat, max_lon, max_lat], ...]}` |
| `probability_components` | `growth_factor` (float), `persistence_factor` (float), `base` (float) |

`cell_id`: string index for the grid cell in this run. `growth_ratio`: `day_t / max(1, day_t1)`. `days_consecutive`: `2` when rule fires.

---

### `typhoon_intensifying`

| Section | Required fields |
|---------|-----------------|
| `inputs` | `active_storms`: `[{storm_id, name, source}]` |
| `intermediate` | `pressure_history`: `[{storm_id, pressures_hpa, timestamps}]`, `pressure_drops`: `[{storm_id, drop_hpa, period_h}]` |
| `geometry_steps` | `storm_positions`: `[{storm_id, lat, lon}]` |
| `probability_components` | `pressure_drop_magnitude` (float), `recency_factor` (float), `base` (float) |

`source`: signal source string (e.g. `nhc`, `jtwc`). Timestamps ISO8601 strings.

---

### `typhoon_landfall_imminent`

| Section | Required fields |
|---------|-----------------|
| `inputs` | `active_storms` (int count), `populated_places_queried_count` (int — rows in `populated_places` with pop ≥ threshold) |
| `intermediate` | `cone_polygon_summary`: `{bbox, area_km2}`, `intersected_population_total` (int), `populated_places_in_cone`: top 5 by population `[{place_id, population, distance_km}]` |
| `geometry_steps` | `cone_construction`: `{heading_deg, speed_kmh, buffer_km_at_horizons: [[hour, km], ...]}` |
| `probability_components` | `population_at_risk` (float), `time_to_landfall_h` (float — forecast horizon used), `base` (float) |

`place_id`: GeoNames `geonameid`. `distance_km`: great-circle distance from place to current storm center.

---

### `wildfire_risk_elevated`

| Section | Required fields |
|---------|-----------------|
| `inputs` | `hotspot_count` (int), `polygon_count_nws` (int), `polygon_count_ecmwf` (int; `0` until v2.5) |
| `intermediate` | `clusters_found` (int), `selected_clusters`: `[{cluster_id, size, centroid_lat_lon, intersecting_polygon_id}]` |
| `geometry_steps` | `dbscan_params`: `{eps_km, min_samples}`, `cluster_bboxes`: `[[min_lon, min_lat, max_lon, max_lat], ...]` |
| `probability_components` | `cluster_size_factor` (float), `polygon_overlap_factor` (float), `base` (float) |

`intersecting_polygon_id`: first matching NWS alert signal UUID. `centroid_lat_lon`: `[lat, lon]`.

---

## Curator trace (`skill_edit_proposals.curator_trace`)

### Required top-level keys

| Key | Type | Description |
|-----|------|-------------|
| `brier_stats_observed` | object | Per-skill stats fed to the LLM |
| `ast_validation` | object | `{passed: bool, warnings: [str], errors: [str]}` |
| `_truncated` | boolean | Optional; `true` if soft-cap truncation ran |

### Optional keys

| Key | Type | Description |
|-----|------|-------------|
| `llm_input_prompt_hash` | string | First 16 hex chars of `sha256(user_prompt_utf8)` |
| `llm_response_full` | string | Serialized Claude response text (truncated if oversized) |
| `rejection_reasons` | array | Empty `[]` on successful insert; pre-insert rejections do not create rows |

### `brier_stats_observed` shape

Map keyed by `skill_id` (the skill being edited in this proposal):

```json
{
  "wildfire_rapid_growth": {
    "brier_14d": 0.21,
    "eval_count": 42,
    "hits": 12,
    "false_positives": 4,
    "brier_30d": 0.23,
    "eval_count_30d": 80
  }
}
```

`brier_30d` / `eval_count_30d`: optional aggregates over 30 days when available.

---

## Examples

**Detection (minimal):**

```json
{
  "now": "2026-05-30T12:00:00+00:00",
  "inputs": {"hotspot_count_last_24h": 120, "hotspot_count_prior_24h": 95},
  "intermediate": {"growing_cells": [{"cell_id": "0", "growth_ratio": 1.8, "days_consecutive": 2}], "threshold_met_count": 1},
  "geometry_steps": [{"name": "cell_boundaries_emitted", "bboxes": [[-120.5, 35.1, -119.8, 35.9]]}],
  "probability_components": {"base": 0.45, "growth_factor": 0.12, "persistence_factor": 0.08}
}
```

**Curator:**

```json
{
  "brier_stats_observed": {
    "wildfire_rapid_growth": {"brier_14d": 0.21, "eval_count": 42, "hits": 12, "false_positives": 4}
  },
  "ast_validation": {"passed": true, "warnings": [], "errors": []},
  "llm_input_prompt_hash": "a1b2c3d4e5f67890",
  "llm_response_full": "...",
  "rejection_reasons": []
}
```
