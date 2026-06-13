# v3 Fix — Evolution Loop Recovery: Sandbox Validation + Ground-Truth Integrity

**Status:** Ready for implementation
**Priority:** P0 — the evolution loop has been dead since 2026-06-01, and the fitness signal it will consume on revival is contaminated
**Date:** 2026-06-07
**Supersedes:** `v3_fix_sandbox_validation.md`, `v3_fix_ground_truth_integrity.md` (drafts, merged here)

---

## 1. Symptoms

1. The deployed v3 curator completes its daily pass but rejects 100% of mutants for both targeted skills, every attempt, with the identical opaque reason `sandbox: runtime error in sandbox`. Last log: `targeted=2 mutated=2 accepted=0 shadow=0 spend=$0.54/5.0`.
2. Zero rows written to `backtest_run` since 2026-06-01 09:26 UTC. Zero candidate rows ever written to `skill_lineage` (only the four manual seed rows, all `promoted`).
3. The shadow wildfire and shadow typhoon cycles crash on every cron tick — downstream consequence of the empty shadow candidate set, not an independent fault.
4. Audit (2026-06-07) found the ground_truth table contains heavy duplication of real GDACS events and a residue of v1 seed-demo data inside the fitness signal.

## 2. Root cause analysis

### Track A — the loop is dead

**Bug A1 — the sandbox swallows exceptions (design flaw).** The sandbox validator catches the real exception and reports only a generic string. This blinds the operator, and worse, starves the mutator's retry-with-feedback loop: the LLM is fed "runtime error in sandbox" three times and has zero signal to correct anything. Retries are structurally useless as built. Must be fixed regardless of the underlying cause.

**Bug A2 (primary hypothesis) — the curator's Modal image lacks the detection-skill dependencies.** Evidence: the failure is identical across every attempt and both skills — content-independent, therefore environmental. Validation *passed* during the May 31 – Jun 1 build session (four `backtest_run` rows exist), which ran locally with full dev deps; it has failed on every pass since deployment to Modal. The curator image was presumably specced for the curator's own needs (anthropic, psycopg), not for the code it `exec`s: every wildfire mutant imports `sklearn` and `shapely`, dies at import, and the generic catch hides it. **Secondary hypothesis** if the image checks out: the `db` handle the sandbox passes to `run(now, db)` doesn't match the real connection API, failing every mutant identically on its first query. The surfaced traceback from A1 distinguishes these in one glance — which is why the fix order is mandatory.

### Track B — the fitness signal is dirty

**Bug B1 — GDACS dedup hole (headline).** The v1 dedup trigger keys on `md5(payload)`. GDACS GeoRSS re-publishes the same event on every advisory update with a new `todate` and updated figures, so every update passes dedup. Measured: typhoon JANGMI-26 (eventid 1001272) = **22 rows**; eventid 1001273 = **21 rows** under two names (ONE-E-26 renamed to AMANDA-26 when the depression was named — proof that dedup must key on `eventid`, never `eventname`); wildfires typically 2–3 rows each. Retained indefinitely. Why it matters: `backtest_run` records `misses` and the mutator consumes hits/misses as failure context — if miss-counting is per GT row, one duplicated typhoon scores as 22 misses, demolishing typhoon candidate fitness and prompting the mutator to fix a fictional failure. Successively extended `todate` windows also widen the intervals a forecast can spuriously match in live evaluation.

**Bug B2 — seed residue (smaller than feared).** Signals: clean (exactly 1 backdated row table-wide; seeded signals already gone). Evaluations: 54 fake rows inside the 14d curator window — 41 for `wildfire_risk_elevated` (≈1.2% of its 3,539-eval pool, negligible) but 13 for `wildfire_rapid_growth` (≈20% of its 66, materially distorting its worst-K ranking at engineered Briers of ~0.18–0.21). These self-expire from the trailing window by ~2026-06-11. Seeded forecasts persist (60d retention). Seeded ground_truth rows are payload-indistinguishable from real GDACS rows but exactly enumerable via the `matched_ground_truth_id` FK chain.

**Bug B3 — history has three independent corruptions** for backtest purposes: the seed era (~05-22→05-28), the ingestion outage (05-29→06-03 07:34, confirmed as a gap in signals), and the v2-refactor-inconsistent history already documented in the addendum §3.

## 3. Scope of work

### W1 — Surface the real sandbox exception (do first, deploy alone)

In `agent/evolution/sandbox.py` (or wherever the catch lives):

