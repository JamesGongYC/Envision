# T3 — Deterministic aggregator

**Goal:** The single non-mutable place emitted `p` is set — for both the agent path and the routine rule path — so the 0.85 cap and the p = hit-rate guard live in exactly one location.
**Depends on:** T2 (emit interface), T1 (provenance columns). **Blocks:** T5 (agent rows to render).

House rules apply.

---

## Context
D1 (aggregator prices; agent selects) and D9 (two producers, one table). The aggregator is **outside the mutation surface** — it must not be importable from any mutator/generator-visible path, or the LLM could copy it and game its own scoring. It sits beside `forecast_writer`.

## Files (confirm paths)
- `pipeline/aggregator.py` — the pure function + config.
- Wire into: the forecaster `emit` (T2) and the routine rule detection emit path (so the rule path is the degenerate single-producer case).
- Config: named keys, no literals — `AGGREGATOR_CORROBORATION_RADIUS_KM`, plus the conflict/cap constants.

## Signature
```python
def aggregate(candidates: list[Forecast],
              skill_hit_rates: dict[str, float],
              cfg: AggregatorConfig) -> list[EmittedForecast]:
    # Groups candidates by hazard class + spatial proximity, computes emitted p per group,
    # honoring the 0.85 cap and the p = hit-rate guard. Pure; no I/O.
```

## Rule (named-config default — `v4_plan.md §4`)
1. **Corroboration:** ≥2 skills firing on the same hazard class within `CORROBORATION_RADIUS_KM` of each other → combine via **noisy-OR** of individual `p`, then clamp to **0.85**.
   `p_combined = 1 - Π(1 - p_i)`, then `min(p_combined, 0.85)`.
2. **Single detection:** one skill on a point → keep that skill's own `p` unchanged.
3. **Conflict:** overlapping same-point forecasts that disagree → the **highest recent-hit-rate skill's** forecast wins the point. No averaging of disagreement.
4. **Guard:** never *lower* `p` on an under-confident skill — the aggregator may only *raise* confidence via corroboration (capped). Reject/clamp any path that would push a single skill's emitted `p` below its own.

> If you prefer a simpler start, swap step 1's noisy-OR for `max(p_i)` capped at 0.85 — one line, same interface. Flagged as tunable; default ships noisy-OR.

## Wiring
- Forecaster `emit(selected)` → `aggregate(...)` → write `producer='agent'`, `agent_run_id`.
- Routine rule path → `aggregate(...)` (single-producer, so mostly step 2) → write `producer='rule'`.
- Both write through `forecast_writer.emit_forecasts` — the aggregator prices, the writer persists. The cap CHECK is the backstop; the aggregator is the intended enforcement point.

## Guardrails
- Pure function: no DB reads inside `aggregate` — `skill_hit_rates` is passed in.
- Not imported by any module the mutator/generator can see; add a test/CI check asserting no such import path exists.
- Deterministic: same input → same output (no clock, no RNG).

## Test plan
1. Two corroborating detections (`p=0.4`, `p=0.5`) → noisy-OR `0.7`, under cap, emitted `0.7`.
2. Corroboration that exceeds cap (e.g. three high `p`) → clamped to exactly `0.85`.
3. Conflicting pair, hit-rates `0.7` vs `0.4` → the `0.7` skill's forecast wins the point.
4. Single detection `p=0.6` → emitted `0.6` unchanged.
5. Under-confident skill (`p` below its hit-rate) is never down-weighted by aggregation.
6. **Shared-code proof:** identical single-detection input through rule path and agent path yields identical emitted `p`.
7. Determinism: repeated calls, identical output.
8. Import-boundary test: `aggregator` not reachable from mutator/generator modules.

## Acceptance
- [ ] Corroboration/conflict/single/guard all behave per §Rule.
- [ ] Cap enforced by the aggregator (not only the DB CHECK).
- [ ] Rule and agent paths share the function and agree on identical input.
- [ ] Pure + deterministic; outside the mutation surface (import test passes).

## Out of scope
Calibrating `CORROBORATION_RADIUS_KM` / noisy-OR against real data — that waits on D9 A/B samples.
