---
name: jtwc-cyclones
description: Modal-only. JTWC ATCF a-deck parser for WP cyclones. Every 6 hours UTC.
---

# jtwc-cyclones (Modal)

Live fetch from `metoc.navy.mil`. If HTTP 403, set `JTWC_USER_AGENT` in Modal secret to a browser-like string.

Fixture: `fixtures/sample_wp.dat` for local/parser tests (`--fixture fixtures/sample_wp.dat`).

## Schedule

`modal.Cron("0 */6 * * *")`

## Deploy

```bash
python -m modal run agent/modal_skills/jtwc-cyclones/app.py
python -m modal deploy agent/modal_skills/jtwc-cyclones/app.py
```
