# T12 — Map choreography: paced playback, input-layer pulse, anchored candidate popups

**Goal:** Drive the map and transcript together off the agent event stream on a single eased-timeline player used for **both** live fire and public replay: firing a skill pulses the input signal layer(s) it reads, candidate emission drops anchored popups that persist for the rest of the run, and the transcript advances in lockstep on the paced timeline.
**Depends on:** T11 (event contract: prose, `input_layers`, per-candidate geometry). **Blocks:** none.
**Scope:** `viewer/` only — the `/agent` demo (forecaster map side + transcript), the SSE client, and a new timeline player. **No** backend changes.

House rules: viewer only; no SSE schema change (consume T11's fields); preserve producer badges, operator-Fire gating (public = replay-only), disclaimer/attribution.

---

## Context (locked decisions)
- Effect (1) = **input-layer pulse**: firing a skill pulses the signal layer(s) it *reads* (from T11 `input_layers`), not produced clusters. Layers already exist on the map; we animate them. No skill change.
- Effect (2) = **anchored candidate popups** on `emit`, Leaflet popups at each candidate's location, **persist for the rest of the run**.
- Pacing = **replay-level for both surfaces.** Even a live operator fire plays on the eased timeline (steps buffer, then animate) — legibility over raw immediacy. Live and replay share one choreography engine; they differ only in source (live starts as steps arrive and may catch the run's tail; replay reads a finished run).

## Build

### 1. Single eased-timeline player
- **New** `viewer/components/agent/RunPlayer.tsx` — consumes the ordered `agent_step` event stream and advances a paced timeline, driving **both** the transcript and the map from the same clock.
- Live (`fire`) and replay (`GET …/run/{id}/replay`) feed the same player. Live buffers incoming steps and plays them on the eased schedule (may lag the true run tail — that's the accepted tradeoff). Replay plays a finished run end to end.
- Eased inter-step timing (not raw arrival gaps); transcript prose and the corresponding map effect fire on the same tick so the two panels stay in lockstep.

### 2. Input-layer pulse on skill fire
- On a `run_skill` step, read `input_layers[]` and apply a **pulse/highlight** to those existing map layers (e.g. FIRMS hotspots pulse while a wildfire skill runs; cyclone-signal layer pulses for a typhoon skill).
- Pulse is tied to the step's dwell on the timeline — animate while that step is "active," settle as the timeline advances. Use `geo_focus` to pan/zoom to the region as today.
- If a skill maps to a layer with no visible data in view, pulse is a no-op (don't invent geometry).

### 3. Anchored candidate popups on emit
- On the `terminal`/`emit` step, for each candidate drop a **Leaflet popup anchored to its location** (from T11's per-candidate geometry) with the forecast detail (hazard, probability, skill), badged `agent`.
- Popups **persist for the remainder of the run** (do not auto-fade); clear on a new run / player reset.

### 4. Transcript in lockstep
- The T7/T8 transcript is driven by the same player: prose `thought` blocks reveal on their timeline tick, tool chips stay thin/collapsed. Map effect and its narrating prose surface together.
- Keep typing animation on prose only.

## Guardrails
- Forecaster only gets the map; the critic window stays transcript-only (no map).
- Consume T11 fields as-is; no SSE schema change; no backend calls beyond existing `fire`/`replay`.
- Producer badges, operator-Fire gating (public replay-only), disclaimer/attribution preserved.
- Pulse targets **existing** layers; no cluster/candidate geometry is fabricated client-side.

## Test plan
1. A run plays on the eased timeline for both a live fire and a replay, using the same player; transcript and map advance together.
2. `run_skill` for a wildfire skill pulses the FIRMS layer; for a typhoon skill, the cyclone layer; correct per `input_layers`.
3. `emit` drops one anchored popup per candidate at its location with correct detail; popups persist to run end; clear on reset.
4. Live fire buffers + paces (does not render raw bursts); replay plays a finished run.
5. Critic window shows no map; forecaster does.
6. Badges, gating, disclaimer intact; public surface has no Fire control.

## Acceptance
- [ ] One shared eased-timeline player drives transcript + map for both live and replay.
- [ ] Skill fire pulses the correct **input** signal layer(s) from `input_layers`.
- [ ] Candidate emission drops anchored popups that persist for the run.
- [ ] Transcript prose and map effects advance in lockstep on the paced timeline.
- [ ] Forecaster-only map; gating/badges/disclaimer preserved; no fabricated geometry.

## Out of scope
Backend/loop/event changes (T11), produced-cluster visualization (explicitly not built — input-layer pulse only), aggregator/critic behavior, prose density tuning.
