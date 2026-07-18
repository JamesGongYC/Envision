# T10 — Roll back the T8 prose changes; redo prose without breaking the loop

**Goal:** T8's reasoning-first rework left the loop emitting **zero steps** (`agent_run` finishes `completed`, `step_count=0`, empty transcript). Revert to the working pre-T8 loop first to restore a live demo, then re-introduce richer prose in a way that does not break the ReAct parse / persist / terminate contract.
**Depends on:** T2, T6 (loops), T8 (the change being rolled back). **Blocks:** none.
**Scope:** the agent loops (`agents/forecaster/loop.py`, `agents/critic/loop.py`) + their prompts. **Not** `agents/api` (T9 is fine) and **not** the T7/T8 frontend transcript (it renders whatever steps arrive — leave it).

House rules: LLM calls through the wrapper only; no SSE schema change; tests never write prod DB; `git push origin master:main`.

---

## Context — why T8 failed
Evidence: a fire runs ~34s, ends `completed` with `step_count=0`. The loop executed its full course and wrote nothing — it exited on the first model turn without dispatching a tool or persisting a thought. That is a loop-contract failure, and it lines up with two things T8 introduced:
1. **Prompt told the model to reason in prose and "never echo JSON."** If the loop parses tool actions from model *text* (text-ReAct), that instruction starved the parser — no parseable action on turn one.
2. **Termination on "no action parsed."** If the loop's fallback for an unparseable turn is *complete* rather than *re-prompt*, it ends immediately.
3. **Thought steps may only persist on the action path** — a thought-without-action turn writes nothing, so even generated prose never reached `agent_step`.

The transport (thoughts as `thought` steps, no schema change) was fine. The loop contract was not.

## Phase 1 — Roll back T8 loop changes (do now)
Restore the working baseline so the demo emits steps again (tool-summary transcript from before T8 — tool-heavy but functional).

- Revert **only the T8 loop/prompt changes** in `agents/forecaster/loop.py` and `agents/critic/loop.py`: the intent/narration bracketing, the "never echo JSON" prompt language, and the ordering guard that blocks an action before its intent thought.
- Prefer a clean `git revert` of the T8 loop commit(s); if T8 mixed loop + frontend in one commit, cherry-pick the revert to the loop files only. Keep T9 (`agents/api`) and the T7/T8 frontend intact.
- **Verify baseline before moving on:** a test fire produces an `agent_run` with `step_count > 0` and a populated transcript.

## Phase 2 — Redo prose correctly (design + implement, validated before ship)

### Diagnose first (confirm the mechanism)
Confirm how the loop currently gets its tool action: **native `tool_use` blocks** (SDK-structured) or **text-parsed** ("Action: run_skill(...)"). This decides the fix and must be checked, not assumed.

### Design requirements (non-negotiable)
- **Prose must not compete with the tool-call format.** Reasoning and the tool call must be *separate channels*, so producing prose can never starve the action parser.
- **Persist thoughts independently of actions.** The `agent_step` writer must be called on the thought path, not only the action path. A thought-only turn still writes a step.
- **Terminate only on an explicit `emit`/terminal action or max-steps** — never on "no action parsed." An unparseable / no-action turn **re-prompts for a tool call**, it does not complete the run.
- Keep prose riding as `thought` steps (no SSE schema change).

### Recommended mechanism
If the loop is text-parsed, **move to native `tool_use`**: the model returns a `text` block (the reasoning) **and** a `tool_use` block (the action) in the *same* assistant turn. Persist the `text` as the intent thought, dispatch the `tool_use`, persist the observation, and let the next turn's `text` be the narration. The SDK guarantees the tool call's structure, so richer prose can't break parsing — the exact failure mode T8 hit. The wrapper already handles `tool_use`; no new call site.
If the loop is already native `tool_use`, the fix is smaller: wire thought-step persistence + fix the terminate condition, and put the reasoning in the per-turn `text` block rather than instructing the model to suppress the tool format.

### Validate before ship
- On a dev/test fire, assert the loop emits **N>0 steps**, interleaving thought prose with tool chips, and terminates only on `emit`/max-steps.
- Only after that passes does prose density get tuned (the qualitative "reasoning leads" goal from T8) — density work resumes **on top of a loop that provably emits steps**, not before.

## Guardrails
- Do not touch T9 (`agents/api`) or the frontend transcript.
- Wrapper stays the sole LLM choke point; no new `anthropic` imports.
- No SSE schema change.

## Test plan
1. **Phase 1 baseline:** post-revert test fire → `agent_run.step_count > 0`, transcript populated.
2. **Regression guard:** a run with no work to do still emits its reasoning/inspection steps and ends `completed` with `step_count > 0` (never 0).
3. **No-action turn:** simulate a turn with no parseable tool call → loop re-prompts, does **not** complete.
4. **Thought persistence:** a thought-only turn writes an `agent_step`.
5. **Terminate condition:** run ends only on `emit`/terminal action or max-steps.
6. **Phase 2:** test fire emits interleaved prose + tool steps, N>0, prose reads as intent/observation not JSON echo.

## Acceptance
- [ ] **Phase 1:** T8 loop/prompt changes reverted; test fire emits steps again; T9 + frontend untouched.
- [ ] Current tool-action mechanism (native `tool_use` vs text-parsed) confirmed and recorded.
- [ ] **Phase 2:** reasoning and tool call are separate channels; thoughts persist independently; no-action turns re-prompt; termination only on `emit`/max-steps.
- [ ] Validated test fire emits N>0 interleaved prose + tool steps before any density tuning.
- [ ] No schema change; wrapper-only; `agents/api` + frontend unchanged.

## Out of scope
Prose *density* tuning (resumes after Phase 2 proves the loop emits steps), aggregator/critic behavior, `agents/api`, promotion UX.
