# T11 — Loop + stream refactor: model prose, unlocked geo, skill→layer events

**Goal:** Refactor the agent loop so the model emits real reasoning as a native `text` block *alongside* each `tool_use` action (prose streams outside the boxes), coordinates leave the prose and ride as structured geo on events, `run_skill` events name the input signal layer(s) to pulse, and candidate-emission events carry per-candidate location + detail. This is the event contract the map choreography (T12) consumes — it must be correct before T12 has anything to animate.
**Depends on:** T10 (loop emits steps again). **Blocks:** T12.
**Scope:** `agents/forecaster/loop.py`, `agents/critic/loop.py`, their prompts, the tool layer, and the step/event serialization. **Not** the aggregator, `agents/api` transport shape beyond the event fields, or the frontend.

House rules: LLM calls through the wrapper only; tests never write prod DB; no new `anthropic` imports (wrapper only); `git push origin master:main`.

---

## Context
T8 failed because it asked the model to emit prose *instead of* the tool-call format, starving a text parser. The durable fix (locked): **native `tool_use`** — reasoning and the action are separate channels, so richer prose can never break parsing. Coordinates currently sit trapped inside the tool JSON; they move out — to the map, not the transcript.

## Changes

### 1. Native `tool_use` with a per-turn reasoning `text` block
- Each assistant turn returns a `text` block (the reasoning) **and** a `tool_use` block (the action). The SDK guarantees the tool call's structure; prose lives in `text` and cannot collide with it.
- Persist the `text` as a `thought` step (streamed outside the boxes); dispatch the `tool_use`; persist the observation; the next turn's `text` is the narration of that result.
- **Prompt:** ask for concise, first-person intent before acting and sense-making after observing — in the `text` block. Do **not** instruct the model to suppress or avoid the tool format (that was the T8 error).
- Keep the T10 contract intact: thoughts persist **independently** of actions; a no-action turn re-prompts; termination only on `emit`/terminal or max-steps — never on "no action parsed."

### 2. Unlock coordinates → structured geo on events (out of prose)
- Coordinates stop appearing as transcript text. `run_skill` and candidate events carry geometry as structured fields (GeoJSON), not prose.
- `geo_focus` (bbox) stays for the map spotlight; **add** per-event geometry so the map can highlight specifics, not just pan.
- Prose `text` references places in words ("the western US"), never raw lat/lng.

### 3. Skill → input-layer map (for the pulse effect)
- Add a **static** map from `skill_id` → the input signal layer(s) it reads (e.g. `wildfire_rapid_growth` → FIRMS hotspots; `typhoon_intensifying` → cyclone signals). Hardcoded config, not model-authored.
- Every `run_skill` event carries `input_layers: [...]` so T12 can pulse the layer(s) the skill consumes. This is **input** layers read, not produced clusters — no skill output changes, nothing touches the mutation surface.

### 4. Candidate-emission event payload (for anchored popups)
- On `emit`, each selected candidate's event carries its **location** (point/geometry) + the forecast detail needed for a popup (hazard class, probability, skill, any short label).
- Enough for T12 to drop an anchored, persistent Leaflet popup per candidate — no map-side re-derivation from raw JSON.

## Event contract handed to T12 (per step, existing `thought/action/observation/terminal` types)
- `thought` → model `text` prose (streams outside the boxes).
- `action` (`run_skill`) → `tool`, `skill_id`, `input_layers[]`, `geo_focus`, per-run geometry.
- `observation` → structured result (candidate count, etc.); prose narration arrives as the next `thought`.
- `terminal` (`emit`) → per-candidate `{location, hazard, probability, skill, label}[]`.

No new `step_type`; new **fields** on existing events. Confirm whether the T4 event serializer needs widening to pass these through — if so, widen it here (still no semantic schema change to the step types).

## Guardrails
- Reasoning and tool call are separate channels; prose can never starve the parser.
- Skill→layer is static config; skills' `run(now,db)` outputs are unchanged; mutation surface untouched.
- Wrapper is the sole LLM choke point.
- Prose carries no raw coordinates.

## Test plan
1. Test fire emits `thought` steps containing model prose (intent + narration), interleaved with tool steps; `step_count > 0`.
2. No-action turn re-prompts; run terminates only on `emit`/max-steps (T10 contract preserved).
3. Every `run_skill` event carries correct `input_layers` for that skill.
4. `emit` event carries per-candidate location + detail sufficient for a popup.
5. No raw lat/lng appears in any `thought` text.
6. Wrapper-only; no direct SDK imports; no skill output signature change.

## Acceptance
- [ ] Native `tool_use`: model `text` reasoning streams alongside the action; T10 loop contract intact.
- [ ] Coordinates removed from prose; geometry rides as structured event fields.
- [ ] `run_skill` events carry static `input_layers[]`.
- [ ] `emit` events carry per-candidate location + detail.
- [ ] Event serializer passes the new fields through; no new `step_type`; mutation surface untouched.

## Out of scope
The map choreography itself (T12), prose density tuning beyond "intent + narration present," aggregator/critic behavior, `agents/api` gate logic.