- Replace the generic rejection string with `f"sandbox: {type(e).__name__}: {e}"` plus a traceback truncated to the last N frames / ~2KB.
- Propagate the full reason into: (a) the mutator's retry-feedback prompt, (b) the curator log line, (c) `curator_trace.rejection_reasons` on any proposal row written. Truncate before the trace builder so the 16KB `trace_size_cap` is respected.
- Deploy W1 alone, trigger one manual curator pass (`modal run`), and read the now-specific rejection reason before touching anything else. Proceed on the traceback, not on assumption.

### W2 — Unify the skill-execution image

Skill code now executes in four places — detection apps, the curator's sandbox, the backtest harness, and the shadow runners — and must not have independently-maintained images; this incident is the first drift casualty and the shadow runners are suspect for the same reason.

- Extract a single shared image definition (e.g. `agent/lib/skill_image.py` exposing `SKILL_EXEC_IMAGE`) containing everything the detection skills import: `scikit-learn`, `shapely`, `psycopg`, `httpx`, plus anything else found by auditing the four detection skills' imports.
- All four execution contexts import this one definition; detection apps may layer extras on top, but the base is shared. `grep` should find no second image spec for skill execution.
- Audit the shadow runner apps against it while in there — deployed in the same window, likely same gap.

### W3 — Sandbox DB isolation

Confirm what the sandbox's `db` parameter connects to. If production Neon: LLM-written candidate code is executing arbitrary queries against prod. Floor: wrap each sandbox execution in a transaction unconditionally rolled back, or connect via a read-only role. Same risk class as the test-fixture incident covered by `.cursor/rules/test-db-isolation.mdc`; extend that rule's spirit to the sandbox.

### W4 — Shadow runner and selector empty-set no-op (shippable immediately)

The shadow runner must treat zero rows with `status='shadow'` as a clean logged no-op (`[shadow] no candidates, exiting`), not an exception — "no candidates this pass" is a legitimate steady state. Apply the same guard to the selector when zero candidates survive.

### W5 — Seed purge

Identification is exact, not heuristic — seeded forecasts carry the fake version history and pre-date live v3 operation:

```sql
-- Enumerate seeded forecasts (verify count ≈ 34–68 before deleting)
SELECT id FROM forecasts WHERE issued_at < '2026-05-29'
  AND skill_id IN ('wildfire_risk_elevated', 'wildfire_rapid_growth');

-- Their evaluations follow by FK (forecast_id); their seeded ground_truth rows by:
SELECT DISTINCT e.matched_ground_truth_id
FROM evaluations e JOIN forecasts f ON f.id = e.forecast_id
WHERE f.issued_at < '2026-05-29' AND e.matched_ground_truth_id IS NOT NULL;
```

Delete order: evaluations → forecasts → enumerated ground_truth rows → the 5 seeded `skill_edit_proposals` if still present (match on the v1 narrative: DBSCAN eps 15→10, threshold 1.3x→1.5x, etc.). Wrap in a transaction; print counts before commit. Real forecasts may also exist before 05-29 — verify counts against expected seed volumes (34 forecasts per run, possibly ×2); if wildly off, stop and inspect. **Run W5 before W6's collapse migration** so the collapse never elects a seeded row as survivor.

### W6 — GDACS natural-key dedup (migration 007)

