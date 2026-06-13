# Envision v3 — Self-Evolving Skill Generation

A closed loop where the Curator does not just edit existing skills but invents and tests new ones. Mutation by LLM rewriting Python source; selection by backtest Brier. No domain DSL.

---

## 1. Premise

v2's Curator can tune parameters within an existing skill. v3 lets the Curator (a) mutate skill *code* (not just parameters), and (b) generate skills from scratch given the signal catalog. The new fitness signal is **backtest Brier against historical signals + ground_truth**, not just live Brier. Selection is empirical: the LLM proposes, the backtest disposes.

Bitter-lesson alignment: no typed composition primitives, no domain DSL. The mutator is given the parent skill's Python source + Brier trajectory + selected failure traces and is asked to rewrite. The selector ranks by backtest Brier across multiple windows. Whatever cross-source patterns emerge, emerge — we don't pre-enumerate them.

## 2. Decisions log

| Decision | Choice | Rationale |
|---|---|---|
| Mutation surface | Raw Python rewrites by LLM | Bitter-lesson aligned; no domain knowledge baked in |
| Fitness | Backtest Brier across ≥3 disjoint windows | Already the system's grading signal; cross-window guards against overfitting |
| New-skill generation | LLM writes skill from scratch given signal catalog + seed prompt | Same mechanism as mutation, just no parent |
| Promotion path | Shadow mode → operator approval → production | Decouple invention from human review burden |
| Genealogy | `skill_lineage` table | Trace any forecast to its origin |
| Borrow vs. build | Borrow architecture from Hermes Self-Evolution; build our own loop | Phase 4 (code mutation) is not yet implemented in their repo; their eval source doesn't match our domain |
| License posture | Avoid AGPL Darwinian Evolver in core; external CLI subprocess only | Keep Envision permissive |
| GEPA usage | Plug in for SKILL.md / reasoning-prompt text mutation only | Phase 1 is implemented; modest value, low effort, optional |

## 3. Findings from `hermes-agent-self-evolution`

- **Phase 1 (SKILL.md evolution) is implemented**: DSPy + GEPA, evolves skill description and reasoning prompt text. Drop-in plausible for the Envision Curator's existing reasoning-prompt mutations.
- **Phase 4 (tool implementation code evolution) is planned, not implemented**. The intended engine is Darwinian Evolver — AGPL v3, external CLI only. We need this and don't have it for free.
- Eval sources offered: `synthetic` (LLM-generated) and `sessiondb` (Hermes/Claude Code session history). Neither matches Envision's domain (cron-driven detection over signal streams).
- Guardrails worth mirroring: full test suite must pass, size limits, semantic preservation, PR review (never direct commit).

**Implication:** We build the code-evolution loop ourselves. Our setup is simpler than theirs — fitness is a scalar, mutation is well-defined, selection is deterministic. We don't need DSPy; we need a backtest harness and a tight LLM loop.

## 4. Explicit non-scope for v3

- Real-time online evolution. v3 runs daily.
- Cross-class skill generalization. One class at a time per evolution run.
- Reward shaping / curriculum learning. Brier only.
- Multi-objective optimization. Single objective with diversity as tiebreaker.
- The composition DSL. Explicitly abandoned per the bitter-lesson framing.
- Auto-promotion to production. Shadow → operator approval is the floor.
- Generator proposing new *ingestion* skills. Detection only in v3.0.

## 5. Architecture

```
                  ┌────────────────────────────────────────────┐
                  │           v3 Evolution Pipeline            │
                  └────────────────────────────────────────────┘

[signal catalog]                              [skill source + Brier trajectory]
       │                                                  │
       ▼                                                  ▼
  [Generator] ──────► [candidate skill code] ◄────── [Mutator]
                              │
                              ▼
                    [AST + import + sandbox validation]
                              │
                              ▼
                    [Backtest harness]
                    replay signals[t_start..t_end] → run(t)
                    collect forecasts → score vs ground_truth
                    across ≥3 disjoint windows
                              │
                              ▼
                    [Selector: top-K by mean Brier + diversity]
                              │
                              ▼
                    [Shadow deploy]
                    forecasts_shadow table
                    cron-driven real-time evaluation for N cycles
                              │
                              ▼
                    [skill_edit_proposals]
                    (existing operator approval queue)
                              │
                              ▼
                    [Promotion to production skill file]
```

