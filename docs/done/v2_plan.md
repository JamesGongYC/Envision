# Envision v2 — Data Enrichment, Operator Legibility, v3 Foundations

The substrate that makes v3 worth running. New signal sources to widen the combinatorial space the v3 mutator will explore, instrumentation that makes both human operators and the v3 mutator able to read what skills are doing, and the structural prerequisites v3 cannot start without.

---

## 1. Premise

v2 has two jobs:

1. **Enrich the data substrate.** v1 ships with 4 signal sources (FIRMS, NWS Alerts, NHC, GDACS) and a 4-detector library. The v3 self-evolution loop needs combinatorial room to invent over — fewer than ~8 signal types and the generator is just hallucinating from skill names. v2 takes the catalog from 4 to ~10.
2. **Make the system legible.** Both directions: humans looking at `/agent` should understand what skills do and why; the v3 mutator looking at `evaluations` should see *why* a skill failed, not just *that* it did. Both demands resolve to the same artifact — structured trace JSONB.

v2 deliberately does *not* include the self-evolution loop. It does include every prerequisite v3 requires. The contract between them is enumerated in §12.

## 2. Decisions log

| Decision | Choice | Rationale |
|---|---|---|
| Global FIRMS | Drop US bbox; chunk queries per continent; raise volume cap | Vision needs global; cost is more API calls + retention discipline |
| New event feeds priority | Open-Meteo, JTWC, EFFIS/GWIS first; MeteoAlarm later | Free JSON, no GRIB, large data-density payoff per day of work |
| ECMWF gridded data | Derived index emitted as polygon signals, not stored as raster | Avoid storing grids in Postgres; compute at signal-time |
| AI model overlay | AIFS (ECMWF), not Fuxi | Pre-computed open data, no GPU, comparable cyclone skill; Fuxi was decommissioned from ECMWF charts |
| Trace instrumentation | JSONB column on `forecasts` + `skill_edit_proposals` | Single migration, no architecture change |
| Detection-time reasoning | Keep templated; defer LLM-generated narrative | Cost + determinism; v3 may revisit |
| Skill refactor | Parametrize `now` everywhere in v2 | v3 prerequisite (backtest replay); also makes v2 skills more testable |
| Operator UX | Per-skill cards + status header + activity feed | Concrete, low-cost, addresses user feedback directly |
| Defer | Dark theme, coordinated panes | Real lift, low priority vs. v3 substrate |

## 3. Non-scope for v2

- The self-evolution loop (mutation, generation, shadow mode, backtest). That is the entirety of v3.
- LLM-generated reasoning at detection time.
- Real-time alerting (push, email, SMS).
- User accounts, auth, regional queries.
- Mobile-optimized viewer.
- API access for third parties.
- JMA ingestion. Still cut.
- Real GHSL raster. `cities5000` stand-in remains.
- Baseline twin runs. Still cut.
- Dark theme.
- Coordinated multi-pane views on `/agent`.

## 4. Architecture additions

v2 doesn't reshape the v1 architecture. It widens the substrate and adds instrumentation:

```
[Open data sources]                                  ← v1: 4 sources
   FIRMS (global)                                    ← v2: was US-bbox
   NWS Alerts                                        
   NHC                                               
   GDACS                                             
   Open-Meteo            ← v2 NEW
   JTWC                  ← v2 NEW
   EFFIS / GWIS          ← v2 NEW
   ECMWF Open Data       ← v2 NEW (GRIB → derived index)
   AIFS                  ← v2 NEW (AI model forecasts → forecasts table)
        │
        ▼
[Postgres: signals]  ← gains `signal_catalog` materialized view
        │
        ▼
[Detection skills]   ← refactored: `run(now, db) -> list[Forecast]`
        │             ← now writes `trace JSONB` per forecast
        ▼
[Postgres: forecasts]  ← gains `trace` column
        │
        ▼
[Evaluator + Curator]  ← Curator writes `curator_trace JSONB`
```

AIFS is a new kind of forecast — model-driven rather than rule-based — but it lands in the same `forecasts` table. Distinguished by `skill_id='aifs-overlay'`. Evaluated by the same evaluator. Excluded from the v3 mutation surface (see §12).

