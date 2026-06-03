# Envision v3 — Day 2 Ticket: Mutator + Validation Pipeline

**Goal:** a callable `mutate_skill(skill_id, db) -> MutationResult` that takes a detection skill, asks Sonnet to rewrite its Python for better Brier given real failure evidence, validates the candidate hard (AST + sandbox), and lands an accepted candidate in the operator queue with a lineage row. No scoring, no deployment — invention + validation only.

**Canonical context:** `docs/v3_plan.md` (§2, §6, Day 2), `docs/v3_day1_ticket.md`, `docs/v3_fix_backtest_window.md`, `agent/modal_skills/curator/scripts/run_curator.py` (existing AST validator + tool_use pattern), `agent/modal_skills/<detect>/run.py`, `agent/evolution/backtest_harness.py` (connection proxy), `agent/lib/scoring.py`, `agent/lib/trace_builder.py`, `db/schemas.py`.

---

## Dependencies

- **Inputs are independent of the harness.** Parent source, 14d Brier trajectory, and worst-Brier traces all come from `evaluations`/`forecasts`. Build these now regardless of the Day-1 gate state.
- **The sandbox smoke-run (§4.6) reuses the window-guarded connection proxy from the fix ticket.** That part of `v3_fix_backtest_window.md` must land first.
- **You cannot yet tell if a mutant is *better*.** That's backtest Brier (Day 4 Selector), which needs the harness green. Day 2 produces *valid, executable, traceable* candidates — not ranked ones. Do not add scoring here.

---

## 1. Schema amendment — candidate lineage

The Day-1 `skill_lineage` table assumed a linear promoted history (`UNIQUE (skill_id, version)`, `version NOT NULL`). The mutator branches: many candidates per parent, most never promoted, and Day-3 shadow forecasts FK to a candidate's lineage row *before* promotion. So a candidate is a lineage row with `version = NULL` until an operator promotes it.

If migration `006` is **not yet applied**, fold this into it. If it **is** applied, add `007_lineage_candidates.sql`:

```sql
-- 007_lineage_candidates.sql
ALTER TABLE skill_lineage ALTER COLUMN version DROP NOT NULL;

-- Drop the linear-history UNIQUE; confirm the auto-generated name first via \d skill_lineage
ALTER TABLE skill_lineage DROP CONSTRAINT skill_lineage_skill_id_version_key;

-- Uniqueness now applies only to promoted (version-assigned) rows
CREATE UNIQUE INDEX skill_lineage_promoted_version
  ON skill_lineage (skill_id, version) WHERE version IS NOT NULL;

ALTER TABLE skill_lineage
  ADD COLUMN status TEXT NOT NULL DEFAULT 'candidate'
    CHECK (status IN ('candidate','shadow','promoted','archived'));

-- Day-1 backfilled manual rows are the live versions
UPDATE skill_lineage SET status = 'promoted' WHERE version IS NOT NULL;
```

Lifecycle: `candidate` (accepted by mutator) → `shadow` (Day 3) → `promoted` (Day 5 operator approval, version assigned) or `archived` (discarded / aged out). `generation_method` (`manual`/`mutated`/`generated`) is orthogonal to `status`.

## 2. Mutator inputs — `agent/evolution/mutator.py`

Assemble three things for the parent skill at its current version.

**Parent source** — full Python of the current promoted lineage row (`status='promoted'`, latest `version`) for `skill_id`; fall back to `agent/modal_skills/<id>/run.py` if no lineage row.

**14-day Brier trajectory** — per-version mean Brier so the model sees whether prior changes helped:
```sql
SELECT f.skill_version,
       AVG(e.brier_contribution) AS mean_brier,
       COUNT(*) AS n_evals
FROM evaluations e
JOIN forecasts f ON f.id = e.forecast_id
WHERE f.skill_id = %(skill_id)s
  AND e.evaluated_at >= %(now)s - INTERVAL '14 days'
GROUP BY f.skill_version
ORDER BY f.skill_version;
```

**3 worst-Brier traces** — the concrete failures, with their detection trace so the model sees *why* they failed, not just that they did:
```sql
SELECT f.id, e.outcome, e.brier_contribution, f.probability, f.trace
FROM evaluations e
JOIN forecasts f ON f.id = e.forecast_id
WHERE f.skill_id = %(skill_id)s
  AND e.evaluated_at >= %(now)s - INTERVAL '14 days'
ORDER BY e.brier_contribution DESC
LIMIT 3;
```

Also pass the **available signal inventory** (distinct `source`, `signal_type` from `signal_catalog`) so the model only references sources that exist.

## 3. LLM call

Sonnet (`claude-sonnet-4-6`, same client as the existing Curator) via structured `tool_use`. Tool `propose_skill_mutation`:

- `mutated_source` (string) — full Python of the rewritten skill.
- `rationale` (string) — what changed and why, grounded in the trajectory and the 3 traces.
- `targets` (array[string], optional) — which aspects changed (e.g. `dbscan_eps`, `probability_map`, `alert_gate`).

System-prompt hard constraints (state them as rules, not suggestions):
- Keep the signature exactly: `run(now: datetime, db: Connection) -> list[Forecast]`.
- **Return** forecasts; never persist. No `INSERT`/`UPDATE`/`DELETE`, no `emit_forecasts`, no file/network/subprocess.
- Only query `source`/`signal_type` values present in the supplied inventory.
- Reasoning generation stays bypassable — do not make an LLM call a hard requirement for emitting a forecast.
- The objective is lower Brier; you may change thresholds, clustering params, geometry buffers, the probability map, and the signal mix.

