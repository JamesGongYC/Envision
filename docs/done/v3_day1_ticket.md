# Envision v3 — Day 1 Ticket: Migration 005 + Backtest Harness

**Goal:** Land the evolution-loop database tables and a backtest harness that can replay a detection skill over historical signals and score it against `ground_truth` using the *same* matching logic as the live evaluator — with zero leakage and zero pollution of live tables.

**Canonical context (load these into the Cursor session):**
`docs/v3_plan.md`, `docs/v2_plan.md` (§12 dependency contract), `docs/PROGRESS.md` (v2.5 closeout), `db/schemas.py`, `db/migrations/004_v2_additions.sql`, `agent/modal_skills/forecast-evaluator/run.py`, `agent/modal_skills/wildfire-risk-elevated/run.py`, `agent/lib/trace_builder.py`.

---

## Scope

1. Migration `006_evolution.sql` (verify number — see §1).
2. New `db/schemas.py` dataclasses for the new tables.
3. Refactor detection skills to pure `run(now, db) -> list[Forecast]`; move persistence into a non-mutable writer.
4. Extract live evaluator matching into a shared pure module.
5. `agent/evolution/backtest_harness.py` + skill loader.
6. Sanity test proving the harness reproduces live Brier within ±0.02.

**Out of scope (do not build):** Mutator, Generator, Selector, shadow *deployment*, any LLM calls, any `/agent` changes. `forecasts_shadow` is created in the migration but stays empty until Day 3.

---

## 1. Migration `006_evolution.sql`

> **Numbering — verify first.** `v3_plan.md §6` says `004_evolution.sql`; that's taken (`004_v2_additions.sql`). The v2.5 consolidation sprint likely added a `005`. **Run `ls db/migrations/` and use max + 1.** Per current repo state that's **006**; this ticket assumes 006 throughout — adjust if `005` turns out to be free.

Create three tables and one FK. Mirror `forecasts` for the shadow table via `LIKE ... INCLUDING` so the 0.85 probability CHECK, the `trace` JSONB column, and the `gen_random_uuid()` default all carry over automatically.

```sql
-- 006_evolution.sql

-- Genealogy: every skill version, manual or machine-generated.
CREATE TABLE skill_lineage (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id          TEXT NOT NULL,                 -- canonical, e.g. 'wildfire-risk-elevated'
    parent_skill_id   TEXT,                          -- NULL for de-novo generated
    version           INTEGER NOT NULL,
    source_code       TEXT NOT NULL,                 -- full Python
    skill_md          TEXT NOT NULL DEFAULT '',
    generation_method TEXT NOT NULL DEFAULT 'manual'
        CHECK (generation_method IN ('manual','mutated','generated')),
    proposal_id       UUID REFERENCES skill_edit_proposals(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (skill_id, version)
);

-- One row per (skill, version, window) backtest. Aggregate only; no per-forecast rows.
CREATE TABLE backtest_run (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id          TEXT NOT NULL,
    version           INTEGER,                       -- NULL for an un-promoted candidate
    lineage_id        UUID REFERENCES skill_lineage(id),
    window_start      TIMESTAMPTZ NOT NULL,
    window_end        TIMESTAMPTZ NOT NULL,
    brier_score       DOUBLE PRECISION,              -- NULL if no scorable forecasts
    hits              INTEGER NOT NULL DEFAULT 0,
    false_positives   INTEGER NOT NULL DEFAULT 0,
    misses            INTEGER NOT NULL DEFAULT 0,
    forecasts_emitted INTEGER NOT NULL DEFAULT 0,
    run_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_backtest_run_skill ON backtest_run (skill_id, version);

-- Shadow forecasts: structural mirror of forecasts + promotion status. Empty until Day 3.
CREATE TABLE forecasts_shadow (
    LIKE forecasts INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES
);
ALTER TABLE forecasts_shadow
    ADD COLUMN shadow_promotion_status TEXT NOT NULL DEFAULT 'evaluating'
        CHECK (shadow_promotion_status IN ('evaluating','promoted','discarded')),
    ADD COLUMN lineage_id UUID REFERENCES skill_lineage(id);

-- Tie existing proposal queue into lineage.
ALTER TABLE skill_edit_proposals
    ADD COLUMN lineage_id UUID REFERENCES skill_lineage(id);
```

Backfill a `skill_lineage` row (`generation_method='manual'`) for each of the 4 current detection skills at their current version, so mutants have a parent to point at. Pull current source from `agent/modal_skills/<id>/run.py`. This can be a one-off script `agent/evolution/backfill_lineage.py` rather than SQL.

