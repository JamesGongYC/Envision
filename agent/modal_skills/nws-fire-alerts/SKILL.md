---
name: nws-fire-alerts
description: Modal-only. NWS Alerts API fire-weather events. Every 30 minutes. Requires NWS_USER_AGENT.
---

# nws-fire-alerts (Modal)

`NWS_USER_AGENT` must be set on `envision-neon` secret (e.g. `envision-monitor (you@example.com)`).

## Schedule

`modal.Cron("*/30 * * * *")`

## Deploy

```bash
python -m modal run agent/modal_skills/nws-fire-alerts/app.py
python -m modal deploy agent/modal_skills/nws-fire-alerts/app.py
```