## 6. Schema additions

```python
class SkillLineage:
    id: UUID
    skill_id: str                  # canonical, e.g. "wildfire_risk_elevated"
    parent_skill_id: str | None    # None for de-novo generated
    version: int
    source_code: str               # full Python
    skill_md: str
    created_at: datetime
    generation_method: str         # 'manual' | 'mutated' | 'generated'
    proposal_id: UUID | None       # FK to skill_edit_proposals

class BacktestRun:
    id: UUID
    skill_id: str
    version: int
    window_start: datetime
    window_end: datetime
    brier_score: float
    hits: int
    false_positives: int
    misses: int
    forecasts_emitted: int
    run_at: datetime

# forecasts_shadow: mirror of forecasts schema plus:
#   shadow_promotion_status: 'evaluating' | 'promoted' | 'discarded'
```

<!-- TODO(v3): Renumber this migration to 005_evolution.sql when v3 starts — 004 is taken by 004_v2_additions.sql. -->

Migration `004_evolution.sql` creates these. Existing `skill_edit_proposals` gets a new column `lineage_id UUID REFERENCES skill_lineage(id)`.

## 7. Day-by-day roadmap (10 days)

### Day 1 — Skill refactor + backtest harness
- Refactor each detection skill to expose `run(now: datetime, db: Connection) -> list[Forecast]`. Today's scripts have `datetime.utcnow()` peppered throughout — extract as a parameter so the harness can replay historical time.
- Build replay loop: walk forward from `t_start` in the skill's natural cadence, call `run(t)`, collect outputs into a temporary `forecasts_backtest` table.
- Sanity test: backtest `wildfire_risk_elevated` v3 over the last 7 days against accumulated real signals; result should approximate the live Brier in `evaluations` to within ±0.02.

### Day 2 — Mutator
- Sonnet call with structured `tool_use`: input = parent source + Brier trajectory (last 14 days) + the 3 worst-Brier evaluations' detection traces.
- Reuse the existing Curator's AST validator. Reject no-ops. Reject mutations that change the `run()` signature.
- Insert a `skill_lineage` row for every accepted mutant.

### Day 3 — Generator (de-novo skills)
- Sonnet call: seed prompt ("propose a new wildfire detection skill") + signal catalog view (signal types in DB, sample payloads per type, geographic coverage, typical cadence).
- Returns full skill source + SKILL.md.
- Same lineage tracking with `generation_method='generated'`, `parent_skill_id=NULL`.

### Day 4 — Selection + shadow deployment
- Selector: top-K (=3) by mean backtest Brier across ≥3 disjoint windows. Diversity penalty by output overlap (Jaccard on forecast geometries over a shared evaluation window).
- Shadow deploy: write to `forecasts_shadow` with `shadow_promotion_status='evaluating'`. Extend the evaluator to score shadow rows.
- Cron registers the shadow skill at its declared cadence; live Brier accumulates over N=20 evals.

### Day 5 — Operator review surface
- Extend `tools/review_proposals.py`: each proposal shows backtest Brier per window, mean Brier vs parent, shadow Brier-so-far, source diff.
- `/agent` page: add a "Shadow forecasts" subsection (operator-only, not surfaced on `/`); add a lineage column showing parent→child relationships.

### Day 6 — Curator orchestration
- Rewire the daily Curator: instead of proposing parameter tweaks directly, it selects the top-3 skills by "Brier improvement opportunity" (worst-performing, or largest spread between baseline and current) and invokes the mutator on each.
- Once per week, invoke the generator with a seed prompt for one disaster class.
- Budget cap: $5 per evolution pass, ~$25/week. Sonnet→Haiku fallback if exceeded.

### Day 7 — First end-to-end real run
- Trigger a full evolution pass on accumulated real data.
- Observe: do mutants beat parents? Are any pathological (zero forecasts; runaway probabilities; FK violations)? Adjust guardrails.

### Days 8–9 — Iteration
- Tune diversity penalty, minimum-eval threshold, mutator prompt.
- Optionally wire GEPA Phase 1 as a separate slow cron for SKILL.md text mutation.