Budget: one call per skill, ~$0.05–0.15. Sonnet→Haiku fallback per the $5/pass cap.

## 4. Validation pipeline (reject early, cheap → expensive)

Reuse the existing Curator AST validator; extend it. Every rejection records its reason into the proposal's `curator_trace.rejection_reasons`.

1. **AST parse** — candidate must `ast.parse` cleanly.
2. **Signature lock** — `run(now, db) -> list[Forecast]` present and unchanged. Reject any signature change (v3 plan §7 Day 2).
3. **No-op** — normalized AST (strip comments/whitespace/docstrings) must differ from parent. Reject identity. (Curator already does this; reuse.)
4. **No persistence** — AST-walk for any DB write (`INSERT`/`UPDATE`/`DELETE` string literals passed to execute, calls to `emit_forecasts` or the writer). Reject — persistence is not in the mutation surface.
5. **Referenced sources exist** — every `source`/`signal_type` literal the candidate filters on must be in `signal_catalog`. Reject unknown sources (v3 §9 risk).
6. **Import allowlist + dangerous-node ban** — imports restricted to stdlib + the skill's known deps (`psycopg`, `shapely`, `sklearn`, `numpy`, `agent.lib.*`). Reject `os`/`subprocess`/`socket`/`eval`/`exec`/`__import__`/open-for-write and any AST `Call` to them.
7. **Sandbox smoke-run** — load the candidate into an isolated module namespace (not the live skill path) via `importlib`; call `run(t, db)` for one recent `t` through the **window-guarded read-only connection proxy** from the fix ticket. Must: not raise, return `list[Forecast]`, pass the window guard (no leakage / no over-wide window), and emit a non-absurd count (reject if > N× the parent's typical per-tick emission — a cheap forecast-spam tripwire). Capture any traceback into `curator_trace`.

A candidate that clears all 7 is **accepted**. Anything else is rejected with reasons; no rows written for rejects beyond an optional audit log.

## 5. Persist an accepted candidate

One transaction, mind the circular FK between `skill_edit_proposals` and `skill_lineage`:

1. `INSERT skill_edit_proposals (skill_id, current_version, proposed_code, curator_trace, status='pending')` → `proposal_id`. `curator_trace` carries the rationale + the full validation report (which checks ran, any warnings).
2. `INSERT skill_lineage (skill_id, parent_skill_id=skill_id, version=NULL, source_code=mutated, skill_md='', generation_method='mutated', status='candidate', proposal_id)` → `lineage_id`.
3. `UPDATE skill_edit_proposals SET lineage_id = :lineage_id WHERE id = :proposal_id`.

Return a `MutationResult` (accepted bool, proposal_id, lineage_id, rejection_reasons).

> Reuses the existing operator queue (v2 §12: the approval gate is load-bearing; the mutator never auto-deploys). This is the existing Curator contract, with code mutation in place of a parameter tweak.

## 6. Tests / acceptance

`agent/evolution/test_mutator.py`:
- Generate one mutant for `wildfire-risk-elevated`; assert it is accepted, executable for one tick, and that proposal + lineage rows exist and are cross-linked.
- Feed hand-crafted **bad** candidates and assert each is rejected by the right check: a signature change (#2), a no-op (#3), an `INSERT INTO forecasts` (#4), a query on a nonexistent `signal_type` (#5), an `import subprocess` (#6), and a candidate that raises at runtime (#7).
- Assert no `forecasts`/`signals`/`evaluations` rows were written by any of the above.

## Acceptance checklist

- [ ] Lineage schema amended: `version` nullable, partial-unique on promoted rows, `status` column, manual rows backfilled to `promoted`.
- [ ] `mutate_skill` assembles parent source + 14d trajectory + 3 worst traces + signal inventory.
- [ ] Sonnet `tool_use` call returns structured `mutated_source` + `rationale`.
- [ ] All 7 validation stages implemented; each bad-candidate test rejected by the correct stage.
- [ ] Sandbox runs through the window-guarded proxy; no live writes; forecast-spam tripwire active.
- [ ] Accepted candidate → linked `skill_edit_proposals` (pending) + `skill_lineage` (candidate, version NULL).
- [ ] No scoring, no shadow deploy, no promotion in this ticket.

## Out of scope

Backtest scoring / selection (Day 4), shadow deployment (Day 3), Curator orchestration (Day 4), the Generator (deferred v3.1), operator promotion (Day 5).

## Gotchas

- **Validation order is cost order.** AST checks are free; the sandbox run hits the DB and the LLM-bypass path. Don't sandbox a candidate that already failed the signature or persistence check.
- **The no-persistence check is the mutation-surface boundary.** If a mutant smuggles in an `INSERT`, it's not just wrong — it breaks the Day-3 sink swap (production vs `forecasts_shadow` is the caller's decision, not the skill's). Reject hard.
- **`version=NULL` candidates won't collide,** but the partial-unique index means two candidates can't both be promoted to the same version later — that's correct; promotion (Day 5) assigns the next free integer.
- Confirm the dropped UNIQUE constraint's real name via `\d skill_lineage` before writing the `DROP CONSTRAINT`.
- Run from `~/Downloads/envision/`.
