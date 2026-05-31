---
name: wildfire-rapid-growth
description: Modal-only. FIRMS grid-cell growth detection with LLM reasoning. Every 30 minutes UTC.
---

# wildfire-rapid-growth (Modal)

Requires `ANTHROPIC_API_KEY` on `envision-neon` for reasoning generation.

## Schedule

`modal.Cron("*/30 * * * *")`

## Deploy

```bash
python -m modal run agent/modal_skills/wildfire-rapid-growth/app.py
python -m modal deploy agent/modal_skills/wildfire-rapid-growth/app.py
```
