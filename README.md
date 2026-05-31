# Envision

A self-evolving continuous agent for global wildfire and tropical-cyclone monitoring, with a public viewer.

**Live:** see Vercel deployment

---

## ⚠️ Disclaimer

Envision is an experimental research artifact built to explore self-evolving agent architectures for disaster signal detection. It is **not** an alerting service and must **not** be used for safety-critical decisions. For authoritative information consult the U.S. National Weather Service ([weather.gov](https://www.weather.gov)), the National Hurricane Center ([nhc.noaa.gov](https://www.nhc.noaa.gov)), the Japan Meteorological Agency ([jma.go.jp](https://www.jma.go.jp)), or your local emergency management authority. Forecasts published here are produced by an automated system with limited validation and known false-positive rates.

---

## What it does

- Ingests open-data signals from NASA FIRMS, NWS, NHC, Open-Meteo, JTWC, ECMWF HRES/AIFS (via Modal).
- Runs four detection skills on Modal that convert raw signals into probabilistic forecasts (LLM reasoning with templated fallback).
- Evaluates forecasts against GDACS ground-truth events, scoring each with a Brier contribution.
- A daily Curator skill reads 14-day Brier statistics and proposes parameter adjustments via Claude, gated behind a manual approval queue.
- Publishes a public, read-only viewer with the live map, per-forecast detail pages, and an agent log.

See [`docs/METHODS.md`](docs/METHODS.md) for the architecture.

## Non-goals

- Envision does not replace official warning systems.
- Envision does not provide individual-location risk assessments.
- Envision is not validated against operational forecasting benchmarks.
- Envision's confidence calibration is not yet established.

## Stack

- **Agent runtime:** [Modal](https://modal.com/) scheduled functions (v2.5+)
- **LLM:** Anthropic Claude Sonnet (detection reasoning + Curator)
- **Database:** Neon Postgres + PostGIS
- **Viewer:** Next.js (App Router) on Vercel, Tailwind, Leaflet + CARTO tiles
- **Legacy:** Hermes Agent tree archived under `agent/_archive/skills/` (historical reference)

## Repository layout

```
envision/
├── agent/
│   ├── lib/                # trace_builder, reasoning_llm, reasoning_prompts
│   ├── modal_skills/       # all live skills (ingest, detect, evaluate, curator)
│   └── _archive/skills/    # retired Hermes skill copies (v2.5 Day 3)
├── db/migrations/          # SQL migrations
├── docs/
│   ├── METHODS.md          # full architecture explanation
│   └── SAFETY.md           # kill switch contract, probability cap, etc.
├── tools/                  # operator CLIs
│   ├── review_proposals.py # approval queue review tool
│   ├── check_status.py     # kill-switch state check
│   └── _archive/           # retired sync_skills.py
├── viewer/                 # Next.js viewer (deployed to Vercel)
└── envision_plan.md        # original project plan
```

## Operator setup

1. Modal: `pip install modal` → `python -m modal setup`
2. Secret `envision-neon` — see [`agent/modal_skills/README.md`](agent/modal_skills/README.md)
3. Deploy skills: `python -m modal deploy agent/modal_skills/<skill>/app.py`
4. Windows: `$env:PYTHONUTF8='1'` before `modal run` / `modal deploy`

Hermes cron and `tools/sync_skills.py` are **retired** as of v2.5. Do not delete `~/.hermes/.env` (historical keys).

## Safety

The Curator (the only LLM-driven mutating component) is gated by an environment variable on the Modal secret:

```sh
ENVISION_CURATOR_ENABLED=false
```

See [`docs/SAFETY.md`](docs/SAFETY.md) for the full safety contract.

Approval of Curator-proposed edits is manual via `tools/review_proposals.py`. Deployment of an approved edit is also manual — the CLI never overwrites skill files on disk.

## License

MIT for code. Source data attribution belongs to each provider — see `/about` on the deployed viewer.

## Status

v2.5 complete in repo: all skills on Modal, polygon map layers, forecast dropdown with typing reasoning. Operator: Vercel deploy + git tag `v2.5.0`.
