# Envision v3 — Day 3 Ticket: Selector + Shadow Deployment

**Goal:** rank validated candidates by cross-window backtest Brier, advance the qualifying top-K to a *shadow* deployment that runs at live cadence into `forecasts_shadow`, and extend the evaluator to score those shadow forecasts so a live shadow-Brier accumulates. No promotion to production — that's operator-gated (Day 4/5).

**Canonical context:** `docs/v3_plan.md` (§5, §7 Day 4, §9), `docs/v3_day1_ticket.md` (§3 writer, §5 harness), `docs/v3_day2_ticket.md` (lineage), `docs/v3_fix_backtest_window.md`, `agent/evolution/backtest_harness.py`, `agent/evolution/mutator.py`, `agent/lib/forecast_writer.py`, `agent/lib/scoring.py`, `agent/modal_skills/forecast-evaluator/run.py`, `viewer/lib/queries.ts`.

---

## Dependencies & build order

- **Selector (§2) is blocked on the harness fix.** Do not trust any selection until `v3_fix_backtest_window.md` passes its ±0.02 gate for all 4 skills. Selection on a leaky harness promotes false-positive machines.
- **Shadow plumbing (§3–§5) is independent** — it runs on live cadence and the real evaluator. Build and test it now by manually setting a candidate's `skill_lineage.status='shadow'`; wire the selector's output into it once the harness is green.
- This ticket touches the live evaluator (§5). Same regression discipline as Day-1 §4: live `evaluations` output must be byte-identical before/after.

---

## 1. Migration — `shadow_evaluations`

`evaluations.forecast_id` FKs to `forecasts(id)`; shadow forecasts are in `forecasts_shadow`. Scoring them needs a mirror, not a change to the live table.

Verify the next number (`ls db/migrations/`); fold into the Day-2 amendment if unapplied, else new file:

```sql
CREATE TABLE shadow_evaluations (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shadow_forecast_id    UUID NOT NULL REFERENCES forecasts_shadow(id),
    matched_ground_truth_id UUID REFERENCES ground_truth(id),
    outcome               TEXT NOT NULL,
    brier_contribution    DOUBLE PRECISION NOT NULL,
    evaluated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_shadow_eval_fc ON shadow_evaluations (shadow_forecast_id);
```

## 2. Selector — `agent/evolution/selector.py`

Inputs: accepted candidates (`skill_edit_proposals.status='pending'` with `skill_lineage.status='candidate'`) and their parents.

**Windows.** Construct ≥3 **disjoint** windows over the accumulated signal range (no temporal overlap — this is the overfit guard). Each window must contain ≥ `MIN_GT_EVALS` ground-truth-scorable forecasts. If fewer than 3 such windows exist, **refuse**: return empty, log `WARN: insufficient ground truth for cross-window selection`. Do not select on noise.

**Per candidate.** Backtest candidate and parent over the same windows via `backtest_skill(skill_id, windows, db, run_fn=<candidate run>)` (Day-1 §5 `run_fn` override). Load the candidate's `run()` from `skill_lineage.source_code` through the Day-2 sandbox loader (isolated namespace, no Modal import). Persist `backtest_run` rows for both, tagged with `lineage_id`.

