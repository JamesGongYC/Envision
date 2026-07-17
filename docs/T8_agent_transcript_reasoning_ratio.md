# T8 — Agent transcript: reasoning must dominate

**Goal:** The forecaster/critic visibility box is currently a list of tool summaries with almost no prose. Make streamed natural language — intent before each action, sense-making after each observation — the dominant content of the transcript. Tool traces shrink to thin, collapsible chips between the prose.
**Depends on:** T2, T6 (loops), T7 (transcript). **Blocks:** none.

House rules: LLM calls through the wrapper only; no SSE schema change; tests never write prod DB.

---

## Problem (observed)
The live box renders only `RUN_SKILL … → N candidates` / `INSPECT_SIGNALS …` rows — ~0% reasoning. Two causes:
1. **The loop emits terse actions with no bracketing prose** — the ReAct thoughts are empty or trivial, so there's nothing for T7's "reasoning is the hero" layout to show.
2. **T7 folded `observation` into the tool row**, removing the one natural-language observation beat. Reverse that.

The reasoning has to *lead*; it can't be met by styling alone. The loop has to produce substantive prose, and the transcript has to render it as the dominant stream with tools subordinate.

## Part A — Loop: bracket every tool call with prose (backend)
Files: `agents/forecaster/loop.py`, `agents/critic/loop.py`, and their ReAct system prompts.

- **Intent thought before every action.** One–two first-person sentences saying *why* this tool, *what* the agent expects, *how* it will use the result. Emit as a `thought` step, streamed **before** the `action`.
- **Observation narration after every observation.** One–two sentences on *what the result means and what it changes* — not a restatement of the JSON. Emit as a `thought` step immediately **after** the raw `observation`. (No new `step_type`; it rides as `thought`, which T7 already renders as prose.)
- **Ordering guard:** stream `intent(thought) → action → observation(raw) → narration(thought)`. Do not stream an `action` before its intent thought exists.
- **Prompt:** require concise decision-oriented reasoning each step; first person; never echo JSON; name the signal/skill and the inference. These are the same ReAct reasoning tokens the model already produces — the change is making them substantive and streaming them, not adding call sites.
- Terminal step keeps its summary card (emitted ids / proposal link).

**Concrete target for the exact run in the screenshot** (so Cursor has a bar): between `LIST_SKILLS` and the typhoon `RUN_SKILL`s, an intent like *"Signals are in — FIRMS is dense over the western US, the cyclone feeds look thin. I'll run both typhoon detectors first to rule out active systems before spending time on wildfire."* After the two empty typhoon results, a narration like *"Both cyclone detectors came back empty. That tracks — JTWC is landing signals under the wrong year, so there's effectively no live typhoon data to act on. Moving to the wildfire detectors where coverage is real."* That is the density expected around every tool call.

## Part B — Transcript: prose is the stream, tools are chips (frontend)
Files: `viewer/components/agent/AgentTranscript.tsx`, `ToolCallRow.tsx`.

- Render intent + narration `thought` blocks as **full-width message blocks** — the dominant, typing-animated content.
- **Un-fold observation from the tool row.** `ToolCallRow` becomes a single-line collapsed chip (tool name + one-line `summarizeTool`); the raw `tool_input`/`tool_output` stays behind the click. It sits *between* the two prose blocks, visually subordinate.
- Do not typing-animate tool chips; animate prose only.
- Keep map spotlight (forecaster) and producer badges unchanged; live and replay identical.

## Acceptance
- [ ] Every tool call is preceded by an intent thought and followed by an observation narration, both streamed.
- [ ] In a representative forecaster and critic run, prose is clearly the dominant content and tool chips read as subordinate detail.
- [ ] Tool chips are one line, collapsed by default, expand to full raw logs.
- [ ] No SSE schema change; narration rides as `thought`.
- [ ] All model calls through the wrapper; map spotlight, badges, live/replay parity intact.

## Out of scope
Aggregator/critic behavior, promotion UX, any new `step_type` or backend `summary` field.
