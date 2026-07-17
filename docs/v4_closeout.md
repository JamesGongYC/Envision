# v4 closeout — Agentic capability layer

**Status:** Code complete (T1–T6). Operator deploy / smoke still required for live production.
**Depends on:** v3 evolution path (mutator, generator, shadow, human gate).
**Blocks:** none (v4 plan ends here).

---

## Goal (restated)

Add an agent layer on top of the existing cron-and-rules system: a **button-fired forecaster** that reasons and selects candidates (aggregator authors `p`), a **scheduled critic** that replaces curator worst-K targeting, **SSE + operator gate** for live fire / public replay, and a **viewer demo** on `/agent`. Exactly two invention points (mutator, generator) remain; agents orchestrate only.

---

## What shipped

### T1 — Schema foundation
- [`db/migrations/012_agent_telemetry.sql`](../db/migrations/012_agent_telemetry.sql) — `agent_run`, `agent_step`; `forecasts.producer` (`rule`|`agent`) + `forecasts.agent_run_id`.
- Numbered **012** (repo head was 011; prior “conditional 012” never existed). Follow-up [`013_llm_call_site_forecaster.sql`](../db/migrations/013_llm_call_site_forecaster.sql) extends `llm_call_log.call_site` for `forecaster` / `critic`.

### T2 — Forecaster harness
- Package [`agents/forecaster/`](../agents/forecaster/) — ReAct loop, tools (`inspect_signals`, `list_skills`, `run_skill`, `emit`), Modal app.
- Raw skill output deposits with `producer='rule'` + `agent_run_id` for fitness; terminal `emit` goes through aggregator interface.
- All LLM calls via `agent/lib/llm_client.py` + health gate. Tests: [`agents/forecaster/test_forecaster.py`](../agents/forecaster/test_forecaster.py).

### T3 — Deterministic aggregator
- [`pipeline/aggregator.py`](../pipeline/aggregator.py) — noisy-OR / conflict / single-detection; env `AGGREGATOR_CORROBORATION_RADIUS_KM`, `AGGREGATOR_P_CAP` (0.85).
- Wired into agent emit + detection skills via `emit_priced` / shared mounts. `pipeline` banned from mutation surface (`skill_validator`).
- Tests: [`pipeline/test_aggregator.py`](../pipeline/test_aggregator.py).

### T4 — SSE + operator gate
- Modal ASGI [`agents/api/`](../agents/api/) — `POST /agent/forecaster/fire`, `POST /agent/critic/fire`, `GET /agent/run/{id}/replay`.
- Bearer `ENVISION_OPERATOR_TOKEN`; concurrency `AGENT_MAX_IN_FLIGHT` (default 2); `gated` on health / capacity.
- Loop hooks: `on_step` + `commit_each_step` for streaming. Tests: [`agents/api/test_api.py`](../agents/api/test_api.py).

### T5 — Viewer demo
- [`viewer/app/agent/`](../viewer/app/agent/) — ForecasterDemo + CriticDemo; SSE client; Next proxies under `viewer/app/api/agent/`.
- Map spotlight from `geo_focus`; `producer` badges on map / dropdown / detail / legend.
- Operator Fire only when server has `ENVISION_OPERATOR_TOKEN`; public auto-replays last run.

### T6 — Critic agent
- Package [`agents/critic/`](../agents/critic/) — tools (`list_skills`, `inspect_forecasts` on `producer='rule'`, `mutate_skill`, gated `generate_skill`), ReAct loop, Modal app.
- [`orchestrator.run_evolution_pass`](../agent/evolution/orchestrator.py): keeps seeded generator block; **replaces worst-K mutate loop** with `run_critic_loop(..., trigger="scheduled")`; `select_candidates` unchanged.
- T4 critic fire stub removed — real streaming loop. Tests: [`agents/critic/test_critic.py`](../agents/critic/test_critic.py).

### Invariants preserved
- Agents do not author scored `p`, do not write production `run.py`, do not promote.
- Human gate remains `tools/review_proposals.py` → operator `modal deploy` of skills.
- Generator stays condition-gated / operator-seeded (not sprayed on plain daily tick).
- No direct `anthropic` imports under agent packages (wrapper only).

---

## What did not ship / did not work yet (operator + deferred)

### Not done in-repo (ops closeout)
These are **operator steps**, not missing tickets:

| Item | Why it matters |
|------|----------------|
| Redeploy Modal apps | `agents/api`, `agents/critic`, `agents/forecaster`, **curator** (ships critic wiring + `agents/` mount) |
| Secret `envision-neon` | Must include `ENVISION_OPERATOR_TOKEN` (recreate replaces **all** fields — easy to wipe keys) |
| Vercel env | `ENVISION_AGENT_API_URL` → Modal ASGI URL; optional `ENVISION_OPERATOR_TOKEN` for Fire buttons |
| Live smoke | Fire forecaster/critic on `/agent`; confirm critic on curator cron; proposals still need human review |
| Promote path | Critic proposals still wait shadow N≥20 + `review_proposals` — no auto-live skills |

Until those land, production still runs the **pre-T6** curator (worst-K) and may still see critic fire as stub if API was never redeployed after T6.

### Explicitly out of scope (by plan)
- Mutator / generator internals, shadow clock rules, promotion UX redesign.
- Routine (scheduled) forecaster — remains **button-only** (D4); schedule cutover deferred until A/B evidence.
- Cross-producer dedup of near-duplicate agent vs rule points — intentional A/B signal (D9).
- Diversity penalty on selector — still deferred from v3.
- Aggregator calibration against real corroboration — start conservative; tune later.
- Viewer “critic polish” beyond the T5 window.

### Known open risks (from v4 plan §8)
- **`agent_step` growth** — size-cap tool output + add `agent_run`/`agent_step` to housekeeping retention (not verified as done in this closeout).
- **JTWC year-parse bug** (pre-existing) — thin typhoon GT pool; cyclone agent runs are weakly evaluable until fixed.
- **Modal cron budget** — workspace may already be at cron limit; new apps may need plan upgrade or manual-only deploy.
- **Aggregation params** uncalibrated until enough agent-vs-rule samples exist.

### Test / acceptance gaps vs ticket wording
- T6 ticket acceptance includes “parity: candidates still reach shadow at ≥ old rate on same fixtures” — covered by unit/mocks wiring, **not** a live shadow-rate A/B measurement in CI.
- End-to-end “proposal appears in `review_proposals list` after real LLM mutate” requires a live run against Neon (tests mock mutator; prod writes forbidden in unit tests by design).

---

## Architecture snapshot (after v4)

```
rule cron skills ──► emit_priced (aggregator) ──► forecasts (producer=rule)
button forecaster ──► ReAct ──► emit ──► aggregator ──► forecasts (producer=agent)
curator cron ──► health gate ──► optional generator (seeded)
              ──► critic ReAct ──► mutate/generate ──► validate → shadow → human gate
operator /agent Fire ──► Modal ASGI SSE ──► same loops
public /agent ──► replay only (persisted agent_step)
```

---

## Key paths

| Area | Path |
|------|------|
| Plan | [`docs/v4_plan.md`](v4_plan.md) |
| Tickets | [`docs/T1_…`](T1_migration_agent_telemetry.md) … [`T6_…`](T6_critic_agent.md) |
| Agents | [`agents/`](../agents/) |
| Aggregator | [`pipeline/`](../pipeline/) |
| Curator orchestrator | [`agent/evolution/orchestrator.py`](../agent/evolution/orchestrator.py) |
| API deploy notes | [`agents/api/README.md`](../agents/api/README.md) |
| Human gate | [`tools/review_proposals.py`](../tools/review_proposals.py) |

---

## Operator checklist (next)

1. Confirm migrations **012** + **013** applied on Neon.
2. Ensure `envision-neon` has operator token + all existing keys.
3. `modal deploy` API, critic, forecaster, curator.
4. Set Vercel `ENVISION_AGENT_API_URL` (+ token if Fire desired); redeploy viewer.
5. Smoke Fire + replay; after critic/curator, `python tools/review_proposals.py list`.
6. Leave generator env vars off unless intentionally seeding a de-novo skill.

---

## Suggested follow-ons (not v4)

1. Retention / size-cap for `agent_step` rows.
2. Fix JTWC year-parse for typhoon evaluation depth.
3. Tune aggregator radius/cap from live A/B.
4. Decide whether forecaster earns a schedule (requires evidence + cron budget).
5. Update [`docs/PROGRESS.md`](PROGRESS.md) live handoff with v4 section (if not already).

---

## Definition of done (code vs live)

| Plan DoD | Code | Live |
|----------|------|------|
| Schema + provenance | Done | Confirm on Neon |
| Forecaster + raw deposit + aggregator emit | Done | Deploy + Fire smoke |
| Aggregator sole `p` author (agent path) | Done | — |
| SSE fire + replay + gated | Done | Deploy API + env |
| Viewer demo + producer badges | Done | Vercel env + redeploy |
| Critic replaces worst-K; human gate intact | Done | Redeploy curator + smoke |
| Wrapper-only LLM; tests no prod writes | Done | — |
