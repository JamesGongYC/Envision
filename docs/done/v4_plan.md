# Envision — v4 Plan (agentic capability layer)

**Scope:** Add an agent layer on top of the existing single-pass cron-and-rules system. A **forecaster agent** (manually fired, live producer) reasons over ingestion + skills via ReAct and curates what gets emitted; a **critic agent** (scheduled) replaces the curator's mechanical worst-K selection with reasoned targeting of the two existing invention points. A **viewer demo layer** streams both agents' reasoning traces and tool use, with a map spotlight following the forecaster's attention.
**Status:** Planned. Decisions locked (§0). Not yet implemented.

> Live current-state handoff is `PROGRESS.md`; build chronology + resolved incidents in `history.md`; the standing roadmap in `Future plans.md`. This doc is the v4 build plan; it retires the "v4 — Agentic team structure" section of `Future plans.md` on merge.

---

## 0. Decisions locked

| # | Decision | Resolution |
|---|----------|------------|
| 1 | Who authors the emitted probability | **Deterministic aggregator**, not the agent. Agent selects the candidate set; a fixed rule computes `p`. |
| 2 | Per-skill fitness attribution | Measured on **raw skill output** deposited to the scoring stream, **agent-independent**. Agent curation affects only the presented/production set. |
| 3 | Is the forecaster an invention point | **No — orchestration layer.** It authors neither code nor scored values. "Exactly two invention points" (mutator, generator) holds. |
| 4 | Forecaster scheduling | **Two modes in parallel.** Rule-based detection fires routinely (cron, unchanged, auto-emit). The agent fires **only on button**. |
| 5 | Critic scope | Replaces curator worst-K **selection** with reasoned targeting. **All gates unchanged**; generation trigger stays condition-gated/operator-seeded. |
| 6 | Demo button semantics | **Real production run.** A button-fire executes a live agent run and emits to `forecasts`. No dry-run branch. |
| 7 | Trace transport | **SSE** from a Modal ASGI endpoint. `geo_focus` rides on region-scoped tool events; the map spotlight derives from the tool schema. |
| 8 | Agent telemetry | New `agent_run` + `agent_step` tables. Every run + step persisted. |
| 9 | Two production writers into `forecasts` | Single table, add `producer ('rule'\|'agent')` + `agent_run_id` provenance. **No cross-producer dedup; both scored; viewer badges producer.** Every button-fire is a manual agent-vs-rule A/B sample on shared ground truth. |
| 10 | Write-capable button exposure | **Live-fire is operator-gated.** Public `/agent` gets **read-only replay** of the last real run (same SSE trace, same map spotlight, same emitted candidates — no re-triggered spend/writes). |

---

## 1. Architectural invariants (v4 additions — do not drift)

Everything in `PROGRESS.md §2` still holds. v4 adds:

- **Agents propose, sequence, and reason — never author scored `p`, never author production code without the human gate, never self-promote.** This is the operational form of "reason not score."
- **Still exactly two LLM invention points: the mutator and the generator.** Both agents are reasoning/orchestration layers wrapping them; invention = LLM-authored code that can reach production, and neither agent authors code (forecaster) or bypasses the gate (critic).
- **The deterministic aggregator is outside the mutation surface** — beside `forecast_writer`, never fed to mutator/generator. It owns the emitted `p`; the agent owns only the selected set.
- **Per-skill fitness is agent-independent.** Raw skill output → scoring stream → evaluator, regardless of who emitted or whether the agent selected it.
- **Two production writers, one table.** Rule path (routine) and agent path (on-demand) both write `forecasts`, provenance-tagged, both Brier-scored, no cross-producer dedup.
- **The ReAct loop control, tool dispatch, and SSE endpoint are deterministic infrastructure.** Only the LLM's reasoning steps inside the loop are model-driven; the harness around them is hardcoded.
- **One LLM client wrapper remains the sole API choke point** — agent calls route through it, behind the health gate, independent of `ENVISION_CURATOR_ENABLED`.
- **Live-fire operator-gated; public surface is replay-only.**

---

## 2. Workstreams (build order)

Sequenced lowest-risk / foundational first. Each lands independently; nothing after W1 touches the invariant boundary.

### W1 — Migration (schema foundation)
`agent_run`, `agent_step`, and `forecasts` provenance. Numbered **013** on the assumption 012 (generation_method/parent_skill_id backfill) landed — **confirm the live head against the repo before applying** (per `PROGRESS.md` 012 note); renumber to 012 if 012 was never needed. Single transaction. No backfill of historical `forecasts` beyond the `producer='rule'` default.

### W2 — Forecaster agent harness + toolset
New Modal function `forecaster-agent` on the shared `skill_exec_image` (sklearn/shapely + LLM wrapper via `add_local_python_source`). Deterministic ReAct loop around the wrapper; four tools (§3). Health-gate pre-flight at entry + in-run rolling 529 abort. Every step → `agent_step`; run → `agent_run`. The loop **never calls `emit_forecasts` directly** — its terminal `emit` action hands the selected set to the aggregator (W3).

