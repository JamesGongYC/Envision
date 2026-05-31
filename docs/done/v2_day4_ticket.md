# v2 Day 4 — ECMWF GRIB Ingestion & Curator Migration

**Scope.** The structurally heaviest day of v2. Stand up Modal infrastructure, ship the first Modal-deployed skill (`ecmwf-fire-weather-derived`) for the GRIB → polygon fire weather index pipeline, and migrate the curator from Hermes to Modal as the first instance of the committed option-B architecture. No detector changes — `wildfire-risk-elevated` generalization moves to v2.5 along with its Modal migration.

## Canonical context

Attach via `@`:

- `@docs/envision_plan.md`
- `@docs/v2_plan.md`
- `@docs/v2_day1_ticket.md`, `@docs/v2_day2_ticket.md`, `@docs/v2_day3_ticket.md`
- `@docs/PROGRESS.md`
- `@db/schemas.py`
- `@agent/skills/curator/scripts/run_curator.py` (target of D4 migration; code unchanged, only rehoused)

## Pre-decided

**Inherited:** `run(now, db)` signature; `ST_Force2D(...)` on geometry inserts; hyphenated dir names. Detection skills (not in this ticket) query signals with `AND timestamp <= %s`.

**New for Day 4:**

1. **Option-B committed.** Production runs on Modal long-term. v2.5 sprint after v2 close migrates remaining 9 Hermes skills. Day 4 ships ECMWF + curator as the first two Modal-native skills. v2.5 plan to be drafted at v2 close.

2. **Modal owns ECMWF and curator end-to-end.** Neither skill lives under `~/.hermes/skills/`. Neither is touched by `tools/sync_skills.py`. Repo location: `agent/modal_skills/<id>/` — distinct prefix makes it obvious these bypass the Hermes sync workflow.

