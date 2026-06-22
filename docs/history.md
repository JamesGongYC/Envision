# Envision — History & Resolved-Incident Archive

Historical reference for the build lineage and the incidents resolved along the way. The live current-state handoff is `PROGRESS.md`; this file is append-only archive and is not the source of truth for how the system runs today.

---

## 1. Build lineage

**v1 — Hermes-era MVP (Days 1–6, ~2026-05-28).**
Hermes Agent (Nous Research) on Windows/Git Bash, `local` terminal backend, manual `hermes cron tick`. 5 ingestion/detection skills writing to Neon. Viewer scaffolded on Vercel (single forecast layer). Templated detection reasoning. Curator built but gated (parameter tweaks only, manual approval). Demo seed data used for soft launch. Automatic cron firing never worked on Windows (`schtasks` access-denied); the scheduler lived in the gateway daemon.

**v2 — data enrichment & legibility.**
Took the signal catalog from 4 sources to ~9. Added `open-meteo-fire-weather`, `jtwc-cyclones`, `ecmwf-fire-weather-derived`, `aifs-overlay`; global FIRMS (6-bbox). Refactored every detection skill to `run(now, db)` (the backtest prerequisite). Added `forecasts.trace` + `curator_trace` JSONB and the `signal_catalog` matview (migration 004). Frontend ops surface: per-skill cards, status header, Brier sparklines. **AIFS reframed as a signal source, not a forecast producer.**

**v2.5 — Modal consolidation & viewer UX.**
Hermes decommissioned; all 12 production skills migrated to Modal native cron. Multi-layer map (forecasts + 7 point + 2 polygon signal layers). Reversed v1's templated-reasoning decision — LLM-generated per-forecast narration returned (cost ~$5/month at v2 volume, not the v1-projected $25/week), with template fallback on API failure. Forecast dropdown with typing-animated reasoning. `wind_fields` table + leaflet-velocity wind streaming (migration 005, v2.6).

**v3 — self-evolution loop (built 2026-06-03).**
10-day plan compressed to a 4-day split. Migrations 006–008: `skill_lineage`, `backtest_run`, `forecasts_shadow`, lineage-candidate lifecycle, `shadow_evaluations`. Built the backtest harness, mutator + validation, selector, shadow runner, and Day-4 curator orchestration (worst-K → mutate → select → shadow). Generator (de-novo skills) deferred to v3.1; diversity penalty and tiered auto-approve cut. **Open gap at the time:** the backtest ±0.02 sanity gate could not be turned green (v2's DB refactor left history inconsistent for replay), so shadow Brier — not backtest — became the trusted fitness signal.

**v3 recovery (2026-06-08).**
The loop was dead 06-01 → 06-08 (100% mutant rejection). Four faults fixed (see §2). Fitness signal cleaned: GDACS natural-key dedup (migration 009), seed-data purge, and `BACKTEST_EPOCH = 2026-06-04` introduced as a single fencing constant. Shadow gate opened on a light viability gate; three candidates admitted to shadow.

**First promotion (current).**
GDACS constraint finalized (migration 010), ground truth refreshed. The `wildfire_rapid_growth` mutant (lineage `4baa8dda`, shadow Brier 0.4078 vs parent 0.5812) cleared its shadow clock and was promoted to production — the first completed mutate → shadow → promote cycle on live data.

## 2. Resolved-incident archive

**The dead evolution loop (06-01 → 06-08) — four faults, one symptom.**
1. *Sandbox swallowed exceptions* — validator reported a generic string, starving the mutator's retry-with-feedback. Fixed: real `{TypeName}: {message}` + 2KB traceback into `rejection_reasons`.
2. *Curator Modal image lacked `sklearn`/`shapely`* — every wildfire mutant died at import; validation had only ever run locally with full deps. Fixed: single shared `skill_exec_image.py`.
3. *Exec-from-string broke skill bootstrap* — `Path(__file__).parents[2]` raised `IndexError: 2` on the parent baseline load, before the mutant was even evaluated. The precise unlock. Fixed: loader injects a synthetic deep `__file__`.
4. *Shadow gate deadlock* — selector gated shadow admission behind backtest cross-window ranking (needs 30 GT events; only 7 existed), so the trusted signal was gated behind the untrusted one. Fixed: light viability gate to shadow; backtest as pathology filter only.

**Ingestion outage (05-29 → 06-03).** Detection silently produced 0 forecasts; FIRMS stale since 05-31, NWS since 05-29. Root cause: five ingestion apps were not deployed on Modal. Redeployed. Lesson: a deploy that succeeds but fails at runtime is invisible until something runs — add per-source staleness to the status header (still deferred).

**GDACS advisory-update duplication.** md5-payload dedup let every advisory update create a new `ground_truth` row (one typhoon had 22 rows; one eventid had 21 under two names after naming). Fixed with natural key `(source, eventid)` + `ON CONFLICT DO UPDATE` (migrations 009/010).

**Legacy curator firing lineage-less proposals.** The old v2.5 curator (deployed 05-30) kept emitting old-contract proposals (returns int, self-INSERTs, no trace). Stopped by App ID; two orphan proposals rejected. One proposed lowering `p` 0.45→0.40 on a 74%-hit skill — rejected on the p = hit-rate principle.

**Test-fixture pollution.** Tests committing to the prod DB left "fixture mutant" rows in the live approval queue. Removed via SQL (broke circular FK, deleted lineage then proposals). Now enforced via `.cursor/rules/test-db-isolation.mdc`.

**Health-check scares (not bugs).** 296 ungraded forecasts and similar mid-cycle backlogs are normal — the evaluator runs once daily (07:00 UTC). Only a backlog that *survives* a run is a bug; check ground-truth health first, since dead GT makes a healthy grader look all-false-positive.

**Viewer / deploy issues (v1–v2.5).** Map dark-mode override; Leaflet container 0-height under dynamic `ssr:false` imports (fixed with explicit `100dvh` minus nav offset); polygons invisible at world zoom (pixel-constant `CircleMarker` overlay); Vercel `DATABASE_URL` required in all three environments; Vercel Root Directory = `viewer/`; nested `.git` from `create-next-app` blocking commits; `@neondatabase/serverless` for connection pooling (not `pg`).

## 3. Decisions retired or reversed

- **Hermes → Modal** (v2.5). Hermes archived; Modal native cron eliminated the Windows admin/`schtasks` friction that consumed half of v1's debugging.
- **Templated reasoning → LLM reasoning** (v2.5), reversing v1's cost-driven choice as volume economics changed.
- **AIFS as forecast producer → signal source** (v2). Lands in `signals`, consumed downstream by detection skills.
- **Baseline twin runs** (planned v1 §7) — never implemented; cut.
- **JMA ingestion, real GHSL raster, EFFIS/GWIS** — cut/deferred; `cities5000` remains the population stand-in.
- **Typed composition DSL** — explicitly abandoned per the bitter-lesson framing; mutation is raw LLM Python rewrites.
