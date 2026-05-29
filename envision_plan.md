# Envision — Project Plan

A self-evolving continuous agent for global wildfire and tropical cyclone monitoring, with a public-facing viewer. One-week MVP roadmap.

---

## 1. Decisions log

| Decision | Choice | Rationale |
|---|---|---|
| Disaster classes | Wildfires + tropical cyclones | Complementary timescales (fast/sparse vs. slow/dense); rich open data; aligns with project narrative |
| Forecast horizons | Wildfires 0–24h nowcast; cyclones 6–72h short-range | Matches data cadence and where the agent can add value |
| Agent framework | Nous Research Hermes Agent (model-agnostic) | Provides skill library + Curator + cron + persistent memory + Modal deployment out of the box |
| LLM | Anthropic Claude Sonnet for reasoning/reflection; Haiku optional for routine detection | Cost/quality tradeoff |
| Compute backend | Modal (serverless persistence) | Native Hermes support; free tier sufficient for a week |
| Database | Neon Postgres + PostGIS (free tier) | Serverless, Vercel-friendly, geo-native |
| Object storage | Skip in v1 — everything in Postgres | Simpler; bring R2 in later if needed |
| Viewer | Next.js 14 on Vercel free tier | Reads Neon directly via server components |
| Map | Leaflet + OpenStreetMap tiles | Free, no API key |
| Timeline | 7 days to deployable v1 | Hack roadmap; defers proper backtesting and calibration |

## 2. Explicit non-scope for v1

Deferred to v2 or later:

- Historical replay backtesting
- ECMWF Open Data / GFS / HRRR GRIB ingestion
- Sentinel-2/3 imagery
- Calibration analysis beyond raw Brier score
- Real-time alerting (push, email, SMS)
- User accounts or auth
- Mobile-optimized viewer (desktop only)
- API access for third parties

## 3. Architecture

Bicephalic: agent runtime on Modal + viewer on Vercel, sharing one Neon Postgres.

```
[Open data sources]
        │
        ▼
[Ingestion skills (Hermes cron)]
        │
        ▼
[Postgres: signals] ──────────────────────────┐
        │                                     │
        ▼                                     │
[Detection skills (Hermes cron)]              │
        │                                     │
        ▼                                     │
[Postgres: forecasts] ──────────────┐         │
                                    │         │
[GDACS poller] ──► [Postgres: ground_truth]   │
                                    │         │
                                    ▼         │
                          [Evaluator skill (nightly)]
                                    │
                                    ▼
                          [Postgres: evaluations]
                                    │
                                    ▼
                          [Hermes Curator (24h)]
                                    │
                                    ▼
                          [approval_queue (manual gate)]
                                    │
                                    ▼
                          [Updated skill library]

[Next.js viewer on Vercel] ◄── reads from Postgres
```

## 4. Tech stack

- **Agent runtime**: Hermes Agent (Nous Research, MIT)
- **LLM**: Claude Sonnet via Anthropic API; Haiku as cost fallback
- **Compute**: Modal
- **Database**: Neon Postgres with PostGIS extension
- **Frontend**: Next.js 14 (app router), TypeScript, Tailwind, shadcn/ui
- **Map**: Leaflet + OSM
- **Hosting**: Vercel
- **Geo data**: GHSL global population raster (downloaded once, queried as static asset)
- **Python deps**: `pydantic`, `psycopg`, `shapely`, `scikit-learn` (DBSCAN), `httpx`

## 5. Data sources for v1

### Wildfires
- **NASA FIRMS** active fire detections — `https://firms.modaps.eosdis.nasa.gov/api/area/csv/` — free MAP_KEY required; MODIS + VIIRS; 24h endpoint
- **NWS Alerts API** — `https://api.weather.gov/alerts/active` — JSON, no auth; filter by event ∈ {Fire Weather Watch, Red Flag Warning, Fire Warning}

### Tropical cyclones
- **NHC** (Atlantic + East Pacific) — `https://www.nhc.noaa.gov/CurrentStorms.json` — JSON product feed
- **JMA** Western Pacific — `https://www.jma.go.jp/bosai/typhoon/data/` — JSON, stable format

### Ground truth
- **GDACS** — `https://www.gdacs.org/xml/rss.xml` — used only by the evaluator

All sources are free, public, and permit redistribution with attribution. Attribution shown on every forecast detail page.

## 6. Data schemas