**Verify:** `\dt` shows the 3 new tables; `\d forecasts_shadow` shows the inherited 0.85 CHECK and the `trace` column plus the two added columns.

---

## 2. `db/schemas.py` additions

Add `SkillLineage`, `BacktestRun`, `ShadowForecast` mirroring the SQL. Keep the existing style. `BacktestRun.brier_score` is `float | None`.

---

## 3. Skill refactor — pure `run()` + non-mutable writer

**Decision:** detection skills currently `INSERT INTO forecasts` and return a count. Refactor each to a pure function and lift persistence into a writer that the mutator cannot reach. This is the v2 §12 contract finally honored, and it makes Day 3 shadow deploy a one-line sink swap.

- **Skill becomes:** `run(now: datetime, db: Connection) -> list[Forecast]`. It queries `signals WHERE timestamp <= now`, computes detections, attaches reasoning, and **returns** `Forecast` objects. No `INSERT`. Reasoning generation (Sonnet) stays *inside* `run()` — it's detection-domain and a legitimate future mutation target — but must be bypassable (harness guard #3 handles this).
- **New writer `agent/lib/forecast_writer.py`:** `emit_forecasts(forecasts, db, *, table="forecasts") -> int`. Owns everything persistence-side that was previously inline: the `INSERT`, the `ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(...), 4326))` geometry boundary, `trace` JSONB write, `contributing_signal_ids`, dedup interaction. Returns the row count (preserves the old call-site contract). Lives in `agent/lib/` — **not** mutation surface, so the 0.85 cap, trace integrity, and sink choice are never things an LLM-generated mutant controls.
- **Production wiring:** each skill's Modal entrypoint becomes `emit_forecasts(run(now, db), db)`. External behavior (rows landing in `forecasts`) is unchanged.
- **Signature is now canonical.** Day 2's mutator rejects any `run()` signature change against this.
- **Day 3 payoff:** shadow deploy = `emit_forecasts(run(now, db), db, table="forecasts_shadow")`. Nothing in the skill changes.

**Regression gate (hard pass/fail):** run all 4 skills in production mode (`emit_forecasts(run(...), db)`) against the live DB before and after the refactor; the emitted forecast rows must match — same count, geometries, probabilities, `contributing_signal_ids`, `trace`. Diff and treat any difference as failure. This plus the evaluator extraction (§4) are the two risky edits in the ticket.

---

## 4. Shared scoring module — `agent/lib/scoring.py`

The harness must score with the **same** logic as the live evaluator, not a reimplementation (drift here makes every backtest number a lie). Extract — don't fork.

- Pull the matching predicate and Brier-contribution math out of `agent/modal_skills/forecast-evaluator/run.py` into two pure functions:
  - `match_forecast_to_truth(forecast, ground_truth_rows, *, grace_hours=12) -> GroundTruthEvent | None` — class alias handling (wildfire/WF/fire, typhoon/TC/cyclone), geometry intersection, time overlap.
  - `brier_contribution(forecast, matched) -> tuple[outcome: str, contribution: float]` — `'hit' | 'miss' | 'false_positive'`.
- Refactor `forecast-evaluator/run.py` to import from `agent/lib/scoring.py`. **No behavior change.**

> **Anti-dependency (v2 §12):** the evaluator stays a single hardcoded component the mutator cannot reach. Extracting matching into `agent/lib/scoring.py` is fine — `agent/lib/` is not mutation surface. Do **not** make scoring configurable per-skill.

**Regression gate:** run the live evaluator once before the refactor and once after against the same DB snapshot; the rows written to `evaluations` must be byte-identical (same outcomes, same `brier_contribution` values). Capture both as CSV and diff. This is the one risky edit in the ticket — treat the diff as a hard pass/fail.

---

## 5. `agent/evolution/backtest_harness.py`

Create `agent/evolution/__init__.py` and the harness.

### Skill loader
Import the pure `run(now, db)` from `agent/modal_skills/<id>/run.py` **without** importing `app.py` (no Modal runtime). Use `importlib.util.spec_from_file_location` to load `run.py` by path and grab its `run` attribute. A `SKILL_CADENCE` dict (sourced from the cron table in PROGRESS §7) maps skill_id → step interval:

