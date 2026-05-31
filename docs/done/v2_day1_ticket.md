# v2 Day 1 — Foundations

**Scope.** Migration 004 (trace columns + signal_catalog matview), sync tooling for the structured-repo ↔ flat-runtime asymmetry, a new `housekeeping-retention` skill, and a uniform `run(now, db)` refactor of every existing skill. All v3 prerequisite groundwork — none of the v3 evolution loop itself.

## Canonical context

Attach via `@`:

- `@docs/envision_plan.md`
- `@docs/v2_plan.md`
- `@docs/v3_plan.md` (for v3 dependency contract awareness)
- `@docs/PROGRESS.md`
- `@db/schemas.py`
- `@db/migrations/001_init.sql`
- `@db/migrations/002_hardening.sql`
- `@db/migrations/003_populated_places.sql`

## Pre-decided

1. **Structured repo, flat runtime.** Repo keeps `agent/skills/<category>/<skill_id>/`. Runtime at `~/.hermes/skills/<skill_id>/` is flat. Bridged by `tools/sync_skills.py`.
2. **Sync gate.** All edits land in the repo. Sync to runtime is operator-controlled via an `--apply` flag. Cursor must not write into `~/.hermes/skills/` directly (it's not in the workspace anyway, but no shell calls to mirror either).
3. **Refactor signature.** Every skill script gains `def run(now: datetime, db: Connection)`. Detection skills use `now` as a query cutoff (`AND timestamp <= %s`). Ingestion skills use `now` only to stamp `ingested_at`. Same shape, different load-bearing.
4. **Backward compatibility.** Hermes cron continues invoking `python scripts/<x>.py` with no args; default `now = datetime.now(timezone.utc)`. v3's harness will `from <x> import run` and pass historical `now` values.
5. **Migration numbering.** This migration is `004_v2_additions.sql`. v3_plan §6 currently labels its migration `004_evolution.sql` too — that's a future collision. Add a TODO comment in `v3_plan.md` to renumber → `005` when v3 starts. Do not modify v3's plan text beyond that.
6. **Retention windows.** signals 30d, forecasts 60d, indefinite for `ground_truth` / `evaluations` / `skill_edit_proposals`. If migration 002's commented retention SQL specifies different windows, prefer 30/60/indefinite and update 002's comment to match.

## Deliverables

### D1 — `tools/sync_skills.py`

Python script. Walks `agent/skills/` looking for any directory containing `SKILL.md` (that's the canonical skill marker — not the category dirs). For each found `skill_id`, copies `agent/skills/<...>/<skill_id>/` to `~/.hermes/skills/<skill_id>/` via `rsync -av --delete` with excludes for `__pycache__`, `*.pyc`, `.pytest_cache`, `.DS_Store`.

CLI:

- `python tools/sync_skills.py` — dry run by default; prints planned changes, no mutation.
- `python tools/sync_skills.py --apply` — performs the sync.
- `python tools/sync_skills.py --apply --prune` — additionally deletes runtime skill dirs not present in repo.

Behaviors:

- **Collision detection.** If two repo dirs produce the same `skill_id`, abort with exit code 1 and list the offending paths.
- **Orphan warning.** List runtime skills not in repo. Don't auto-delete without `--prune` AND `--apply`.
- **Idempotent.** Running twice with `--apply` is a no-op on the second run.

Acceptance: with no flags, prints planned actions and lists `usgs-hello-world` as a known orphan (assuming D4 deletion is complete), exits 0. With `--apply`, runtime mirrors repo exactly modulo orphans.

### D2 — `db/migrations/004_v2_additions.sql`

SQL contents per v2_plan §5, applied via Neon SQL Editor (browser):

- `ALTER TABLE forecasts ADD COLUMN trace JSONB NOT NULL DEFAULT '{}'::jsonb;`
- `ALTER TABLE forecasts ADD CONSTRAINT trace_size_cap CHECK (octet_length(trace::text) <= 16384);`
- `ALTER TABLE skill_edit_proposals ADD COLUMN curator_trace JSONB NOT NULL DEFAULT '{}'::jsonb;`
- `CREATE MATERIALIZED VIEW signal_catalog AS ...` per v2_plan §5 (full DDL is in the plan).
- `CREATE UNIQUE INDEX ON signal_catalog (source, signal_type);` (required for `REFRESH ... CONCURRENTLY`).

Acceptance, verified in Neon SQL Editor:

- `\d forecasts` shows `trace` column with default `'{}'::jsonb` and `trace_size_cap` constraint.
- `\d skill_edit_proposals` shows `curator_trace`.
- `\dm signal_catalog` exists with non-zero rows (it auto-populates on creation).
- `REFRESH MATERIALIZED VIEW CONCURRENTLY signal_catalog;` succeeds.

### D3 — `agent/skills/housekeeping/housekeeping-retention/`

New skill — net-new, no existing files touched. Two files:

**`SKILL.md`** — describes purpose, retention windows, cadence, and note that this skill is unaffected by `ENVISION_CURATOR_ENABLED` (it's housekeeping, not mutation).

**`scripts/run_retention.py`** — exposes `def run(now: datetime, db: Connection) -> dict` returning row counts deleted per table. Reads `DATABASE_URL` from env. Executes:

- `DELETE FROM signals WHERE ingested_at < %s - interval '30 days'` (param: `now`)
- `DELETE FROM forecasts WHERE issued_at < %s - interval '60 days'`
- `REFRESH MATERIALIZED VIEW CONCURRENTLY signal_catalog;`

`__main__` block parses optional `--now ISO8601` (default: `datetime.now(timezone.utc)`).

Acceptance:

- After sync, `python ~/.hermes/skills/housekeeping-retention/scripts/run_retention.py` runs clean against live Neon.
- Register cron: `hermes cron add "24h" "Run the housekeeping-retention skill"`.
- `hermes cron tick` fires it without error.

### D4 — Refactor existing skills to `run(now, db)`

Apply to each skill **one at a time**, completing the per-skill smoke test below before moving to the next. Order:

1. `agent/skills/ingest/firms-active-fires/`
2. `agent/skills/ingest/nws-fire-alerts/`
3. `agent/skills/ingest/nhc-cyclones/`
4. `agent/skills/ground_truth/gdacs-poller/`
5. `agent/skills/detect/wildfire-risk-elevated/`
6. `agent/skills/detect/wildfire-rapid-growth/`
7. `agent/skills/detect/typhoon-intensifying/`
8. `agent/skills/detect/typhoon-landfall-imminent/`
9. `agent/skills/evaluate/forecast-evaluator/`
10. `agent/skills/curator/` (uniform shape; `now` may not be load-bearing here)

For each skill:

- Extract main logic into top-level `def run(now: datetime, db: Connection)`. Return type can be `list`, `dict`, or `int` (row count) — natural per skill; uniformity not required for Day 1.
- Replace any inline `datetime.utcnow()` / `datetime.now(timezone.utc)` with the `now` parameter.
- **Detection skills only:** every query against `signals` adds `AND timestamp <= %s` bound to `now`. This is the load-bearing v3 prerequisite — confirm by code review per skill.
- `if __name__ == "__main__":` parses optional `--now ISO8601` with `argparse` (default `datetime.now(timezone.utc)`), connects via `DATABASE_URL`, calls `run(now, db)`.
- Don't modify SKILL.md unless user-facing CLI changes (e.g., add a note about `--now`).

`usgs-hello-world`: do NOT refactor. Delete the repo dir `agent/skills/ingest/usgs-hello-world/`. The sync script's orphan warning will surface it at runtime; operator prunes with `--prune --apply`.

**Per-skill smoke test (mandatory checkpoint):**

```bash
# 1. Refactor in repo.
# 2. Sync to runtime:
python tools/sync_skills.py             # review the diff
python tools/sync_skills.py --apply

# 3. Smoke-run without args (back-compat):
python ~/.hermes/skills/<skill_id>/scripts/<...>.py

# 4. Smoke-run with --now to a recent past time (detection only):
python ~/.hermes/skills/<skill_id>/scripts/<...>.py --now 2026-05-25T00:00:00Z

# 5. Confirm in Neon:
#    Ingestion:
SELECT count(*), max(ingested_at) FROM signals WHERE source = '<...>';
#    Detection:
SELECT count(*), min(issued_at), max(issued_at) FROM forecasts WHERE skill_id = '<...>';

# 6. Only after this passes, move to the next skill.
```

If a skill fails its smoke test, **stop and report** rather than push through. Conventions established by early skills are inherited by later ones; a broken pattern compounds.

### D5 — `docs/TRACES.md`

Schema-only document. Defines the JSONB shape for `forecasts.trace` and `skill_edit_proposals.curator_trace` per v2_plan §5. Must cover:

- 16KB cap (CHECK constraint named `trace_size_cap`).
- `run(now, db)` signature contract.
- Detection trace conventions: required keys `now`, `inputs`, `intermediate`, `geometry_steps`, `probability_components`.
- Ingestion trace conventions (descriptive — ingestion does NOT currently write trace; this is forward guidance for Day 6): `now`, `fetched_at`, `rows_inserted`, `rows_deduped`.
- Curator trace conventions per v2_plan §5.

Population of these traces is **Day 6**, not Day 1. This doc just locks the schema.

## Out of scope (Day 1)

- Trace JSONB *population* — Day 6.
- New ingestion sources (Open-Meteo, JTWC, EFFIS, ECMWF, AIFS) — Days 2–5.
- Frontend changes — Days 7–8.
- Curator behavior changes — Day 6. Day 1 only adds the `curator_trace` column; the Curator doesn't write to it yet.
- JMA ingestion — still cut.
- Baseline twin runs — still cut.

## Notes / gotchas

- **Skill directory naming.** Runtime currently uses hyphenated names (`wildfire-risk-elevated/`, `forecast-evaluator/`, etc., per `ls ~/.hermes/skills/`). PROGRESS.md §10 shows some underscore variants (`wildfire_risk_elevated/`) for detect/evaluate skills. **Authoritative source is the actual filesystem**, not the docs. Before running sync the first time, verify repo dir names match runtime exactly. If a mismatch exists, normalize the repo to hyphens — don't rename runtime, that breaks the existing cron jobs by skill_id.
- **`.env` loading.** Hermes reads `~/.hermes/.env` for `DATABASE_URL`, `ANTHROPIC_API_KEY`, `FIRMS_MAP_KEY`, `NWS_USER_AGENT`. Standalone `python script.py` does NOT — `export` in shell first when running outside Hermes.
- **Geometry inserts.** `ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(...), 4326))` is non-negotiable. Don't drop this in any refactor — Z-coordinate feeds will crash inserts without it.
- **`--now` parsing.** Use `datetime.fromisoformat`; treat naïve datetimes as UTC by attaching `tzinfo=timezone.utc` if none supplied.
- **Migration 004 idempotency.** It applies cleanly on a database with existing rows (the `DEFAULT '{}'::jsonb` covers trace columns; the CHECK passes for empty JSON). But it is NOT idempotent across reruns — wrap in a transaction in the SQL Editor or use `IF NOT EXISTS` clauses where possible.
- **v3 import smoke test.** After D4 completes, confirm `from <module path> import run` works for at least one detection skill — that's the contract v3's backtest harness will rely on.

## Done definition

- All D1–D5 acceptance criteria met.
- Per-skill smoke tests in D4 pass for all 9 refactored skills (plus `usgs-hello-world` deleted).
- `hermes cron list` shows 9 jobs (was 8; +1 for retention).
- `git status` clean from `~/Downloads/envision/`.
- `PROGRESS.md` updated with a "v2 Day 1 complete" section noting: migration 004 applied, sync tooling in place, retention cron registered, all skills refactored to `run(now, db)`.