## 5. Schema additions

Migration `004_v2_additions.sql`:

```sql
-- Trace instrumentation
ALTER TABLE forecasts
  ADD COLUMN trace JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE skill_edit_proposals
  ADD COLUMN curator_trace JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Trace size cap (sanity)
ALTER TABLE forecasts
  ADD CONSTRAINT trace_size_cap CHECK (octet_length(trace::text) <= 16384);

-- Signal catalog (refreshed daily)
CREATE MATERIALIZED VIEW signal_catalog AS
SELECT
  source,
  signal_type,
  COUNT(*) AS row_count,
  MIN(timestamp) AS first_seen,
  MAX(timestamp) AS last_seen,
  ST_Envelope(ST_Collect(geometry)) AS coverage_bbox,
  (array_agg(payload ORDER BY timestamp DESC))[1:3] AS sample_payloads
FROM signals
GROUP BY source, signal_type;

CREATE UNIQUE INDEX ON signal_catalog (source, signal_type);
```

Trace JSONB schemas (documented in `docs/TRACES.md`, not enforced at DB layer):

```python
# forecasts.trace
{
  "now": "2026-06-01T12:00:00Z",         # the parametrized timestamp
  "inputs": {"signal_count": 487, "filter_applied": "..."},
  "intermediate": {"clusters_found": 3, "selected_cluster_size": 47},
  "geometry_steps": [...],
  "probability_components": {...}
}

# skill_edit_proposals.curator_trace
{
  "brier_stats_observed": {...},
  "llm_input_prompt_hash": "...",
  "llm_response_full": "...",
  "ast_validation": {"passed": true, "warnings": []},
  "rejection_reasons": []
}
```

## 6. Tech stack additions

- `cfgrib` + `xarray` + `eccodes` system dep for GRIB parsing (ECMWF derived layer + AIFS)
- `httpx` continues for JSON endpoints (Open-Meteo, EFFIS, JTWC)
- GRIB-handling skills run on Linux (Modal) only — Windows `eccodes` install is painful

## 7. New ingestion / overlay skills

| Skill | Writes to | Source | Cadence |
|---|---|---|---|
| `firms-active-fires` (refactor) | `signals` (hotspot) | NASA FIRMS, chunked per continent | 30 min |
| `open-meteo-fire-weather` | `signals` (fire_weather) | Open-Meteo forecast API | 3 h |
| `jtwc-cyclones` | `signals` (cyclone_advisory) | JTWC ATCF bulletins (Western Pacific) | 6 h |
| `effis-fire-events` | `signals` (fire_event) | EFFIS / GWIS JSON | 6 h |
| `ecmwf-fire-weather-derived` | `signals` (fire_weather_grid) | ECMWF Open Data GRIB → derived index polygons | 12 h |
| `aifs-overlay` | `forecasts` (model-driven) | ECMWF Open Data AIFS GRIB | 12 h |

ECMWF derived index: 2m temp + dewpoint depression + 10m wind + 24h precipitation deficit → fire weather index per grid cell; emit polygon signals where index exceeds threshold. The detection skill `wildfire_risk_elevated` can then consume these globally (replacing its US-only NWS gate).

AIFS overlay: parse 72h forecast for MSLP minima + 850hPa vorticity maxima; emit cyclone-like features as `forecasts` rows with model-driven reasoning. Same evaluator scores them against `ground_truth` as any other forecast.

## 8. Day-by-day roadmap (10 days)

### Day 1 — Skill refactor + retention (v3 prerequisites)
- Parametrize `now` across every detection and ingestion skill. Signature: `run(now: datetime, db: Connection) -> list[Forecast]` for detectors; analogous for ingestors. No `datetime.utcnow()` inline anywhere.
- Wire migration 002's retention SQL to a cron (was manual).
- Apply migration 004 (trace columns + signal_catalog view).

