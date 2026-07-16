# T2 — Forecaster agent harness + toolset

**Goal:** A manually-fired Modal function that runs a deterministic ReAct loop, reasons over ingestion + skills through four tools, and hands a selected candidate set to the aggregator — never authoring `p`, never calling `emit_forecasts` directly.
**Depends on:** T1. **Blocks:** T3 (emit target), T4, T5.

House rules apply. All model calls go through the single LLM wrapper behind the health gate. Tests never write the prod DB.

---

## Context
D1 (agent selects the set, not the number), D2 (raw per-skill output is agent-independent fitness), D3 (orchestration, not an invention point), D6 (real production run). The ReAct **loop control and tool dispatch are hardcoded infrastructure** — only the reasoning steps inside are model-driven. This keeps the forecaster outside the mutation surface.

## Files (confirm exact paths against repo)
- `agents/forecaster/app.py` — Modal function `forecaster-agent`, on the shared `skill_exec_image`.
- `agents/forecaster/loop.py` — ReAct control loop (deterministic).
- `agents/forecaster/tools.py` — the four tools.
- `agents/common/agent_telemetry.py` — `agent_run`/`agent_step` writers (shared with T6).
- Reuse: the existing single LLM wrapper module; `forecast_writer` (not called here directly); the synthetic-`__file__` skill loader; `signal_catalog` access.
- `add_local_python_source` must include the wrapper + loader + tools so Modal ships them alongside `app.py`.

## Tool contracts
```python
def inspect_signals(bbox: Optional[BBox]) -> dict:
    # signal_catalog view (assume caller REFRESHed) + per-source max(timestamp) freshness.
    # If bbox given, scope counts to it and set geo_focus = bbox on the emitted step.

def list_skills() -> list[dict]:
    # detection skills: id, SKILL.md summary, recent Brier, hit_rate, override_frequency (T1 provenance).

def run_skill(skill_id: str, now: datetime) -> list[Forecast]:
    # Load promoted skill via the synthetic-__file__ loader; execute run(now, db).
    # 1) return candidates into agent context (observation)
    # 2) ALSO deposit raw candidates to the scoring stream tagged (skill_id, agent_run_id),
    #    independent of whether the agent later selects them  <-- D2, non-negotiable
    # 3) geo_focus = bounding envelope of returned candidates

def emit(selected: list[Forecast]) -> list[uuid]:
    # TERMINAL. Passes `selected` to the aggregator interface (T3), which prices + writes
    # producer='agent', agent_run_id. Agent supplies the SET only — never p.
    # In this ticket, call a thin AggregatorInterface stub; T3 wires the real rule.
```

## Loop control (deterministic)
```
pre-flight: health-gate cold-start probe. Fail -> agent_run.status='gated', write a 'gated' step, stop.
for step in range(AGENT_MAX_STEPS):
    call wrapper (single choke point) with running transcript
    parse one action (tool + input) OR terminal emit
    in-run rolling-window 529 abort check -> on trip, status='gated', stop
    dispatch tool, capture observation, persist thought+action+observation steps
    if terminal emit -> run aggregator path, write producer='agent' rows, status='completed', stop
on exhaustion without emit -> status='completed' with empty outcome (no forecasts), log reason
```
- `AGENT_MAX_STEPS`, health-gate `window_minutes`/`min_samples`/`threshold` are named config.
- Every step persisted to `agent_step` (seq monotonic); `tool_output` size-capped (16KB trace discipline); run row updated with `step_count`, `finished_at`, `status`.

## Guardrails (invariant-preserving)
- Agent sees only `run(now, db)` results — never `emit_forecasts` internals or `app.py`.
- Agent never sets `p`; `emit` rejects any per-candidate probability supplied by the model (strip/ignore).
- No direct SDK calls anywhere in the agent path.
- `run_skill` MUST deposit raw output to the scoring stream even when the candidate is dropped — assert this in tests.

## Test plan (test DB + fixtures)
1. Full cycle on fixture signals: thought→action(`inspect_signals`)→observation→action(`run_skill`)→observation→`emit`. Assert ordered `agent_step` rows + one `agent_run`.
2. Assert every `run_skill` call deposits raw candidates to the scoring stream, including a candidate the agent does not select.
3. Forced 529 mid-run → `status='gated'`, no `emit`, no `producer='agent'` rows.
4. Cold-start probe failure → `status='gated'` before any tool runs.
5. Model returns a `p` on a candidate → ignored; emitted `p` comes only from the aggregator stub.
6. Grep: zero direct SDK imports in `agents/forecaster/**`.

## Acceptance
- [ ] `forecaster-agent` runs a full ReAct cycle on the shared image with wrapper + loader shipped.
- [ ] Raw per-skill output hits the scoring stream on every `run_skill`, selection-independent.
- [ ] Health-gate refusal yields `gated`, no partial emit.
- [ ] Agent supplies a set only; emitted `p` never originates from the model.
- [ ] All model calls through the single wrapper.

## Out of scope
The real aggregation rule (T3 — stubbed here), the SSE endpoint (T4), viewer (T5), the critic (T6).
