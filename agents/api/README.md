# Envision agent API (Modal ASGI)

Operator-gated live fire + public replay SSE for the forecaster and critic.

## Deploy

```bash
python -m modal deploy agents/api/app.py
```

ASGI function timeout is **8 minutes** (hard cap on a fire/SSE hold).

## Secret

`envision-neon` must include `ENVISION_OPERATOR_TOKEN` (Bearer for fire routes).
**Recreate replaces the whole secret** — include every existing field:

```bash
python -m modal secret create envision-neon \
  DATABASE_URL='<neon-url>' \
  ANTHROPIC_API_KEY='<key>' \
  ENVISION_CURATOR_ENABLED=true \
  ENVISION_OPERATOR_TOKEN='<long-random-token>' \
  NWS_USER_AGENT='envision-monitor (you@example.com)' \
  FIRMS_MAP_KEY='<firms-map-key>'
```

Optional LLM gate / generator vars as in
[`agent/modal_skills/README.md`](../agent/modal_skills/README.md).

There is **no** `AGENT_MAX_IN_FLIGHT` gate (removed in T9). Provider health-gate
`gated` events from the loops still apply.

If old deploys left stuck rows:

```sql
UPDATE agent_run
SET status = 'failed', finished_at = now(), error = 'stale_running_reaped'
WHERE status = 'running'
  AND started_at < now() - interval '15 minutes';
```

## Routes

| Method | Path | Auth | Behavior |
|--------|------|------|----------|
| POST | `/agent/forecaster/fire` | Bearer operator | Live ReAct run → SSE |
| POST | `/agent/critic/fire` | Bearer operator | Live ReAct run → SSE |
| GET | `/agent/run/{id}/replay` | none | Re-stream persisted steps |

SSE events use `event: step` with the v4 §5 JSON payload.
