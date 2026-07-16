# T1 — Migration: agent telemetry + forecast provenance

**Goal:** Land the schema v4 stands on — `agent_run`, `agent_step`, and provenance columns on `forecasts` — in one transaction.
**Depends on:** none. **Blocks:** T2, T3, T4, T5, T6.

House rules: single transaction; guard for re-run; no test writes to prod DB; geometry SRID 4326; `git push origin master:main`.

---

## Context
D7/D8/D9 (locked). Two production writers share one `forecasts` table distinguished by `producer`; every agent run and step is persisted for replay (D10) and telemetry parity with `llm_call_log`. No cross-producer dedup — the duplication *is* the agent-vs-rule A/B signal.

## Migration number
`PROGRESS.md` records head 011 with a conditional `012` (generation_method/parent_skill_id backfill). **First step: confirm the live head against the repo.** If 012 landed, this is **013**; if 012 was never needed, this is **012**. Do not guess — `SELECT max(version) FROM schema_migrations;` (or the project's equivalent ledger) before naming the file.

## Files
- `migrations/013_agent_telemetry.sql` (or `012_…` per above).
- Any migration-runner manifest/ledger the repo uses to register applied versions.
- No app code in this ticket.

## DDL
```sql
BEGIN;

CREATE TABLE agent_run (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_type       text NOT NULL CHECK (agent_type IN ('forecaster','critic')),
  trigger          text NOT NULL CHECK (trigger IN ('button','scheduled','operator')),
  status           text NOT NULL CHECK (status IN ('running','completed','failed','gated')),
  started_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz NULL,
  step_count       int NOT NULL DEFAULT 0,
  outcome          jsonb NULL,          -- emitted forecast ids | created proposal ids
  health_gate_state text NULL,
  error            text NULL
);

CREATE TABLE agent_step (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_run_id  uuid NOT NULL REFERENCES agent_run(id) ON DELETE CASCADE,
  seq           int  NOT NULL,
  step_type     text NOT NULL CHECK (step_type IN ('thought','action','observation','gated','terminal')),
  tool          text NULL,
  tool_input    jsonb NULL,
  tool_output   jsonb NULL,             -- size-capped by the writer (16KB trace discipline)
  geo_focus     geometry(Geometry,4326) NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_agent_step_run_seq ON agent_step (agent_run_id, seq);

ALTER TABLE forecasts
  ADD COLUMN producer text NOT NULL DEFAULT 'rule'
    CHECK (producer IN ('rule','agent')),
  ADD COLUMN agent_run_id uuid NULL REFERENCES agent_run(id);
CREATE INDEX idx_forecasts_producer ON forecasts (producer);

COMMIT;
```

## Notes / guardrails
- Existing `forecasts` rows read `producer='rule'`, `agent_run_id NULL` via the default — **no data backfill**.
- The existing 0.85 probability-cap CHECK on `forecasts` is untouched and now governs both producers.
- `geo_focus` stores an envelope polygon; write via `ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(:bbox),4326))`, read via `ST_AsGeoJSON`.
- `ON DELETE CASCADE` on `agent_step` so a run purge (housekeeping) drops its steps.
- Add `agent_run`/`agent_step` retention to `housekeeping-retention` in a follow-up (tracked in T-cleanup, not here) — but leave a comment in the migration noting the pruning obligation.

## Test plan (scratch/test DB only)
1. Apply on a clean scratch DB → succeeds; re-run guard prevents double-apply.
2. Insert a `forecasts` row without `producer` → reads `'rule'`.
3. Insert `forecasts` with `p = 0.9` → rejected by the existing cap CHECK.
4. Insert `forecasts` with `producer='bogus'` → rejected.
5. Insert `agent_run` + two `agent_step` rows, delete the run → steps cascade-deleted.
6. Round-trip a `geo_focus` bbox GeoJSON → geometry → GeoJSON, coordinates preserved.

## Acceptance
- [ ] Head confirmed; file numbered correctly.
- [ ] Migration applies clean and is re-run-safe, single transaction.
- [ ] Legacy `forecasts` rows default to `rule`/NULL.
- [ ] Cap CHECK and enum CHECK both enforced for the new column.
- [ ] Cascade + geometry round-trip verified.

## Out of scope
App code, retention wiring, any read/write of the new tables from Modal or the viewer.
