# T6 — Critic agent over the existing mutator/generator

**Goal:** Replace the curator's mechanical worst-K selection with a reasoning agent that inspects raw per-skill performance and targets the two existing invention points — routing everything through the unchanged validation → shadow → human-gate path.
**Depends on:** T1 (override-frequency signal), T2 (shared harness + `list_skills`). **Blocks:** none.

House rules apply. All model calls through the single wrapper behind the health gate.

---

## Context
D5 (critic replaces selection, keeps all gates + generation-trigger discipline) and D3's analogue: the critic is **orchestration, not a new invention point** — invention still happens in the mutator/generator; the critic only reasons about *which* to invoke and *on what target*. It never scores, never promotes, never writes a production skill file. Lands last because it is the two live invention points rewrapped, not new surface.

## Files (confirm paths)
- `agents/critic/app.py` — Modal function `critic-agent` (same harness pattern as T2).
- `agents/critic/loop.py`, `agents/critic/tools.py`.
- Modify the `curator`: swap its worst-K mechanical selection for a call into the critic's reasoned targeting. Keep the curator shell — scheduling, health gate, generation-trigger condition-gate — intact.
- Reuse: the existing mutator + generator entry points; `tools/review_proposals.py` queue; `agent_telemetry` writer.

## Tool contracts
```python
def inspect_forecasts(skill_id: str) -> dict:
    # RAW per-skill forecasts + ground-truth matches + Brier trace (the scoring stream, D2),
    # NOT agent-curated production. Surfaces override_frequency (T1 provenance) alongside Brier.

def list_skills() -> list[dict]:   # shared with forecaster (T2)

def mutate_skill(skill_id: str) -> uuid:
    # Invoke the EXISTING mutator. Output flows the UNCHANGED path:
    # AST -> sandbox -> light viability gate -> shadow -> shadow-Brier clock -> human gate.
    # Returns the proposal id. Critic does not evaluate or promote it.

def generate_skill(disaster_class: str, seed: str) -> uuid:
    # Invoke the EXISTING generator. STAYS condition-gated / operator-seeded — NOT the daily tick.
    # Same downstream path; returns proposal id.
```

## Behaviour
- Runs on the curator tick for **mutation targeting** — reasons over which skills underperform and why, then calls `mutate_skill` on the chosen target(s) instead of blind worst-K.
- De-novo `generate_skill` fires **only** when its existing condition gate / operator seed is satisfied — the critic must not spray de-novo skills onto the daily tick.
- Reads the **raw** scoring stream, never the agent-curated production set.
- Every step persisted to `agent_step`/`agent_run` (`agent_type='critic'`, `trigger='scheduled'` on the tick, `'button'`/`'operator'` when fired via T4).

## Guardrails (invariant-preserving)
- Critic proposes and reasons only: no scoring, no promotion, no production skill-file writes, no touching the evaluator/cap/gates.
- Only `run.py` is ever fed to the mutator/generator (unchanged) — the critic passes targets, not code.
- Curator's shadow-Brier clock (N≥20), light viability gate, and human gate are untouched.
- The "frequently overridden by forecaster" signal is an *input* to the critic's reasoning, not a fitness score.

## Test plan (test DB + fixtures)
1. Critic run over fixture per-skill performance produces a `mutate_skill` proposal that appears in `review_proposals.py list` with correct lineage (`generation_method`, parent).
2. `generate_skill` is **not** invoked on a plain daily tick; only when its condition gate is set.
3. No proposal auto-promotes — the human gate is still required to reach production.
4. Worst-K mechanical selection path is removed; parity check: candidates still reach shadow at ≥ the old rate on the same fixtures.
5. Critic reads raw scoring stream, not agent-curated `forecasts` (assert the query source).
6. All model calls through the wrapper; health-gate refusal → `status='gated'`, no proposals.

## Acceptance
- [ ] Critic reasons over raw per-skill performance and targets `mutate`/`generate`.
- [ ] Output clears the unchanged AST→sandbox→viability→shadow→human-gate path with correct lineage.
- [ ] No auto-promotion; human gate intact.
- [ ] Curator worst-K selection retired with no drop in proposals reaching shadow.
- [ ] Generator not invoked on the plain daily tick.
- [ ] Steps/runs persisted; all model calls through the single wrapper.

## Out of scope
Any change to the mutator/generator internals, the validation pipeline, or the promotion gate — the critic only chooses targets and invokes existing machinery.