### W3 — Deterministic aggregator
Pure, non-mutable function beside `forecast_writer`. Input: agent-selected candidate forecasts (possibly multiple skills on overlapping geometry). Output: emitted forecasts with computed `p`, `producer='agent'`, `agent_run_id`. Rule (named-config, §4): **noisy-OR over corroborating same-point detections, capped at 0.85; same-point conflict → highest-hit-rate skill wins.** Honors the p = hit-rate principle. Reused by both the routine rule path (single-producer, degenerate case) and the agent path so cap/aggregation logic lives in exactly one place.

### W4 — SSE endpoint + trace schema + operator gate
Modal ASGI (FastAPI) web endpoint. `POST /agent/forecaster/fire` (operator-token gated) starts a real run and streams SSE; `POST /agent/critic/fire` likewise; `GET /agent/run/{id}/replay` re-streams persisted `agent_step` rows for the public surface. Event schema §5. Health-gate degradation returns a `gated` event, never a hang. Wrapper concurrency: bounded max in-flight across button-fires + scheduled critic (§6).

### W5 — Viewer demo layer
`/agent` gains: an operator-gated **Fire forecaster** control (public sees replay-of-last-run); a live trace panel (thought/action/observation, typing-animated, reusing the existing reasoning animation); tool-use cards with lightweight data viz (per-source signal counts, candidate tables); and the **map spotlight** — the existing Leaflet map pans/zooms to `geo_focus` as events arrive, drawing agent-emitted candidates with a `producer` badge. Critic demo is a **standard window, no map**: trace + tool-use + the data it reads (per-skill Brier, the existing React Flow lineage tree, ground-truth matches). Producer badge (`rule`/`agent`) on forecast rendering everywhere. Disclaimer + per-source attribution unchanged.

### W6 — Critic agent over the existing mutator/generator
Replaces the curator's worst-K selection with reasoned targeting (§3). Curator shell — scheduling, health gate, generation-trigger discipline — unchanged. Output routes through the **unchanged** `AST → sandbox → light viability gate → shadow → shadow-Brier clock (N≥20) → human gate via review_proposals.py`. The critic proposes and reasons; it never scores, never promotes, never emits a production skill file. Reads the **raw** scoring stream (not agent-curated production). New signal available to it: "skill frequently overridden by the forecaster" (from W1 provenance), distinct from raw Brier. Lands last — it is the two live invention points rewrapped, not new surface.

---

## 3. Agent toolsets

**Forecaster (ReAct, terminal action `emit`):**

| Tool | Returns | Notes |
|------|---------|-------|
| `inspect_signals(bbox?)` | `signal_catalog` view + per-source freshness | The "ingestion layer as a skill." `REFRESH MATERIALIZED VIEW` awareness. Region-scoped variant attaches `geo_focus`. |
| `list_skills()` | detection skills + SKILL.md summaries + recent Brier/hit-rate + override-frequency | Read-only. |
| `run_skill(skill_id, now)` | candidate `Forecast` list → agent context | Loads promoted skill via the synthetic-`__file__` loader; runs `run(now, db)`. **Also deposits raw candidates to the scoring stream** tagged per skill + `agent_run_id` (D2), independent of later selection. Attaches `geo_focus` = candidate bbox. |
| `emit(selected)` | emitted forecast ids | Terminal. Hands the selected set to the **aggregator** (W3) → `emit_forecasts` with `producer='agent'`. Agent supplies the set, **never `p`.** |

**Critic (ReAct, terminal actions `mutate_skill` / `generate_skill`):**

| Tool | Returns | Notes |
|------|---------|-------|
| `inspect_forecasts(skill_id)` | raw per-skill forecasts + GT matches + Brier trace | Reads the raw scoring stream, not agent-curated production. |
| `list_skills()` | skills + lineage + Brier + override-frequency | Shared with forecaster. |
| `mutate_skill(skill_id)` | proposal id | Invokes the **existing mutator**; output flows the unchanged validation→shadow path. |
| `generate_skill(class, seed)` | proposal id | Invokes the **existing generator**; stays condition-gated/operator-seeded — not sprayed on a tick. |

Both agents' LLM calls go through the one wrapper behind the health gate. Tool dispatch and loop control are hardcoded; only the reasoning steps are model-driven.

---

## 4. Aggregator rule (named-config)

Default, all params in named config (not hardcoded), tunable against observed corroboration:

- **Corroboration:** two+ skills firing on the same hazard class within `corroboration_radius_km` of each other → combine via **noisy-OR** of their individual `p`, then clamp to the **0.85 cap**.
- **Single detection:** one skill on a point → keep that skill's own `p` (unchanged).
- **Conflict:** overlapping same-point forecasts that disagree → the **highest recent-hit-rate skill's** forecast wins the point (no averaging of disagreement).
- **Guard:** never lower `p` on an under-confident skill (p = hit-rate principle preserved). The aggregator can only raise confidence via corroboration, capped.

