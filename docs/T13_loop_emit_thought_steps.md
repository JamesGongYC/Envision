# T13 — Loop must emit model reasoning as `thought` steps (native `tool_use`)

**Goal:** The loop currently writes only `action` + `observation` steps — **zero `thought` steps** — so no model reasoning exists in the data and no frontend can render prose. Refactor the loop to native `tool_use` so the model returns a reasoning `text` block **alongside** each `tool_use` action, and persist that text as a `thought` step. This is the half of T11 that did not land; without it T12 has nothing to animate.
**Depends on:** T10, T11 (`input_layers` shipped; native-`tool_use` prose did not). **Blocks:** T12.
**Scope:** `agents/forecaster/loop.py`, `agents/critic/loop.py`, their prompts, and the step-persistence path. **Not** the aggregator, `agents/api`, or the frontend.

House rules: LLM calls through the wrapper only; no new `anthropic` imports; no SSE schema change (`thought` is an existing `step_type`); tests never write prod DB; `git push origin master:main`.

---

## Evidence (why this ticket exists)
`SELECT step_type, count(*) FROM agent_step` for the latest run returns `action: 6, observation: 5, thought: 0`. The `input_layers` field is present in the `run_skill` JSON, so T11's field append shipped — but the native-`tool_use` reasoning refactor was skipped. **Zero thoughts = the model reasoning is never produced or never persisted.** Fix that and only that; the frontend (T12) unblocks automatically.

## Root cause to eliminate
Whatever the loop does now, a full run produces no `thought` rows. That means one or more of:
- the request doesn't use native `tool_use`, so the model has no clean `text` channel and emits only the action;
- the model does return a `text` block but the loop **discards it** (reads only the `tool_use` block);
- the persistence path writes `thought` steps but is never called on the reasoning path.
All three end at the same failure. The fix must guarantee a `text` block is requested, captured, and written as a `thought` step.

## Changes

1. **Native `tool_use` request shape.** Each turn, call the model (through the wrapper) with the tools defined as `tool_use` tools. The model returns an assistant message that may contain **both** a `text` block (reasoning) and a `tool_use` block (action). Do not prompt it to avoid or suppress the tool format (the T8 error) and do not parse actions out of text.

2. **Capture and persist the `text` block as a `thought` step.** On every turn: if the assistant message contains a `text` block, write it as a `thought` step **before** dispatching the `tool_use`. This is the reasoning that streams outside the boxes. The narration of a result is simply the `text` block on the **next** turn.

3. **Prompt for intent + narration in the `text` block.** Instruct the model to state, in prose, its intent before acting and its read of the result after observing — first person, concise, no raw coordinates, no JSON echo. The tool call rides in the `tool_use` block regardless, so prose cannot starve parsing.

4. **Preserve the T10 contract.** Thoughts persist independently of actions; a no-action turn re-prompts (does not complete); termination only on `emit`/terminal or max-steps.

## Guardrails
- Reasoning (`text`) and action (`tool_use`) are separate channels — richer prose can never break the action.
- No new `step_type`; `thought` already exists and is already rendered by the transcript.
- `input_layers` and per-candidate geometry from T11 stay as-is.
- Wrapper is the sole LLM choke point.

## Acceptance — the hard gate
- [ ] **The exact diagnostic query returns `thought` > 0 for a fresh run:**
  `SELECT step_type, count(*) FROM agent_step WHERE agent_run_id = (SELECT id FROM agent_run ORDER BY started_at DESC LIMIT 1) GROUP BY 1;`
  → a `thought` row must be present, and `thought` count should be roughly one-per-turn (comparable to `action`).
- [ ] Each `thought` row's text is **model-generated prose** (intent/narration), not a template and not JSON.
- [ ] `thought` steps interleave with `action`/`observation` in `seq` order (intent → action → observation → narration).
- [ ] T10 contract intact: no-action turn re-prompts; terminate only on `emit`/max-steps.
- [ ] No SSE schema change; wrapper-only; no skill output change; `input_layers` still present.

## Test plan
1. Fire a forecaster run; run the acceptance query → `thought` > 0, ~one per turn.
2. Inspect a `thought` row → contains real reasoning prose, no raw lat/lng.
3. Fire a critic run → same result (thoughts present).
4. Simulate a no-action turn → loop re-prompts, does not complete; run still ends only on `emit`/max-steps.
5. Confirm `run_skill` events still carry `input_layers` (no regression of the half that shipped).

## Out of scope
Frontend rendering/choreography (T12 — unblocks once thoughts exist), prose density tuning, aggregator/critic behavior, map effects.