**Qualification (all of):**
- `improvement_i = brier(parent, W_i) − brier(candidate, W_i) ≥ NOISE_FLOOR` (0.03) in **every** window `W_i`, not just on the mean (v3 §9 — require improvement in all windows).
- No window degenerate (candidate emitted 0 forecasts across all windows → disqualify; it's not detecting).

**Select.** Among qualifiers, rank by `mean(improvement_i)`; take **top-K = 3**. (Diversity penalty cut per cut-list #2 — plain top-K.)

Non-qualifying candidates stay `candidate` (logged why); the operator gate is never bypassed by auto-rejection.

## 3. Writer extension — emit to the shadow sink

Day-1 §3 promised shadow deploy as a sink swap. Extend `emit_forecasts` minimally:

```python
def emit_forecasts(forecasts, db, *, table="forecasts", lineage_id=None) -> int:
    # table="forecasts_shadow" → require lineage_id; status defaults to 'evaluating' (table default)
    # table="forecasts"        → lineage_id ignored (no such column on live forecasts)
```

The writer stays non-mutable. `forecasts_shadow` rows carry `lineage_id` (shadow candidates have `version=NULL`, so the live `(skill_id, version)` join can't identify them — `lineage_id` is the link).

## 4. Shadow runner — `agent/evolution/shadow_runner.py` (Modal cron)

Do **not** deploy a Modal function per candidate. One generic runner, bucketed by cadence:

- On each tick, load all `skill_lineage` rows with `status='shadow'` whose parent skill matches this cadence bucket (30 min / 3 h).
- For each: compile `source_code`, call `run(now, db)` (directly — the surface has no entrypoint per the mutator fix), then `emit_forecasts(forecasts, db, table="forecasts_shadow", lineage_id=<id>)`.
- **Volume guard:** cap per-tick emissions per lineage at `SHADOW_RATE_LIMIT`; record the per-tick forecast-count distribution (into `forecasts_shadow.trace` or a small log). A candidate that hits the cap is flagged `pathological` for operator review (v3 §9 forecast-spam risk) — capped, not silently dropped.
- Register two crons (`*/30 * * * *`, `0 */3 * * *`) matching the existing detection cadences.

## 5. Evaluator extension — score the shadow sink

Extend `forecast-evaluator` to also scan expired `forecasts_shadow` rows (`shadow_promotion_status='evaluating'`) and match them against `ground_truth` using the **same `agent/lib/scoring.py`** functions. Write results to `shadow_evaluations`.

- The evaluator stays the single hardcoded component (v2 §12 anti-dependency). It now scores two sinks with one matching path; it is not made per-skill configurable.
- **Regression gate:** live `evaluations` output byte-identical before/after the extension. The change is purely additive (a second scan into a second table).

Shadow Brier-so-far readout (for the Day-4 review surface and the N≥20 gate):

```sql
SELECT fs.lineage_id,
       AVG(se.brier_contribution) AS shadow_brier,
       COUNT(*)                   AS n_evals
FROM shadow_evaluations se
JOIN forecasts_shadow fs ON fs.id = se.shadow_forecast_id
WHERE fs.shadow_promotion_status = 'evaluating'
GROUP BY fs.lineage_id;
```

A candidate becomes *promotion-eligible* at `n_evals ≥ 20` AND shadow_brier beating the parent's live Brier by ≥ `NOISE_FLOOR` — but the promotion **decision is operator-gated** (Day 4/5). Day 3 only exposes the numbers.

## 6. Public-viewer guardrail

`forecasts_shadow` must never reach the public map. The public routes (`/`, `/forecast/[id]`) query `forecasts` only. Add a test asserting no query reachable from a public route references `forecasts_shadow`. Operator-facing display of shadow rows is Day 4 (`/agent`), not now.

## Tests / acceptance

- `test_selector_requires_improvement_in_all_windows` — a candidate that beats the parent in 2 of 3 windows but not the 3rd is rejected.
- `test_selector_refuses_on_thin_ground_truth` — fewer than 3 qualifying windows → empty result + WARN, no shadow promotion.
- `test_selector_topk` — given >3 qualifiers, exactly the 3 best by mean improvement advance.
- `test_emit_shadow_requires_lineage_id` — `table="forecasts_shadow"` without `lineage_id` raises; rows land with `shadow_promotion_status='evaluating'` and the lineage_id set.
- `test_shadow_runner_rate_limit` — a spammy candidate is capped and flagged `pathological`, not allowed to flood `forecasts_shadow`.
- `test_evaluator_live_unchanged` — live `evaluations` diff empty before/after; `shadow_evaluations` populated for expired shadow forecasts.
- `test_public_routes_never_query_shadow` — static check over public-route queries.

## Out of scope

Operator review surface + the promotion decision (Day 4), Curator orchestration (Day 4), the Generator (v3.1), diversity penalty (cut #2).

## Gotchas

- **Selection is meaningless until the harness gate is green.** Gate this ticket's selector acceptance on `v3_fix_backtest_window.md` passing. Build the plumbing first if the fix is still in flight.
- **`lineage_id`, not `(skill_id, version)`, identifies shadow forecasts** — candidates are `version=NULL`. Don't try to join shadow rows on version.
- **Disjoint windows are the overfit guard** — overlapping windows let one good period carry a bad candidate. Assert disjointness when constructing them.
- **Cold-start is expected**, not a bug. With ~a week of data the selector will often refuse. That's the system declining to promote on noise; let it.
- **Run `run()` directly in the shadow runner** — the mutation surface has no entrypoint (mutator fix §2), so there's nothing that calls `emit_forecasts` inside it; the runner is the caller.
- Run from `~/Downloads/envision/`.