### Day 2 — Global FIRMS + Open-Meteo + JTWC + EFFIS
- FIRMS: drop bbox, chunk per continent (6 bboxes), raise per-call row cap to 8000.
- Open-Meteo fire weather signals.
- JTWC ATCF bulletin parser.
- EFFIS / GWIS JSON ingestion.
- All write to `signals` with proper source attribution.

### Day 3 — Signal catalog refresh + per-source validation
- Daily cron to refresh `signal_catalog`.
- Validate each new source: row counts reasonable, geometry valid, payloads parseable, dedup trigger handling them correctly.
- Update `signal-sources.ts` in viewer so detail pages render attribution.

### Day 4 — ECMWF GRIB ingestion (the expensive day)
- Install `cfgrib` + `eccodes` on Modal Linux image.
- Build GRIB → derived fire weather index pipeline.
- Emit polygon signals where index > threshold.
- Generalize `wildfire_risk_elevated` to use ECMWF index globally OR fall back to NWS in the US; ship as a single skill.

### Day 5 — AIFS overlay
- ECMWF Open Data AIFS via their HTTP API.
- Parse 72h forecast: MSLP minima, 850hPa vorticity.
- Cyclone-like feature detection (deterministic, not LLM).
- Emit forecasts with `skill_id='aifs-overlay'`, model-driven reasoning string.

### Day 6 — Trace instrumentation
- Update all detection skills to write structured `trace` JSONB per forecast.
- Update existing v1 Curator to write `curator_trace` per proposal.
- Backfill: leave existing rows with empty `{}`; new writes populate.
- This is the most important day for v3.

### Day 7 — Frontend ops surface
- Replace `/agent` skill stats table with per-skill cards: name, plain-language description (from `skill-metadata.ts`), current version, Brier (4 digits), hits/false-alarms (with hover-tooltip definitions), small sparkline of Brier across versions.
- Top of `/agent`: fixed explainer block describing the pipeline in 3 sentences.
- Status header on every page: skills active count, last ingestion timestamp, curator status (enabled/disabled).

### Day 8 — Frontend trace surfaces
- `/forecast/[id]`: add a collapsible "Detection trace" section rendering the JSON trace as a structured tree (not raw JSON).
- `/agent`: add collapsible "Curator trace" for each proposal showing what the Curator observed and proposed.
- Activity feed strip on `/` (right rail desktop, hidden mobile): last 10 ingestion + detection + proposal events.

### Day 9 — Buffer / observed-data quality check
- Run all skills for 24h. Inspect: trace JSONB sizes, signal_catalog accuracy, detection skill behavior on new globally-sourced data, AIFS overlay reasonableness.
- Tune anything pathological.

### Day 10 — Documentation
- `METHODS.md`: new sources, derived index methodology, AIFS attribution.
- `docs/TRACES.md`: trace JSONB schema documentation (informal but precise).
- `/about` page: updated source attribution + AIFS disclosure.
- `PROGRESS.md`: v2 closeout.

## 9. Cut list

In order of expendability:

1. **AIFS overlay** (defer to v2.1). Most expensive day, narrowest payoff for v2's data-richness goal.
2. **ECMWF GRIB derived index** (defer to v2.1). Same reasoning. Open-Meteo's fire weather variables are an acceptable temporary substitute.
3. **`curator_trace` JSONB** on proposals. Just `forecasts.trace` is sufficient for v3's mutator.
4. **Activity feed strip**. Status header alone covers the ops framing.
5. **EFFIS/GWIS**. Open-Meteo + JTWC suffice for global event coverage.

**Never cut:**
- Global FIRMS (the primary substrate widening)
- `now` parametrization (v3 blocked without it)
- `trace JSONB` on forecasts (v3 blocked without it)
- `signal_catalog` view (v3 blocked without it)
- Per-skill cards on `/agent` (direct user feedback)
- Retention automation (without it, Day 4+ blows the DB)

## 10. Risks