```python
class Signal:
    id: UUID
    timestamp: datetime          # UTC
    source: str                  # 'firms_viirs' | 'nws_alerts' | 'nhc' | 'jma'
    signal_type: str             # 'hotspot' | 'fire_warning' | 'cyclone_advisory'
    geometry: dict               # GeoJSON: point or polygon
    payload: dict                # source-specific fields
    ingested_at: datetime

class Forecast:
    id: UUID
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    disaster_class: str          # 'wildfire' | 'typhoon'
    geometry: dict               # GeoJSON polygon (area of concern)
    probability: float           # capped at 0.85 in v1
    skill_id: str
    skill_version: int
    contributing_signal_ids: list[UUID]
    reasoning: str               # LLM-generated explanation
    is_baseline: bool            # frozen baseline parallel run

class GroundTruthEvent:
    id: UUID
    occurred_at: datetime
    source: str                  # 'gdacs' | 'nhc_postanalysis'
    disaster_class: str
    geometry: dict
    severity: str | None
    payload: dict

class Evaluation:
    id: UUID
    forecast_id: UUID
    matched_ground_truth_id: UUID | None
    outcome: str                 # 'hit' | 'miss' | 'false_positive'
    brier_contribution: float
    evaluated_at: datetime

class SkillEditProposal:
    id: UUID
    proposed_at: datetime
    skill_id: str
    current_version: int
    proposed_code: str
    curator_reasoning: str
    status: str                  # 'pending' | 'approved' | 'rejected'
    reviewed_at: datetime | None
```

## 7. Detection skills (v1 seed library)

| Skill ID | Class | Logic |
|---|---|---|
| `wildfire_risk_elevated` | Wildfire | DBSCAN cluster (eps=10km, min_samples=5) on FIRMS hotspots last 24h, intersecting any active Fire Weather Watch or Red Flag Warning polygon |
| `wildfire_rapid_growth` | Wildfire | Hotspot count in a 50km×50km cell grew >50% day-over-day for 2 consecutive days |
| `typhoon_intensifying` | Typhoon | NHC/JMA bulletin shows central pressure dropping >5 hPa over 12h |
| `typhoon_landfall_imminent` | Typhoon | NHC/JMA forecast cone (next 72h) intersects any coastline with GHSL population >10⁴ within 50km |
| `wildfire_smoke_corridor` *(stretch)* | Wildfire | Active fire cluster upwind of populated area within 200km |
| `typhoon_compound_exposure` *(stretch)* | Typhoon | Active typhoon track within 100km of a region currently under another disaster alert |

Each skill emits 0–N `Forecast` rows per cycle and caps probability at 0.85.

## 8. Hermes Curator configuration

- **Cycle**: 24h (override Hermes default of 7d — we have only days to observe)
- **Grading signal**: Brier score from `evaluations` table over trailing 14d, weighted by recency
- **Mutation scope**: skill parameters and reasoning prompts only; structural changes require manual approval
- **Gating**: every Curator-proposed edit lands in `approval_queue` with `status='pending'`; manual CLI approval required for promotion
- **Frozen baseline**: every skill has a parallel `is_baseline=true` copy that always runs and is never mutated; this is the regression floor
- **Kill switch**: env var `ENVISION_CURATOR_ENABLED=false` halts all mutation

## 9. Viewer (Vercel app)

Three routes:

1. `/` — World map (Leaflet); forecast markers colored by class and probability; popup with summary and link to detail
2. `/forecast/[id]` — Full detail: geometry, probability, time window, reasoning, contributing signals (linked back to sources)
3. `/agent` — Read-only agent log: current skill library, Brier scores per skill, recent Curator activity, public view of approval queue

Implementation rules:
- All data fetching in server components; no client-side fetching
- ISR with 60s revalidation
- Tailwind + shadcn defaults; do not over-design
- Disclaimer banner on every page

## 10. Day-by-day roadmap

### Day 1 — Foundation
- Install Hermes Agent locally; smoke test
- Configure Modal as Hermes execution backend
- Provision Neon Postgres with PostGIS; create tables from schemas
- Wire Anthropic API key
- Disable all chat gateways
- Hello-world skill: poll USGS earthquake feed and write one row

