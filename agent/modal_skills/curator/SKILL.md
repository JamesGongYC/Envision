---
name: curator
description: Modal-native curator. Reads 14-day Brier stats, proposes detection-skill parameter edits via Claude. Gated by ENVISION_CURATOR_ENABLED in Modal secret envision-neon.
version: 0.2.0
---

# curator (Modal)

**Source of truth:** `agent/modal_skills/curator/run.py` (Hermes copy retired Day 4).

The entrypoint stages detection scripts from the repo into `~/.hermes/skills/` inside the container before each run so `find_skill_script()` works unchanged.

## Cadence

Modal cron **04:00 UTC** daily.

## Kill switch

Set `ENVISION_CURATOR_ENABLED=false` in Modal secret `envision-neon` (must re-create secret with all keys).

## Run

```bash
python -m modal run agent/modal_skills/curator/app.py
python -m modal deploy agent/modal_skills/curator/app.py
```

Requires `DATABASE_URL` and `ANTHROPIC_API_KEY` in `envision-neon`.
