# Envision

A self-evolving continuous agent for global wildfire and tropical-cyclone monitoring, with a public viewer.

**Live:** see Vercel deployment

---

## ⚠️ Disclaimer

Envision is an experimental research artifact built to explore self-evolving agent architectures for disaster signal detection. It is **not** an alerting service and must **not** be used for safety-critical decisions. For authoritative information consult the U.S. National Weather Service ([weather.gov](https://www.weather.gov)), the National Hurricane Center ([nhc.noaa.gov](https://www.nhc.noaa.gov)), the Japan Meteorological Agency ([jma.go.jp](https://www.jma.go.jp)), or your local emergency management authority. Forecasts published here are produced by an automated system with limited validation and known false-positive rates.

---

## What it does

- Ingests open-data signals from NASA FIRMS (fires), NWS Alerts (fire weather), and NHC (tropical cyclones).
- Runs four detection skills that convert raw signals into probabilistic forecasts.
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

- **Agent runtime:** Hermes Agent (Nous Research, MIT)
- **LLM:** Anthropic Claude Sonnet
- **Database:** Neon Postgres + PostGIS
- **Viewer:** Next.js 14 (App Router) on Vercel, Tailwind, Leaflet + CARTO tiles
- **Cron:** Hermes-managed, mostly agent-mode

## Repository layout

```
envision/
├── agent/skills/           # source-of-truth copies of all skills
│   ├── ingest/             # FIRMS, NWS, NHC
│   ├── ground_truth/       # GDACS
│   ├── detect/             # 4 detection skills
│   ├── evaluate/           # forecast-evaluator
│   └── curator/            # the self-evolving Curator
├── db/migrations/          # SQL migrations
├── docs/
│   ├── METHODS.md          # full architecture explanation
│   └── SAFETY.md           # kill switch contract, probability cap, etc.
├── tools/                  # operator CLIs
│   ├── review_proposals.py # approval queue review tool
│   └── check_status.py     # kill-switch state check
├── viewer/                 # Next.js viewer (deployed to Vercel)
└── envision_plan.md        # original project plan
```

## Safety

The Curator (the only LLM-driven mutating component) is gated by an environment variable:

```sh
ENVISION_CURATOR_ENABLED=false
```

Set this in `~/.hermes/.env` to halt all mutation. See [`docs/SAFETY.md`](docs/SAFETY.md) for the full safety contract.

Approval of Curator-proposed edits is manual via `tools/review_proposals.py`. Deployment of an approved edit is also manual — the CLI never overwrites skill files on disk.

## License

MIT for code. Source data attribution belongs to each provider — see `/about` on the deployed viewer.

## Status

One-week build. v1 ships with the cuts documented in [`envision_plan.md` §11](envision_plan.md). v2 work is documented in §15 of the same file.
