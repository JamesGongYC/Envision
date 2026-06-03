# Envision v3 — Day 4 Ticket: Orchestration + Operator Surface + Closeout

**Goal:** rewire the daily Curator into the full evolution loop (pick worst skills → mutate → select → shadow), give the operator a CLI surface to review and promote candidates with a hard human gate before production, do the first end-to-end real run, and close out the docs.

**Canonical context:** `docs/v3_plan.md` (§5, §6 Day 6–7, §9, §10), `docs/v3_day1..3_ticket.md`, the two fix tickets, `agent/modal_skills/curator/scripts/run_curator.py`, `agent/evolution/{mutator,selector,shadow_runner}.py`, `tools/review_proposals.py`, `tools/check_status.py`, `docs/{METHODS,SAFETY}.md`, `viewer/app/about/page.tsx`.

---

## Dependencies & gating

- **The first real run (§5) is gated on both fixes being green:** the harness window fix (or selection is garbage) and the mutator acceptance fix (or the loop produces no candidates). Build the orchestration now; run it for real only once both pass.
- Orchestration and the operator CLI (§2–§4) are buildable and testable with stubs regardless.

---

## 1. Automation boundary (the rule everything else obeys)

```
pick worst skills → mutate → validate → backtest-select → SHADOW      ← automatic (kill switch + validation gate only)
                                          ───────────────────────
SHADOW → operator review → PROMOTE to production                       ← human gate, never automated
```

Shadow is a parallel sink the public never sees; advancing to it is safe to automate. Promotion writes production code, so it is operator-only. **No evolution component ever writes the production skill file or runs `modal deploy`.**

## 2. Curator orchestration rewire — `curator/run_curator.py`

The v2.5 Curator proposed parameter tweaks directly. v3 **subsumes** that (param tweaks are a strict subset of code mutation, v3 §10). Replace its proposal-generation body with the loop; archive the old param-tweak path so it doesn't double-propose.