| Risk | Mitigation |
|---|---|
| Global FIRMS overruns Neon free tier | Retention cron from Day 1; raise to Neon paid if signals table > 0.4GB; weekly monitoring |
| `cfgrib` / `eccodes` install fragility | Pin in Modal Linux image; Windows local dev skips GRIB skills entirely |
| AIFS data format drift | Pin ECMWF Open Data API version; subscribe to their changelog |
| JTWC bulletin parsing breaks | ATCF is a stable 1980s format; budget half a day for edge cases |
| Trace JSONB rows grow huge | 16KB hard cap as CHECK constraint; aggregate older traces if needed |
| Refactoring `now` breaks existing skills | Comprehensive replay test before deploy; current skills get an explicit smoke run before merge |
| Open-Meteo rate limits | Free tier is generous; chunk by region; cache 1h |
| Trace JSONB schema drift between skills | Document expected fields in `docs/TRACES.md`; v3's mutator handles missing fields gracefully |

## 11. Open questions

- Should AIFS be excluded from v3's mutation surface? (Lean: yes — it's not a skill the LLM should rewrite, it's a baseline reference. Mark with `is_mutable=false` in lineage table when v3 ships.)
- Per-source attribution: where on `/forecast/[id]`? (In the contributing-signals list, link to source.)
- Materialized view vs real table for signal catalog? (Materialized view; daily refresh; cheap.)
- Should `effis-fire-events` write `signal_type='fire_event'` (suggesting confirmed event) or `signal_type='fire_indicator'` (treating it as another hotspot-like signal)? (Lean: `fire_event` — EFFIS confirms; this gives the detector signal something stronger than FIRMS hotspots.)

## 12. v3 dependency contract

This is the section v2 tickets must respect. What v2 commits to delivering for v3:

1. **`now` parametrization in every detection skill.** Signature: `run(now: datetime, db: Connection) -> list[Forecast]`. Detection logic queries `signals` with `WHERE timestamp <= :now`. No `datetime.utcnow()` calls inline. This is what enables backtest replay; without it v3 cannot begin.

2. **`forecasts.trace` JSONB populated by every detection skill.** Structure documented in `docs/TRACES.md`. The mutator reads this to understand why skills fail; v3 Day 2 is blocked without real trace data accumulated over weeks.

3. **`signal_catalog` materialized view.** The v3 generator reads this to know what signals exist before proposing a new skill from scratch. If it's missing, the generator hallucinates source names.

4. **`skill_edit_proposals.curator_trace` JSONB populated by the existing Curator.** Lets v3's mutator interoperate with the existing proposal-and-approval queue.

5. **≥8 signal types in `signals`.** v1 has 4. The mutator/generator needs combinatorial space; below 8, generated skills look like noise.

6. **Retention automation running.** Without it, the signals table runs out of room during v3 backtesting.

**Anti-dependencies — what v2 must NOT do:**

- Don't introduce a typed composition DSL. v3 explicitly rejects domain primitives per the bitter-lesson framing.
- Don't move detection logic into a "framework" with helper functions that smell like primitives. Skills stay as plain self-contained Python — that's what the v3 mutator rewrites.
- Don't auto-deploy curator proposals. The operator gate is load-bearing for v3 safety.
- Don't unify the evaluator across skills. v3 needs the evaluator to be a single hardcoded component the mutator cannot reach.

---

## Appendix A — Files Cursor should always have in context for v2 work

- `envision_plan.md`
- `v2_plan.md` (this file)
- `v3_plan.md` (for dependency-contract awareness)
- `docs/PROGRESS.md`
- `db/schemas.py`

## Appendix B — Repo layout additions

```
envision/
├── agent/skills/
│   ├── ingest/
│   │   ├── firms-active-fires/        # refactored: global, parametrized now
│   │   ├── open-meteo-fire-weather/   # NEW (v2)
│   │   ├── jtwc-cyclones/             # NEW (v2)
│   │   ├── effis-fire-events/         # NEW (v2)
│   │   └── ecmwf-fire-weather-derived/ # NEW (v2, Modal-only)
│   └── overlay/                        # NEW (v2)
│       └── aifs-overlay/               # NEW (v2, Modal-only)
├── db/migrations/
│   └── 004_v2_additions.sql           # trace columns + signal_catalog view + retention cron
└── docs/
    ├── v2_plan.md                     # this file
    └── TRACES.md                      # NEW (v2): trace JSONB schema documentation
```
