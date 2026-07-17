# T4 — SSE endpoint + operator gate

**Goal:** A Modal ASGI endpoint that live-fires agents (operator-gated) and streams their ReAct trace as SSE, plus an unauthenticated replay stream for the public surface.
**Depends on:** T2, T3. **Blocks:** T5.

House rules apply.

---

## Context
D7 (SSE, `geo_focus` on region-scoped tools), D10 (live-fire operator-gated; public gets replay only), D6 (fire is a real run). The endpoint is deterministic infrastructure. The operator gate is a **separate control** from the health gate and from `ENVISION_CURATOR_ENABLED`: it governs *who may trigger a write-capable fire*, not provider availability or loop intent.

## Files (confirm paths)
- `agents/api/app.py` — Modal ASGI (FastAPI) web endpoint.
- Reuse: forecaster loop (T2), critic loop (T6 — endpoint route can ship ahead, guarded), `agent_step`/`agent_run` readers.
- Secret: add `ENVISION_OPERATOR_TOKEN` to the `envision-neon` Modal secret. **Recreate is destructive — include every existing field.**

## Routes
```
POST /agent/forecaster/fire   (operator-token gated) -> starts real run, streams SSE
POST /agent/critic/fire       (operator-token gated) -> starts real run, streams SSE   [route stub if T6 unshipped]
GET  /agent/run/{id}/replay   (public, no auth)      -> re-streams persisted agent_step rows as SSE
```

## Auth
- `fire` routes require `Authorization: Bearer <ENVISION_OPERATOR_TOKEN>`; missing/wrong → 401/403, **no run created, no writes**.
- `replay` is unauthenticated and read-only — it never triggers LLM spend or DB writes.

## SSE event schema (`v4_plan.md §5`)
```
event: step
data: { run_id, seq, step_type: 'thought'|'action'|'observation'|'gated'|'terminal',
        tool: string|null, input, output (size-capped),
        geo_focus: GeoJSON bbox | null, ts }
```
- `geo_focus` serialized with `ST_AsGeoJSON` on read; present only for region-scoped tool steps (`run_skill`, `inspect_signals(bbox)`), else null → viewer holds the map.
- `gated` (health-gate refusal or over-concurrency) and `terminal` (emitted forecast ids / created proposal ids) are the two stream-ending types besides `failed`.

## Concurrency (`v4_plan.md §6`)
- Bounded wrapper `AGENT_MAX_IN_FLIGHT` across button-fires + the scheduled critic. Over-limit `fire` returns a single `gated` event and does not start a run.
- Health-gate degradation → `gated` event, never a hang.

## Live vs replay
- `fire` streams from the live loop as steps are produced *and* persists each to `agent_step` (so it is later replayable).
- `replay` reads ordered `agent_step` rows for a completed run and re-emits them as the same SSE shape — no new writes, no spend.

## Test plan
1. `fire` without/with-wrong token → 401/403, zero `agent_run` rows, zero writes.
2. `fire` with valid token → ordered SSE stream ending in `terminal`; `forecasts` gains `producer='agent'` rows for the run.
3. `replay` of a completed run reproduces the exact step sequence; asserts no new `agent_step`/`forecasts` rows and no wrapper calls.
4. Forced provider degradation → `gated` event; run row `status='gated'`.
5. `AGENT_MAX_IN_FLIGHT` exceeded → `gated`, no run started.
6. `geo_focus` present on `run_skill` steps, null on pure-`thought` steps.

## Acceptance
- [ ] Operator token enforced on both `fire` routes; unauthenticated fire writes nothing.
- [ ] Live fire streams + persists + emits real `producer='agent'` forecasts.
- [ ] Replay reproduces a run read-only with no spend.
- [ ] Health-gate + concurrency degradation surface as `gated`, never a hang.

## Out of scope
Viewer rendering (T5); the critic loop internals (T6) — the critic route may ship as a guarded stub.