3. **No Windows fallback for ECMWF.** `eccodes` system install on Windows is the painful path. Day 4 dev happens via `modal run` (Modal's local-execution mode) on Modal's Linux image.

4. **Variables to fetch from ECMWF Open Data.** Subset of HRES forecast at +24h horizon, 4 variables only:
   - `2t` (2-meter temperature)
   - `2d` (2-meter dewpoint temperature) — depression = 2t − 2d, proxy for RH
   - `10u`, `10v` (10-meter wind components) — magnitude = √(u² + v²)
   - `tp` (total precipitation, 24h accumulation)

   Subsetting keeps downloads to ~50–200 MB per cycle vs. ~26 GB for full HRES.

5. **Fire weather index, 0–4 score.** Per grid cell:
   - `(temp_2m > 30°C)` +
   - `(dewpoint_depression > 15°C)` +
   - `(wind_10m > 25 km/h)` (= 6.9 m/s) +
   - `(precip_24h < 1 mm)`

   Emit polygon signal where `score >= 3`. Threshold tunable via env var `ECMWF_FW_THRESHOLD` (default 3).

6. **Polygon aggregation.** Group contiguous high-score cells into polygons via `shapely.ops.unary_union`. Typical output: 10–100 polygons globally per cycle.

7. **Cadence: 12h.** Tied to ECMWF run cycles (00, 12 UTC). Schedule Modal cron at 04:00 and 16:00 UTC (4h post-run, allowing for Open Data publication delay).

8. **Source string + signal type.** `source='ecmwf_open_data'`, `signal_type='fire_weather_grid'`. Distinct from Open-Meteo's `fire_weather` (point-based forecast index).

9. **Modal cost ceiling.** ECMWF: ~5 min CPU/cycle × 2/day = ~5 hr/month. Curator: <1 min CPU/day. Combined well inside Modal's $30 free credit.

10. **Fallback if Modal infra fights back.** Cut-list per v2_plan §9: defer ECMWF to v2.1, rely on Open-Meteo as substrate substitute. Curator-on-Modal stays even if ECMWF defers (curator migration is independently valuable). Trigger: if Modal setup costs >1 full day without progress on ECMWF, stop and document.

## Deliverables

### D1 — Modal infrastructure scaffolding

One-time platform setup that D2–D4 reuse.

- **Modal secret.** `modal secret create envision-neon DATABASE_URL='<value>' ANTHROPIC_API_KEY='<value>' ENVISION_CURATOR_ENABLED=true`. Single secret carries everything Day-4 deliverables need. **This is a manual precondition** — values aren't in the workspace; operator runs this once before Cursor proceeds.
- **Repo layout.** Create `agent/modal_skills/` directory with a top-level `README.md` explaining this is Modal-native code, not synced by `tools/sync_skills.py`.

**Acceptance:** `modal secret list` shows `envision-neon`; `agent/modal_skills/README.md` committed.

### D2 — ECMWF skill: `agent/modal_skills/ecmwf-fire-weather-derived/`

Net-new Modal-native skill:

- `SKILL.md` — describes the skill, notes Modal-only.
- `app.py` — Modal app definition:
  - Image: `modal.Image.debian_slim().apt_install("libeccodes-dev").pip_install("cfgrib", "xarray", "eccodes", "shapely", "psycopg[binary]", "numpy", "httpx")`
  - Secret: `modal.Secret.from_name("envision-neon")`
  - Function: `@modal.function(image=image, secrets=[...], schedule=modal.Cron("0 4,16 * * *"))` entry point calling `run.run(now, db)`.
- `run.py` — pipeline logic exposed as `def run(now: datetime, db: Connection) -> int` per Day-1 contract. Importable for local-mode testing.

Pipeline inside `run()`:

1. Determine target ECMWF cycle (most recent run preceding `now − 4h`).
2. Download subset GRIB from `https://data.ecmwf.int/forecasts/<YYYYMMDD>/<HH>z/ifs/0p25/oper/...` — verify exact path via ECMWF Open Data docs.
3. Parse with `cfgrib` + `xarray`; load 4 variables, align on lat/lon grid.
4. Compute index per pre-decided (5).
5. Threshold and aggregate contiguous cells via `shapely.unary_union`.
6. Insert one signal per polygon. Payload: score, mean variable values inside polygon, polygon area (km²), cycle timestamp. Geometry: `ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(...), 4326))`. `timestamp` = forecast valid time (run + 24h), not run time.

**Acceptance:** `modal run agent/modal_skills/ecmwf-fire-weather-derived/app.py` from local Git Bash spins up Modal container and executes one cycle without errors (≥1 polygon inserted assuming any region currently meets criteria).

### D3 — Curator migration: `agent/modal_skills/curator/`

Migrate the existing curator from Hermes to Modal. Python logic stays identical — only the invocation harness changes.

- `SKILL.md` — describes the migration; notes that source-of-truth for curator code is now `agent/modal_skills/curator/run.py` (the Hermes copy at `agent/skills/curator/` is retired post-D3).
- `app.py`:
  - Image: `modal.Image.debian_slim().pip_install("psycopg[binary]", "anthropic")`. Lighter than ECMWF — no eccodes.
  - Secret: `modal.Secret.from_name("envision-neon")`.
  - Function: `@modal.function(image=image, secrets=[...], schedule=modal.Cron("0 4 * * *"))` calling `run.run(now, db)`.
- `run.py` — copy the existing `agent/skills/curator/scripts/run_curator.py` here, unchanged. Confirm `run(now, db)` already matches the Day-1 contract from the v2 Day 1 refactor.

Retirement steps:

- The Hermes-side curator cron was never registered (PROGRESS §3: "Pending: hermes cron add..."). Nothing to remove.
- Delete `agent/skills/curator/` from the repo. The runtime copy at `~/.hermes/skills/curator/` becomes an orphan; `tools/sync_skills.py --apply --prune` removes it. (The `references/run-history.md` situation surfaced earlier disappears with the dir.)

**Acceptance:** `modal run agent/modal_skills/curator/app.py` executes one cycle. With seeded eval data the curator either inserts a proposal or skips (depending on whether pending proposals already exist for the highest-Brier-opportunity skill). Modal dashboard shows the scheduled function with next run time at 04:00 UTC.

### D4 — Deployment + verification

- `modal deploy agent/modal_skills/ecmwf-fire-weather-derived/app.py`
- `modal deploy agent/modal_skills/curator/app.py`
- Verify both in Modal dashboard: functions listed, schedules shown, next run times correct.
- Manual triggers via `modal run` to populate first ECMWF cycle and first curator pass.
- Check Neon:
  - `SELECT count(*), max(timestamp) FROM signals WHERE source = 'ecmwf_open_data';`
  - `SELECT count(*), max(proposed_at) FROM skill_edit_proposals WHERE status = 'pending';`
- Refresh `signal_catalog`: `(ecmwf_open_data, fire_weather_grid)` row visible.

**Acceptance:** both functions visible in Modal dashboard; manual runs produced rows in their respective tables.

### D5 — Documentation update

- `docs/METHODS.md` — append section on ECMWF source + polygon aggregation algorithm. Note that curator now runs on Modal; document the kill-switch update path (Modal secret edit, not shell export).
- `viewer/lib/signal-sources.ts` — add `ecmwf_open_data` attribution (link `https://www.ecmwf.int/en/forecasts/datasets/open-data`, license per ECMWF Open Data terms).
- `docs/PROGRESS.md` — Day 4 closeout: Modal infrastructure standing, ECMWF emission cycle verified, curator on Modal with `modal deploy` registered, Hermes-side curator retired.

## Out of scope

- AIFS overlay — Day 5.
- **`wildfire-risk-elevated` detector generalization** — deferred to v2.5 along with the detector's Modal migration. ECMWF polygons land in Neon on Day 4 but won't drive forecasts until v2.5.
- EFFIS/GWIS — still deferred.
- Trace JSONB *population* — Day 6.
- Migrating other Hermes skills (FIRMS, NWS, NHC, JTWC, Open-Meteo, GDACS, detectors, evaluator, housekeeping) — v2.5 sprint.
- ECMWF ensemble (ENS) — HRES only.

## Notes / gotchas

- **Modal secret precondition.** `modal secret create envision-neon ...` MUST run before first `modal run` of either function. Both ECMWF and curator depend on it.
- **Kill switch logistics.** Curator-on-Modal reads `ENVISION_CURATOR_ENABLED` from its secret. To flip: `modal secret create envision-neon ... ENVISION_CURATOR_ENABLED=false` (replaces the secret entirely; include all other fields). Slower than the previous shell export. If this becomes painful, the next refactor is a DB-backed `system_config` flag — not Day 4 scope.
- **ECMWF Open Data delay.** HRES runs at 00/06/12/18 UTC but data isn't published immediately. 4h post-cycle is conservative; verify against actual file listing on `https://data.ecmwf.int/forecasts/`.
- **cfgrib + eccodes version pinning.** Both libraries are finicky. Pin exact versions in the Modal image once you have a working combination. Verify current versions via PyPI when Cursor builds the image.
- **Polygon validity.** After `unary_union`, occasionally produces invalid polygons (self-intersections) for complex contiguous regions. Run `make_valid()` before insert, or PostGIS `ST_MakeValid()` at the DB layer.
- **`signals.timestamp` semantics for ECMWF.** Should be the forecast valid time (run + 24h), not the run time. Detection queries filter on `timestamp <= now`, so valid time is the right anchor.
- **Curator source-of-truth shift.** After D3, the canonical curator code lives at `agent/modal_skills/curator/run.py`. The Hermes-side copy is retired. Don't edit both — they're not synced.
- **Modal logs.** `modal app logs ecmwf-fire-weather-derived` and `modal app logs curator` show stdout/stderr. First place to look when smoke fails.

## Done definition

- D1–D5 acceptance criteria met.
- Modal dashboard shows both scheduled functions with next run times.
- `signal_catalog` includes `(ecmwf_open_data, fire_weather_grid)` row.
- Curator's first scheduled run produces either a proposal or a documented skip.
- Hermes-side `agent/skills/curator/` deleted; runtime orphan pruned.
- `PROGRESS.md` "v2 Day 4 complete" section: Modal infrastructure live, ECMWF emission verified, curator migrated, v2.5 plan flagged for drafting at v2 close.