### Day 2 — Ingestion
- Implement four ingestion skills: FIRMS, NWS Alerts, NHC, JMA
- All write to normalized `signals` table
- Add GDACS poller writing to `ground_truth`
- Hermes cron configured: 30min (fires), 3h (cyclones), 6h (ground truth)
- Verify data flowing end-to-end

### Day 3 — Detection
- Implement the five non-stretch detection skills
- Each writes to `forecasts`; baseline frozen copies marked
- Cron configured to fire after ingestion
- Verify forecasts appearing for current active events

### Day 4 — Evaluation and guardrails
- Evaluator skill running nightly; writes Brier scores to `evaluations`
- `approval_queue` table + CLI review tool
- Kill switch wired and tested
- Probability cap enforced at storage layer

### Day 5 — Viewer
- Next.js scaffolded with Tailwind + shadcn
- All three routes built
- Leaflet map with markers
- Deployed to Vercel; domain configured

### Day 6 — Curator on + safety copy
- Hermes Curator enabled with 24h cycle, gated by approval queue
- Disclaimer page and footer copy committed (see §12)
- `METHODS.md` committed to repo
- Final smoke test pass

### Day 7 — Soft launch
- 24h observation window
- Bug fix pass
- Public launch

## 11. Cut list

In order of expendability if behind schedule:

1. JMA connector (NHC covers Atlantic + East Pacific; ~70% of basin coverage)
2. Stretch detection skills (`wildfire_smoke_corridor`, `typhoon_compound_exposure`)
3. `/agent` page (alternative: expose read-only Neon URL)
4. GDACS automation (run as a manual nightly script week 2)

**Never cut**: data normalization, kill switch, disclaimer, probability cap, frozen baseline.

## 12. Disclaimer — locked text

> Envision is an experimental research artifact built to explore self-evolving agent architectures for disaster signal detection. It is **not** an alerting service and must **not** be used for safety-critical decisions. For authoritative information consult the U.S. National Weather Service (weather.gov), the National Hurricane Center (nhc.noaa.gov), the Japan Meteorological Agency (jma.go.jp), or your local emergency management authority. Forecasts published here are produced by an automated system with limited validation and known false-positive rates.

Must appear:
- As a banner on every viewer page
- On the about page in full
- In the `<meta name="description">` (truncated)
- In the GitHub README

## 13. Non-goals

State these loudly:

- Envision does not replace official warning systems
- Envision does not provide individual-location risk assessments
- Envision is not validated against operational forecasting benchmarks
- Envision's confidence calibration is not yet established

## 14. Risks and mitigations

| Risk | v1 mitigation |
|---|---|
| Self-evolution drifts toward false positives | Approval queue gate, frozen baseline runs in parallel, probability cap at 0.85 |
| LLM cost overrun | $50 budget cap; downgrade to Haiku if exceeded; Modal has its own free-tier ceiling |
| Public misinterprets as alerting service | Prominent disclaimer; no push notifications; severity language avoids matching official warning vocabulary |
| Data source TOS violation | All sources public/attribution-only; attribution on every forecast detail page |
| Cold start (<1 week of ground truth) | Curator runs in observation mode for first 14 days; mutation proposals logged but not promoted |
| Hermes framework friction | Day 1 dedicated to foundation; if friction is severe, fall back to LangGraph + custom Curator (cost: +3 days) |

## 15. Open questions deferred to v2

- Support arbitrary regional queries (current is global map only)
- ECMWF/GFS GRIB ingestion for genuine sparse-forecast capability
- Public calibration plots
- Multi-language disclaimer
- API access for third-party tools
- Mobile viewer
- Push to expand to floods, heatwaves, earthquakes

---

## Appendix A — Files Cursor should always have in context

- This file (`envision_plan.md`)
- `schemas.py` (the Pydantic models from §6)
- The current `skill_registry.json` (Hermes auto-maintains)
- `METHODS.md` once written

## Appendix B — Repo layout (target)

```
envision/
├── agent/                  # Hermes Agent skills and config
│   ├── skills/
│   │   ├── ingest/
│   │   ├── detect/
│   │   ├── evaluate/
│   │   └── ground_truth/
│   ├── hermes.toml
│   └── modal_app.py
├── db/
│   ├── migrations/
│   └── schemas.py
├── viewer/                 # Next.js app
│   ├── app/
│   ├── components/
│   └── lib/
├── docs/
│   ├── envision_plan.md   # this file
│   ├── METHODS.md
│   └── architecture_diagram.png
└── README.md
```
