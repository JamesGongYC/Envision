# v2 Day 6 — Trace Instrumentation

**Scope.** Populate the `trace` JSONB columns added by migration 004 (Day 1). Update all 4 detection skills to write per-forecast traces; update the curator (Modal) to write per-proposal `curator_trace`. Lock down `docs/TRACES.md` from sketch to authoritative schema. Build a shared `TraceBuilder` helper so all skills emit consistent shape. This is the v3 dependency that lets the future mutator reason about why skills succeed or fail — the most important day of v2 for v3 readiness.

## Canonical context

Attach via `@`:

- `@docs/envision_plan.md`
- `@docs/v2_plan.md` (§5 trace JSONB schemas)
- `@docs/v3_plan.md` §11 (dependency contract — traces are v3's reading material)
- `@docs/v2_day1_ticket.md` (TRACES.md was sketched there)
- `@docs/PROGRESS.md`
- `@db/schemas.py`
- `@db/migrations/004_v2_additions.sql`
- `@docs/TRACES.md` (current sketch; this ticket finalizes)

## Pre-decided

**Inherited:** `run(now, db)` signature; `ST_Force2D(...)` for geometry; per-skill smoke test before next.

**New for Day 6:**

1. **Traces only on `forecasts` and `skill_edit_proposals`.** Migration 004 added trace columns to those two tables only. Signals have no trace column; ingestion skills do not write traces. (Signal-level provenance is a v2.1+ design question.)

2. **16KB hard cap is DB-enforced.** `forecasts.trace_size_cap CHECK (octet_length(trace::text) <= 16384)`. Skill code must respect this. Truncation policy: if a trace exceeds 12KB, truncate offending fields and set `_truncated=true` at the top level. The 4KB headroom is for trace-builder serialization variance.

3. **Schema first, code second.** Lock `docs/TRACES.md` to precise per-skill trace shapes before any skill code is touched. v3's mutator will read these — schema drift between skills costs the mutator real reasoning effort. Cursor must read the finalized TRACES.md before refactoring any skill.

4. **Required top-level keys per v2_plan §5:** `now`, `inputs`, `intermediate`, `geometry_steps`, `probability_components`. Required for every detection-skill trace. Per-skill extensions allowed via additional keys.

5. **Shared `TraceBuilder` helper.** All detection skills construct traces through a single helper at `agent/lib/trace_builder.py`. Helper enforces required keys, applies the truncation rule, produces the final JSONB. Pays off in v3 — when the generator/mutator produces new skill code, it can be told "use TraceBuilder, here are its methods" and get consistent emission for free.

6. **Curator trace schema.** Required keys: `brier_stats_observed` (map of skill_id → recent Brier stats), `ast_validation` (passed bool + warnings list). Optional: `llm_input_prompt_hash`, `llm_response_full` (truncated if oversized), `rejection_reasons` (list).

7. **Backfill policy: none.** Existing forecast/proposal rows keep `trace='{}'`. Only new writes populate. Per v2_plan §8 explicit guidance.

8. **Skill order (simpler → complex).** Establish trace pattern on the simplest skills first, apply learned shape to the complex ones:
   1. `wildfire-rapid-growth` (single signal source, grid arithmetic)
   2. `typhoon-intensifying` (single source, time-series check)
   3. `typhoon-landfall-imminent` (cone × populated places)
   4. `wildfire-risk-elevated` (DBSCAN + polygon intersection — most complex)
   5. `curator` (Modal-resident; different shape from detection traces)

## Deliverables

### D1 — Lock down `docs/TRACES.md`

Replace the Day-1 sketch with authoritative per-skill schemas. For each of the 5 components above, document:

- The 5 required top-level keys (`now`, `inputs`, `intermediate`, `geometry_steps`, `probability_components` for detection; `brier_stats_observed`, `ast_validation` for curator).
- Per-skill required sub-fields per pre-decided (specific examples below).
- The 12KB truncation threshold and `_truncated=true` marker convention.
- A "do not include" list: raw geometry coordinates (use shape summaries), full payloads from signals (use IDs + key fields), full LLM prompts (use hash).

**Per-skill schema specifics to document:**

- **`wildfire-rapid-growth`:**
  - `inputs`: `hotspot_count_last_24h`, `hotspot_count_prior_24h`
  - `intermediate`: `growing_cells: [{cell_id, growth_ratio, days_consecutive}]`, `threshold_met_count`
  - `geometry_steps`: `cell_boundaries_emitted` (list of bbox tuples, not full polygons)
  - `probability_components`: `growth_factor`, `persistence_factor`

- **`typhoon-intensifying`:**
  - `inputs`: `active_storms: [{storm_id, name, source}]`
  - `intermediate`: `pressure_history: [{storm_id, pressures_hpa, timestamps}]`, `pressure_drops: [{storm_id, drop_hpa, period_h}]`
  - `geometry_steps`: `storm_positions: [{storm_id, lat, lon}]`
  - `probability_components`: `pressure_drop_magnitude`, `recency_factor`

- **`typhoon-landfall-imminent`:**
  - `inputs`: `active_storms`, `populated_places_queried_count`
  - `intermediate`: `cone_polygon_summary: {bbox, area_km2}`, `intersected_population_total`, `populated_places_in_cone: [{place_id, population, distance_km}]` (top 5 by population)
  - `geometry_steps`: `cone_construction: {heading_deg, speed_kmh, buffer_km_at_horizons}`
  - `probability_components`: `population_at_risk`, `time_to_landfall_h`

- **`wildfire-risk-elevated`:**
  - `inputs`: `hotspot_count`, `polygon_count_nws`, `polygon_count_ecmwf` (when v2.5 generalization ships; for now NWS only)
  - `intermediate`: `clusters_found`, `selected_clusters: [{cluster_id, size, centroid_lat_lon, intersecting_polygon_id}]`
  - `geometry_steps`: `dbscan_params: {eps_km, min_samples}`, `cluster_bboxes`
  - `probability_components`: `cluster_size_factor`, `polygon_overlap_factor`

- **`curator`:**
  - `brier_stats_observed`: `{skill_id: {brier_14d, eval_count, brier_30d, ...}}`
  - `ast_validation`: `{passed: bool, warnings: [str], errors: [str]}`
  - `llm_input_prompt_hash`: `sha256(prompt)[:16]`
  - `llm_response_full`: full Claude response, truncated to fit
  - `rejection_reasons`: `[str]` if proposal was rejected pre-insert

**Acceptance:** TRACES.md committed; reviewable for each skill before code touches.

### D2 — `agent/lib/trace_builder.py`

Net-new shared helper. Single class `TraceBuilder` with methods:

```python
class TraceBuilder:
    def __init__(self, now: datetime, skill_id: str): ...
    def set_inputs(self, **kwargs): ...
    def set_intermediate(self, **kwargs): ...
    def add_geometry_step(self, name: str, value: dict): ...
    def set_probability_components(self, **kwargs): ...
    def build(self) -> dict:
        """Returns dict ready to serialize as JSONB. 
        Enforces required keys; truncates if >12KB; sets _truncated=true."""
```

Plus a `CuratorTraceBuilder` variant with the different shape.

Sync to runtime via `tools/sync_skills.py`? No — `agent/lib/` isn't a skill, it's a library. Detection skills import it directly. **For Hermes-resident detection skills, this means `agent/lib/` needs to be on PYTHONPATH at runtime.** Two options:
- (a) Copy `agent/lib/trace_builder.py` into each skill's `scripts/` dir during sync — duplicative but self-contained.
- (b) Configure Hermes to add `agent/lib/` to PYTHONPATH at skill execution time.

Lean (a) — pragmatic, no Hermes-config wrestling. `sync_skills.py` learns to also copy `agent/lib/*.py` into each detection skill's directory. (Curator on Modal: include `agent/lib/` in the Modal image via `add_local_dir`.)

**Acceptance:** unit tests in `agent/lib/test_trace_builder.py` cover required-key enforcement, truncation behavior, and `_truncated=true` marker.

### D3 — Refactor detection skills (per-skill cadence)

Apply to each skill **one at a time**, per the order in pre-decided (8). Per skill:

- Import `TraceBuilder` (after `sync_skills.py` enhancement copies it in).
- Throughout the skill's computation, accumulate trace data: input counts, intermediate results, geometry construction steps, probability components.
- At forecast-emission time, call `builder.build()` to get the JSONB dict.
- Insert into `forecasts.trace` column alongside other fields.
- Don't break existing `run(now, db)` contract or geometry-insert pattern.

**Per-skill smoke test (mandatory between skills):**

```bash
python tools/sync_skills.py --apply
python ~/.hermes/skills/<skill_id>/scripts/<...>.py
# Then in Neon:
SELECT id, skill_id, jsonb_pretty(trace) FROM forecasts 
WHERE skill_id = '<...>' ORDER BY issued_at DESC LIMIT 1;
```

Verify the trace contains all 5 required keys, has reasonable values, is well-formed JSON. If trace exceeds 16KB on a real run, the DB rejects the insert → fix the truncation before moving on.

If a skill fails smoke, stop and report. Pattern established by the first skill propagates.

### D4 — Curator trace (Modal)

Update `agent/modal_skills/curator/run.py` to construct `CuratorTraceBuilder` per proposal and insert into `skill_edit_proposals.curator_trace`.

- Modal image must include `agent/lib/trace_builder.py`. Add via `image.add_local_dir(..., "agent/lib")` in `app.py`.
- Deploy: `modal deploy agent/modal_skills/curator/app.py`.
- Smoke test: `modal run agent/modal_skills/curator/app.py` and check `skill_edit_proposals.curator_trace` for the new row.

**Acceptance:** curator's next proposal carries a populated `curator_trace`.

### D5 — Trace validation script

Net-new at `tools/validate_traces.py`. Read-only against DB. Per (skill_id, last 24h forecasts):

- Sample 5 forecasts per skill.
- Check trace is valid JSON.
- Check required top-level keys present.
- Check trace size ≤ 16KB (should never fail since DB enforces, but useful diagnostic).
- Check `_truncated=true` rate per skill (high rate → trace design is bloated).
- Report counts of pathologies.

Same shape as `tools/validate_signals.py` from Day 3.

**Acceptance:** script runs, reports pass/fail per skill.

### D6 — Documentation

- `docs/METHODS.md` — append section on traces: purpose (v3 mutator's reading material), schema, truncation policy, where to look (`forecasts.trace`, `skill_edit_proposals.curator_trace`).
- `docs/PROGRESS.md` — Day 6 closeout: traces populated across all 4 detection skills + curator; TRACES.md authoritative; v3 prerequisite #2 (per v3_plan §11) satisfied.

## Out of scope

- Trace population for *ingestion* skills (no trace column on `signals`) — v2.1+ design question.
- Backfill of existing rows — v2_plan §8 says no, leave as `'{}'`.
- Frontend trace display — Day 8.
- Aggregating older traces if storage becomes an issue — v3+.
- Trace versioning (schema evolution tracking) — v3+; for now, schema changes are breaking.

## Notes / gotchas

- **Truncation must be deterministic.** If a field is truncated, do it the same way every run — same ordering of keys, same cut points. v3 mutator may compare traces across runs; nondeterministic truncation makes that noisier than it needs to be.
- **`llm_response_full` is the most likely truncation victim.** Claude's responses for skill-edit proposals can run 4–8KB depending on the skill's source size. Combined with `brier_stats_observed` and AST output, can push past 12KB. Truncate `llm_response_full` first; preserve `brier_stats_observed` and `ast_validation` integrally.
- **Geometry in traces is summary, not full.** Don't include raw coordinate arrays; use bbox or area summaries. v3 mutator does its own geometry reasoning; the trace's job is "why did this skill make these choices," not "what are the polygons."
- **JSON-safe values only.** Numpy floats need `.item()` or `float()` conversion before serialization. Datetimes need `.isoformat()`. `TraceBuilder` should handle these conversions internally so skills can pass raw values.
- **`agent/lib/` propagation.** The two-platform model means `agent/lib/trace_builder.py` must arrive at both Hermes runtime (via enhanced `sync_skills.py`) and Modal image (via `add_local_dir`). If either is missing, that skill's traces fail. Sync_skills.py change is small; the Modal change is one line in `curator/app.py`.
- **Existing rows untouched.** `trace='{}'` on old rows is fine — v3 mutator will see those as "no information available, fall back to Brier history only." Don't worry about old rows.
- **Trace size monitoring.** D5's validation script reports `_truncated=true` rate per skill. If any skill exceeds 5% truncation rate, the trace design needs trimming.

## Done definition

- D1–D6 acceptance criteria met.
- TRACES.md committed as authoritative.
- All 4 detection skills emit populated traces; verified via Neon spot-check.
- Curator's next proposal carries `curator_trace`.
- `tools/validate_traces.py` passes for all 5 components.
- v3 dependency contract item #2 (per v3_plan §11) marked satisfied.
- `PROGRESS.md` "v2 Day 6 complete" section: traces live across detection skills and curator; substrate is now legible for v3.