Daily pass:
1. If `ENVISION_CURATOR_ENABLED` is false → exit. (Kill switch halts *evolution only*; ingestion, detection, evaluation continue.)
2. **Pick worst-K skills** (K=3): rank by current-version 14d live Brier desc; tie-break by spread (current vs best historical version). These are the "improvement opportunities."
3. For each, `mutate_skill(skill_id, db)` → pending proposals + candidate lineage rows.
4. Run `selector` over all new candidates → qualifying top-K advance to `status='shadow'` (or none, on thin data).
5. **Weekly generator hook:** stub only — log `generator deferred to v3.1`, no-op. (Cut-list #1.)
6. Write a `curator_trace` pass summary: skills targeted, candidates produced/accepted/selected, cost.

**Budget:** enforce the $5/pass cap *in-pass*, not just observe it. Track spend across mutator retries × skills; switch Sonnet→Haiku as the cap nears, then stop. Record cost in `curator_trace`.

## 3. Operator review surface — extend `tools/review_proposals.py`

`list` — for each pending/shadow candidate show: backtest mean Brier vs parent, per-window Briers, shadow `n_evals / 20`, shadow Brier-so-far, and a **`blocked_on`** reason so cold-start is legible — e.g. `windows: insufficient ground truth`, `evals 4/20`, `backtest pending harness`, `no improvement in window 2`. The operator must be able to see *why* nothing is promotable, not just an inert button.

`show <proposal_id>` — full source **diff** (parent surface vs candidate surface from `skill_lineage.source_code`), rationale, validation report, backtest + shadow numbers.

`promote <proposal_id>` — the human gate. Preconditions: shadow `n_evals ≥ 20` AND shadow Brier beats parent live Brier by ≥ `NOISE_FLOOR`. If unmet, **refuse** (override only via explicit `--force` + typed confirmation; default is refuse). On promote:
- assign `version = parent + 1`, `skill_lineage.status='promoted'`; `skill_edit_proposals.status='approved'`; that lineage's `forecasts_shadow` rows → `shadow_promotion_status='promoted'`; stop its shadow run.
- compose the production file (mutation surface + fixed scaffolding) and write it to an output path; **print the manual `modal deploy` command**. Do not deploy — file deployment stays the intentional manual gate (PROGRESS §7).

`discard <proposal_id>` — `status='rejected'`, lineage `archived`, shadow rows `discarded`, shadow run stopped.

## 4. No tiered auto-approve

v3 §9 floats auto-approving parametric edits to manage backlog. **Not in v3.0.** Auto-approving self-rewritten code contradicts the load-bearing operator gate (v2 §12). Everything is human-gated to production. Document the deferral in SAFETY.md.

## 5. First end-to-end real run + guardrail tuning

Trigger one full pass on accumulated real data with the kill switch on.

**Success = a clean loop, not a promotion.** Verify:
- mutator produces ≥1 validated candidate;
- selector scores across disjoint windows **or** cleanly refuses on thin ground truth — no crash either way;
- shadow plumbing emits to `forecasts_shadow` and the evaluator scores into `shadow_evaluations` with no FK errors;
- no writes to live `forecasts` from any evolution component;
- $5 cap respected;
- the pass **correctly declines to promote** on thin data.

Observe for pathologies (zero-forecast candidates, runaway probabilities, forecast spam) and tune the placeholders: Day-2 spam tripwire `N×`, `NOISE_FLOOR`, `MIN_GT_EVALS`, `MAX_ATTEMPTS`. Do **not** tune thresholds down to force a promotion.

## 6. Documentation closeout

- `METHODS.md` — the v3 loop: mutate → AST/sandbox validate → cross-window backtest → top-K select → shadow → operator gate → promote. Name every gate.
- `SAFETY.md` — new gates (validation, cross-window selection requiring improvement in all windows, shadow observation, N≥20 + noise-floor promotion eligibility, operator promotion gate, manual deploy); kill-switch semantics (halts evolution only); tiered auto-approve explicitly deferred.
- `viewer/app/about` — plain language: "the system proposes and tests changes to its own detection code; a change reaches the public map only after backtesting, a shadow trial, and human approval." Reaffirm the experimental / not-an-alerting-service disclaimer — self-evolution makes that framing more important, not less.
- `PROGRESS.md` — v3 closeout; deviations (generator → v3.1, diversity penalty cut, tiering deferred); open items (cold-start backlog, `/agent` shadow display optional).

## Acceptance checklist

- [ ] Curator subsumes param-tweak mode; old path archived; no double-proposals.
- [ ] Daily pass: worst-K → mutate → select → shadow; weekly generator stub; $5 cap enforced in-pass.
- [ ] Kill switch halts evolution only; ingestion/detection/eval continue.
- [ ] `review_proposals.py` shows backtest + shadow numbers, source diff, and a `blocked_on` reason per candidate.
- [ ] `promote` enforces N≥20 + noise-floor, does the DB transition, emits the composed file, and leaves `modal deploy` to the human.
- [ ] No evolution component writes the production file or deploys.
- [ ] First real run: clean loop, correct cold-start refusal, no live-`forecasts` writes, budget respected.
- [ ] METHODS / SAFETY / about / PROGRESS updated.

## Out of scope

The Generator (v3.1), diversity penalty (cut #2), tiered auto-approve (deferred), `/agent` shadow subsection + lineage column (optional, cut #4 — CLI is the operator surface).

## Gotchas

- **Promotion eligibility ≠ promotion.** N≥20 + noise-floor makes a candidate *reviewable*; the human still decides. Keep `--force` loud and defaulted off.
- **Cold-start is the expected first-run result.** The deliverable is a legible pipeline that declines correctly, not a promoted mutant.
- **Subsumption means retire, not run-both.** If the old param-tweak proposal path is left active alongside the mutator, you'll get duplicate/competing proposals for the same skill.
- **Budget must gate, not just log** — three skills × up-to-3 retries × Sonnet can approach the cap; switch to Haiku before blowing it.
- **The composed production file = surface + scaffolding.** The mutation surface alone has no entrypoint; promotion must recompose it with the `app.py` scaffolding before it's deployable.
- Run from `~/Downloads/envision/`.