- Replace md5-payload dedup for `ground_truth` with a natural key on `(source, payload->>'eventid')`: extracted/generated `event_key` column + unique index + `INSERT ... ON CONFLICT` upsert in the GDACS poller — a new advisory **updates** the existing row (latest `todate`, latest payload, geometry) rather than inserting.
- `occurred_at` stays at the event's earliest known `fromdate`; advisory updates must not push the event start forward.
- Rows with NULL/absent `eventid` fall back to md5 dedup (don't crash on malformed feed items). The md5 trigger remains unchanged for `signals`.
- **One-time collapse migration:** per `(source, eventid)` group, keep one row (latest `todate`, earliest `fromdate` as `occurred_at`), delete the rest — repointing any `evaluations.matched_ground_truth_id` referencing a deleted duplicate to the survivor first (FK integrity).

### W7 — `BACKTEST_EPOCH` floor

- Define `BACKTEST_EPOCH = datetime(2026, 6, 4, 0, 0, tzinfo=UTC)` once, in `agent/lib/` or `agent/evolution/` constants — the first full day after ingestion restoration, fixture cleanup, and the seed era.
- The backtest harness hard-rejects any window with `window_start < BACKTEST_EPOCH` (raise, don't silently clamp); the selector only draws windows inside the epoch.
- This single constraint fences all three history corruptions (B3) regardless of purge completeness, and defines the clean window required to eventually revalidate the ±0.02 sanity gate (addendum §3).
- Document in `METHODS.md`: backtest fitness is computed only on post-epoch history.

### W8 — Scoring semantics audit

- Audit `agent/lib/scoring.py` and the harness's miss-counting: per ground_truth row, or per distinct event? After W6 the distinction collapses, but confirm nothing else assumes duplicates.
- Verify live evaluator matching is unaffected by upsert semantics (a forecast matching an event whose `todate` later extends should not be re-evaluated or double-counted).

## 4. Sequencing

1. **W1** (exception surfacing) — deploy alone, `modal run` curator, read the traceback. Record it in closeout notes.
2. **W4** (empty-set no-ops) — in parallel with W1; stops the crash noise immediately.
3. **W2** (shared image) — or the secondary fix if the traceback implicates the db handle — redeploy, `modal run` curator, confirm a mutant passes sandbox and reaches backtest.
4. **W3** (sandbox DB isolation) — alongside W2 while in the sandbox code.
5. **W5** (seed purge, transaction, count-verified) → **W6** (migration 007 + collapse) → **W7** (epoch floor) → **W8** (audit).
6. Deploy updated GDACS poller; observe one real cycle produce upserts, not inserts.

Rationale for the order: Track A revives the machinery, Track B cleans the signal it consumes. Candidates produced before Track B lands inherit dirty typhoon miss counts and `rapid_growth`'s contaminated ranking — so the first evolution pass worth judging is the one that runs after **both** tracks are deployed.

## 5. Acceptance criteria

1. Any sandbox rejection logs a specific exception type and message; the same text appears in the mutator retry prompt and `curator_trace.rejection_reasons`.
2. A manual curator pass produces ≥1 mutant passing sandbox validation and reaching backtest — fresh `backtest_run` rows (`run_at` > deploy time) and ≥1 candidate row in `skill_lineage`.
3. One shared skill-execution image definition; `grep` finds no second image spec for skill execution.
4. Sandbox executions cannot persist writes to prod (verified by a deliberate write attempt in a test candidate).
5. Shadow runner and selector exit 0 with a log line on empty candidate sets; no crashes in Modal for 24h post-deploy.
6. Post-W6: `SELECT payload->>'eventid', count(*) FROM ground_truth GROUP BY 1 HAVING count(*) > 1` returns zero rows (excluding NULL-eventid fallbacks); a simulated poller run over an updated advisory produces an UPDATE, not an insert, with `occurred_at` unchanged.
7. Post-W5: zero forecasts with the fake version history remain; deletion counts logged and matching expected seed volumes; no orphaned `matched_ground_truth_id` after the collapse (FK check passes).
8. A pre-epoch backtest window raises immediately with a clear message; post-epoch windows run normally; exactly one epoch constant definition exists.
9. `wildfire_rapid_growth`'s 14d Brier recorded pre- and post-purge in closeout notes — quantifies what the contamination cost.
10. Budget: pass spend stays within the $5 cap; note that functional retry feedback may slightly *increase* per-pass spend (retries now do useful work).

## 6. Non-goals

- Revalidating the ±0.02 backtest sanity gate (W7 creates the precondition — a defined clean epoch — but revalidation waits for sufficient post-epoch history).
- JTWC year-parse fix (separate ticket; typhoon *signals*, not ground truth — explains zero typhoon evolution targeting, which is expected given zero typhoon evaluations).
- Signals-table dedup changes (md5 dedup stays; it works for signals).
- Generator, diversity penalty, tiered auto-approve (v3.1).
- Mutator prompt or acceptance-contract changes beyond inserting real error feedback.

## 7. Context for Cursor

Relevant files: `agent/evolution/sandbox.py`, `agent/evolution/mutator.py`, `agent/evolution/backtest_harness.py`, `agent/evolution/selector.py`, curator and shadow-runner Modal apps under `agent/modal_skills/`, `agent/modal_skills/gdacs-ground-truth/`, `agent/lib/forecast_writer.py`, `agent/lib/scoring.py`, `db/migrations/` (next number is **007** — verify with `ls db/migrations/` per standing rule), `tools/seed_demo_data.py` (reference for seed shapes; do not run it), `docs/METHODS.md`, `.cursor/rules/test-db-isolation.mdc`.

Keep in context: `v3_plan.md`, `PROGRESS_v3_addendum.md`, this ticket.

Standing learnings that apply: feed the mutator the surface only; Modal secret recreate is destructive; `signal_catalog` is a materialized view; all PostGIS inserts via `ST_Force2D`; tests never write to prod DB; migration numbers verified by listing the directory, never assumed from docs.