### Day 10 — Documentation + soft launch
- Update `METHODS.md` with the v3 loop.
- New `/about` section explaining the evolution mechanism in plain language.

## 8. Cut list

In order of expendability:

1. Generator (de-novo skills). Mutator alone gets us materially closer to the vision.
2. Diversity penalty in the selector. Plain top-K Brier is fine for v3.0.
3. GEPA Phase 1 for SKILL.md text mutation. Optional.
4. `/agent` lineage column. CLI is sufficient for operators.

**Never cut:** backtest harness, AST/sandbox validation, shadow mode, cross-window Brier selection, lineage table, operator approval gate.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Backtest leakage (skill sees future signals) | Strict temporal cutoff in harness; queries hard-filtered on `timestamp <= now_parameter` |
| Sparse ground truth makes Brier noisy | Require N≥20 evals before promotion; require improvement > noise floor (~0.03 absolute) |
| LLM generates non-executable code | AST + import + sandbox-exec validation before backtest |
| Mutant Brier improvement is spurious (overfits one window) | Cross-validate across ≥3 disjoint windows; require improvement in all |
| Cost blowup | $5/pass cap; Sonnet→Haiku fallback |
| Lineage table bloat | Auto-archive skills not promoted after 5 generations |
| Mutant references a signal source not in DB | Validator checks all referenced sources exist; reject if not |
| Mutant has good shadow Brier but pathological production behavior (forecast spam) | Volume rate limit per skill; shadow phase observes forecast-count distribution |
| Operator review backlog as proposal rate increases | Tier the gates: parametric edits auto-approve below threshold; structural edits manual; new skills shadow → manual |

## 10. Open questions

- One skill per evolution pass, or several in parallel? Lean: several — cheap to run, expensive only in human review.
- Does the existing Curator's parameter-tweak mode coexist with v3 mutation, or does v3 subsume it? Lean: subsume — parameter tweaks are a strict subset.
- Should the generator be allowed to propose ingestion skills? Lean: no, v3.0. New data sources stay manual until v4.
- How do we present shadow forecasts to operators without confusing public viewers? `/agent` is operator-facing; do not surface to `/`.

## 11. Dependencies on v2

v3 cannot start until v2 ships:

- **Multiple data sources** (Open-Meteo, JTWC, EFFIS, AIFS overlay) — the signal catalog needs more than 4 entries before mash-ups are meaningful.
- **Trace JSONB columns** on `forecasts` and `skill_edit_proposals` — the mutator needs to see *why* skills failed, not just *that* they did.
- **Backtest-friendly skill refactor groundwork**. v2's trace instrumentation already requires extracting `now()` to a parameter in many places. Doing it cleanly in v2 makes Day 1 of v3 mostly free.

## 12. What we borrow from `hermes-agent-self-evolution`

| Borrow | Don't borrow |
|---|---|
| Architectural template (read → eval → mutate → guard → PR) | Their eval-source machinery (sessiondb / synthetic) — replaced by our backtest harness |
| Guardrail list (test suite, size limits, semantic preservation, human PR review) | Their target (agent-tool skills, conversation traces) — replaced by our cron detection skills |
| GEPA Phase 1 for SKILL.md text mutation (optional, low priority) | Darwinian Evolver as in-process engine — external CLI subprocess only if used at all |

---

## Appendix A — Files Cursor should always have in context for v3 work

- `envision_plan.md`
- `v3_plan.md` (this file)
- `v2_plan.md` (to be written)
- `docs/PROGRESS.md`
- `db/schemas.py`
- The skill being mutated (passed per-ticket)

## Appendix B — Repo layout additions

```
envision/
├── agent/
│   ├── evolution/                # NEW (v3)
│   │   ├── backtest_harness.py
│   │   ├── mutator.py
│   │   ├── generator.py
│   │   ├── selector.py
│   │   ├── sandbox.py
│   │   └── signal_catalog.py
│   └── skills/
│       └── curator/              # rewired in v3 to invoke evolution pipeline
├── db/migrations/
│   └── 004_evolution.sql         # NEW (v3): skill_lineage, backtest_run, forecasts_shadow
└── docs/
    └── v3_plan.md                # this file
```