```python
SKILL_CADENCE = {
    "wildfire-risk-elevated":      timedelta(minutes=30),
    "wildfire-rapid-growth":       timedelta(minutes=30),
    "typhoon-intensifying":        timedelta(hours=3),
    "typhoon-landfall-imminent":   timedelta(hours=3),
}
```

### Public API
```python
def backtest_skill(
    skill_id: str,
    windows: list[tuple[datetime, datetime]],
    db: Connection,
    *,
    version: int | None = None,
    run_fn: Callable | None = None,   # override for an un-promoted candidate's source
) -> list[BacktestRun]:
    ...
```

### Replay loop (per window)
For `t` walking from `window_start` to `window_end` at `SKILL_CADENCE[skill_id]`:
1. Call `run_fn(t, db)` (default: the skill's own `run`). Collect emitted `Forecast` objects **in memory**.
2. After the window completes, score the collected forecasts against `ground_truth` rows (loaded once for the window) using `agent/lib/scoring.py`.
3. Aggregate hits / false_positives / misses / mean Brier → one `BacktestRun` row.

### Three guards — all non-negotiable

1. **No live writes.** Skills now *return* `list[Forecast]` and never persist (§3); the harness simply does not call `emit_forecasts`. Forecasts live in a Python list for the window. The harness must never execute `INSERT INTO forecasts` / `signals` / `evaluations` / `ground_truth`. Persist only `backtest_run` rows.

2. **Temporal cutoff.** Skills already query `signals WHERE timestamp <= :now` per the v2 contract, so passing `now=t` is the primary guard. Add a **post-hoc leakage audit**: for every emitted forecast, assert no `contributing_signal_ids` references a `signals` row with `timestamp > t`. Any violation aborts the run loudly with the offending skill_id/t. This catches a skill that silently broke the contract.

3. **LLM bypass.** Detection skills generate Sonnet reasoning per forecast (v2.5) with template fallback on API failure. The harness forces the template path by neutralizing the Anthropic client before the replay loop — monkeypatch the client factory the skills use so the reasoning call raises, triggering the existing fallback. Backtest emits no LLM calls, stays deterministic, and costs nothing. Brier is unaffected (it never reads `reasoning`). Add an assertion that zero Anthropic calls fired during a backtest.

---

## 6. Sanity test — acceptance criterion

`agent/evolution/test_backtest_sanity.py` (script, not a unit-test framework unless trivial):

- Backtest `wildfire-risk-elevated` at current version over the **trailing 7 days** as a single window against the accumulated real `signals` + `ground_truth`.
- Compute aggregate Brier from the returned `BacktestRun`.
- Pull the live trailing-7d Brier for the same skill/version from `evaluations`.
- **Pass condition: `abs(backtest_brier - live_brier) <= 0.02`.** Print both numbers and the delta.

Tolerance rationale (document in the script header): live evals apply a 12h grace and depend on ground-truth arrival timing; the backtest replays the same data deterministically, so close-but-not-identical is expected. >0.02 means the harness diverges from the evaluator (likely a scoring-extraction bug or a leakage/cutoff error) and Day 2 must not proceed.

---

## Acceptance checklist

- [ ] `006_evolution.sql` applied; `skill_lineage`, `backtest_run`, `forecasts_shadow` present; `forecasts_shadow` inherited the 0.85 CHECK + `trace` column; `skill_edit_proposals.lineage_id` exists.
- [ ] Lineage backfilled for all 4 detection skills at current version.
- [ ] Detection skills refactored to pure `run() -> list[Forecast]`; persistence in `agent/lib/forecast_writer.py`; before/after production-emission diff is empty for all 4.
- [ ] `forecast-evaluator` refactored onto `agent/lib/scoring.py`; before/after `evaluations` diff is empty.
- [ ] Harness loads `run` from `run.py` without importing Modal.
- [ ] No-live-write, temporal-cutoff audit, and LLM-bypass guards all enforced and individually tested.
- [ ] Sanity test prints backtest vs live Brier with delta ≤ 0.02.

## Gotchas (carry-in)

- **Run from `~/Downloads/envision/`**, not `~/envision/`.
- `forecasts_shadow` empty after this ticket — that's correct; Day 3 fills it.
- `gen_random_uuid()` requires pgcrypto — already enabled in `001_init.sql`.
- Skills import `agent/lib/trace_builder.py`; the standalone import path in the loader must put repo root on `sys.path` or the harness will fail on the skill's own imports.
- Local backtest reads Neon directly via `DATABASE_URL` (psycopg). No Modal needed for Day 1.