The aggregator is the *only* place emitted `p` is set for the agent path, and it is identical code for the routine rule path (which is the degenerate single-producer case). This keeps the cap and the p = hit-rate guard in one non-mutable location.

---

## 5. Trace event schema (SSE)

```
{ run_id, seq, step_type: 'thought'|'action'|'observation'|'gated'|'terminal',
  tool: string|null, input: jsonb, output: jsonb (size-capped, reuse 16KB trace discipline),
  geo_focus: GeoJSON bbox | null, ts }
```

- `geo_focus` is populated only by region-scoped tool events (`run_skill`, `inspect_signals(bbox)`); the viewer pans the map when present, holds when null.
- `gated` = health gate refused the cycle (cold-start probe fail or sustained 529). Terminal, non-error.
- `terminal` carries emitted forecast ids (forecaster) or created proposal ids (critic).
- Persisted rows in `agent_step` are the replay source for `GET /agent/run/{id}/replay`.
- Store `geo_focus` as PostGIS geometry (`ST_GeomFromGeoJSON` at the DB boundary, `ST_Force2D(ST_SetSRID(...,4326))`); serialize to GeoJSON on read. Geometry hygiene per house rule.

---

## 6. Concurrency & stop mechanisms

- **Wrapper concurrency:** button-fires and the scheduled critic share the single wrapper + health gate. Bounded `max_in_flight` (named-config); over-limit fires queue or refuse with a `gated` event rather than fanning out uncapped LLM load.
- **Health gate** applies to agent runs exactly as to curator/generator — cold-start pre-flight + rolling-window 529 abort. Independent of `ENVISION_CURATOR_ENABLED`.
- **Operator gate (D10)** is a separate control from both above: it governs *who can trigger a write-capable live fire*, not provider availability or operator intent to run the loop. Public surface never reaches the fire endpoint — only `replay`.

---

## 7. Invariant boundary map

Inside the mutation surface (LLM-authored): mutator `run.py` rewrites, generator de-novo `run.py`. **Nothing else.**

Outside (deterministic, never LLM-authored): AST + sandbox + light viability gate, shadow scoring, selector, Brier evaluator, **0.85 cap**, `forecast_writer.emit_forecasts`, **the aggregator**, **the ReAct loop control + tool dispatch**, **the SSE endpoint**, the LLM wrapper + health gate, `review_proposals.py` + the human gate.

Agents live *between* the reasoning and the deterministic core: they emit tool calls and a final selection/target; the core executes, scores, caps, and gates. An agent can influence *which* deterministic action runs — never *how* it scores, caps, or promotes.

---

## 8. Open risks & deferrals

- **Aggregation calibration.** noisy-OR + `corroboration_radius_km` are named-config; tune once real agent-vs-rule A/B samples (D9) accumulate. Start conservative.
- **Correlated agent+rule forecasts** on the same point are handled by the aggregator's confidence combination *within* an agent run, but the two production writers can still both emit near-duplicate points (no cross-producer dedup, by D9). That's intended — it is the A/B signal — and is *not* the still-deferred diversity penalty (which is a selector concern for shadow candidates, unchanged).
- **`agent_step` growth.** Size-cap `tool_output` (reuse the 16KB trace discipline) and add `agent_step`/`agent_run` to `housekeeping-retention` pruning.
- **JTWC year-parse bug** (still open) leaves the typhoon evaluation pool empty — the forecaster can fire cyclone skills but has thin ground truth to cross-check against until it's fixed. Orthogonal to v4 but bounds what cyclone forecasting the agent can meaningfully do.
- **Cutover to a routine agent schedule** is explicitly *not* in v4. D4 keeps the agent button-only; whether it earns a schedule is decided later on the accumulated A/B evidence.

---

## 9. Definition of done (v4)

1. Migration head advanced; `agent_run`/`agent_step` live; `forecasts.producer` defaults `'rule'`, agent rows carry `agent_run_id`.
2. `forecaster-agent` fires on operator button, runs a real ReAct cycle, deposits raw per-skill output to the scoring stream, and emits an aggregator-priced, provenance-tagged, cap-respecting set to `forecasts`.
3. Aggregator is the sole emitted-`p` author for the agent path and shares code with the rule path.
4. SSE endpoint streams a live run; `replay` re-streams a persisted run; health-gate degradation returns `gated`.
5. `/agent` shows the live trace + tool-use + map spotlight (forecaster) and the standard trace window (critic); producer badges render on forecasts; public surface is replay-only.
6. `critic-agent` reasons over raw per-skill performance and targets `mutate_skill`/`generate_skill`; output clears the unchanged validation→shadow→human-gate path; the curator's mechanical worst-K selection is retired.
7. No new direct SDK call sites; every agent LLM call is through the one wrapper. Tests never write the prod DB.
