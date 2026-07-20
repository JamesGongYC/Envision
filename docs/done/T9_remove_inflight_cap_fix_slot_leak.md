# T9 — Remove `AGENT_MAX_IN_FLIGHT` gating + fix the leaked slot / zombie run

**Goal:** Stop the false "Run paused — provider capacity" gating (the counter is pinned by leaked slots, not real load), remove the in-flight cap, and make agent runs end when the reasoning ends instead of when the SSE connection closes.
**Depends on:** T4 (SSE + gates). **Blocks:** none.
**Scope:** `agents/api` only. **Do not touch the health gate** (provider 529 / cold-start) — that is a separate gate and stays.

House rules: LLM calls through the wrapper only; no SSE schema change; tests never write prod DB; `git push origin master:main`.

---

## Problem (confirmed from Modal logs)
- Fast `200` fires (~1.5s) are **gated responses** returning immediately (a `gated` body is a 200, not an error).
- The real runs show **20m 12s / 21m 44s** execution — a ReAct pass is 1–3 min; the container lives as long as the **SSE connection stays open**, not until the agent finishes. A left-open tab / dangling connection holds the slot.
- Long runs ended ~18:57 and ~20:57, yet fires from ~21:00 → 00:37 still gate with nothing running. → **the in-flight counter leaked**: runs completed without decrementing it, pinning it at the cap (2) permanently. The cap isn't malfunctioning; it's counting ghosts.

Removing the cap alone would leave the 20-minute zombie runs — and make them cheaper to spawn in parallel (uncapped LLM spend + Modal compute). Fix the leak in the same change.

## Changes (all in `agents/api`)

1. **Remove the capacity gate.**
   - Delete the `AGENT_MAX_IN_FLIGHT` capacity-check branch in the `fire` routes, **or** make it sentinel-disabled: `if AGENT_MAX_IN_FLIGHT and in_flight >= AGENT_MAX_IN_FLIGHT: gate`, then unset/`0` the env and redeploy. Pick permanent-delete unless you want to keep the knob dormant.
   - Remove only the `gated` branch that reports **capacity/max-in-flight**. Leave the health-gate `gated` branch (provider degraded / cold-start) untouched.

2. **Release the slot on every exit path.**
   - If any in-flight bookkeeping remains (or lives elsewhere, e.g. the loop / a run registry), decrement it in a `finally` around the run so it releases on **completed, failed, gated, and client disconnect** — not just the happy path. No exit path may leave the counter incremented.

3. **End the run when reasoning ends, not when the client hangs up.**
   - Close the SSE generator and finalize the run (`agent_run.status`, `finished_at`) the instant the `terminal` (or `gated`/`failed`) event is emitted — do not block on the client staying connected.
   - Detect client disconnect and tear the run down promptly rather than holding the container.

4. **Hard timeout on the fire route.**
   - Set an explicit Modal function timeout on the `fire` handler sized to a realistic max ReAct pass (e.g. a few minutes), so a lingering connection can never hold a container for ~20 min. On timeout, finalize the run (`status='failed'` or a dedicated `timeout` reason) and release the slot.

## Guardrails
- Health gate (529 / cold-start) unchanged and still independent of `ENVISION_CURATOR_ENABLED`.
- No SSE schema change — `gated`/`terminal`/`failed` events as-is (the capacity `gated` reason simply stops being produced).
- Replay path (`GET /agent/run/{id}/replay`) unaffected.
- Wrapper stays the sole LLM choke point.

## Test plan
1. **No false gating:** with no run active, N sequential fires all start real runs — none returns a capacity `gated` body.
2. **No leak:** run to `terminal`, assert the in-flight count returns to 0; force a `failed` run, assert it also returns to 0.
3. **Disconnect:** open a fire, drop the client mid-stream → run finalizes, slot releases, container tears down (not a 20-min hold).
4. **Timeout:** simulate a run exceeding the route timeout → finalizes with the timeout status, slot released.
5. **Health gate intact:** forced 529 / cold-start failure still yields a `gated` event with the *provider* reason.
6. `SELECT status, count(*) FROM agent_run WHERE status='running'` trends to 0 when nothing is live (no stuck `running` rows).

## Acceptance
- [ ] Capacity/max-in-flight gating removed (or sentinel-disabled + unset); provider health gate preserved.
- [ ] In-flight slot released on completed / failed / gated / disconnect via `finally`.
- [ ] Run finalizes on the `terminal` event, independent of client connection.
- [ ] Fire route has a hard timeout that finalizes + releases on expiry.
- [ ] No stuck `running` rows after a run ends; no false capacity gating.

## Out of scope
Health-gate behavior, forecaster/critic loop logic, aggregator, viewer changes beyond the `gated`-reason copy already noted in T4/earlier.
