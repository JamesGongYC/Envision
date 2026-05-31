# v2 Day 3 — Validation & Health Check

**Scope.** Light day. Confirm the housekeeping-retention skill is refreshing `signal_catalog`, run a one-off per-source validation pass against the six active sources (4 from v1 + 2 from Day 2), check `signals` volume against Neon's free-tier watermark, lightweight verification of viewer attribution. No new ingestion, no detection, no Curator changes.

## Canonical context

Attach via `@`:

- `@docs/envision_plan.md`
- `@docs/v2_plan.md`
- `@docs/v2_day1_ticket.md`, `@docs/v2_day2_ticket.md` (inherited conventions)
- `@docs/PROGRESS.md`
- `@db/schemas.py`
- `@viewer/lib/signal-sources.ts`
- `@agent/skills/housekeeping/housekeeping-retention/scripts/run_retention.py`

## Pre-decided

- `signal_catalog` refresh stays coupled to housekeeping-retention (one daily cron, two purposes). Don't split unless validation surfaces a reason.
- Validation is a one-off script, not a recurring monitor. Operator runs, reads output, signs off in PROGRESS.
- EFFIS/GWIS remains deferred. Days 4–5 (ECMWF derived + AIFS overlay) bring `signal_catalog` to ≥8 distinct pairs; if either slips, EFFIS returns.
- Pre-season tolerance: NHC and JTWC may legitimately have 0 rows. Don't fail validation on this — categorize as "informational, no signal".

## Deliverables

### D1 — Confirm `signal_catalog` refresh is active

Verification only, no code change.

- `hermes cron tick` and watch for the housekeeping-retention run; confirm matview refresh line in output.
- In Neon: `SELECT source, signal_type, row_count, last_seen FROM signal_catalog ORDER BY source;`

**Acceptance:** for sources active in last 24h (FIRMS ×2, NWS, Open-Meteo, GDACS), `last_seen` is within ~24h. NHC/JTWC may be older.

### D2 — `tools/validate_signals.py`

Net-new one-shot validation script. For each of the six sources (`firms_viirs`, `firms_modis`, `nws_alerts`, `nhc`, `open_meteo`, `jtwc`), check:

1. **Row count last 24h.** Warn if 0 for active-season sources; informational for pre-season (`nhc`, `jtwc`).
2. **Geometry validity.** `SELECT count(*) FROM signals WHERE source=X AND ingested_at > now() - interval '24h' AND NOT ST_IsValid(geometry);` — should be 0.
3. **Payload shape.** Sample 5 random rows per source; verify required keys present:
   - FIRMS: `brightness`, `frp`, `confidence`
   - NWS: `event`, `affectedZones` (or polygon)
   - NHC: `name`, `winds`, `pressure`
   - Open-Meteo: `temp_max`, `rh_min`, `wind_max`, `precip_sum`, `score`, `region_name`
   - JTWC: `name`, `lat`, `lon`, `winds`, `pressure`
   - Report missing keys.
4. **Dedup health.** `SELECT count(*), count(DISTINCT dedup_key) FROM signals WHERE source=X AND ingested_at > now() - interval '24h';` — counts should match (trigger drops duplicates BEFORE insert; survivors should all be unique).

Output: Markdown table to stdout; exit 0 on all-pass, 1 on any failure. Read-only against DB.

**Acceptance:** script runs from `~/Downloads/envision/`, all 6 sources pass or fail with clear messages.

### D3 — Volume check + retention decision

Manual check, possible config change.

```sql
SELECT 
  count(*) AS rows,
  pg_size_pretty(pg_total_relation_size('signals')) AS total_size,
  pg_total_relation_size('signals') / NULLIF(count(*), 0) AS bytes_per_row
FROM signals;
```

Decision tree:

- **< 0.2GB** → no action; retention stays at signals 30d / forecasts 60d.
- **0.2–0.4GB** → tighten signals retention from 30d → 14d in `run_retention.py`; re-sync.
- **> 0.4GB** → tighten to 7d AND flag in PROGRESS that Neon paid-tier upgrade is imminent.

Record the chosen window in PROGRESS Day 3 section.

### D4 — Viewer attribution lightweight check

Code review only, no rendering test.

- Review `viewer/lib/signal-sources.ts`: confirm `open_meteo` and `jtwc` entries present with correct URL + license per Day-2 D5.
- `cd viewer && npm run build` — should pass without TypeScript errors.
- Defer end-to-end rendering verification to when a detector actually consumes these signals (post-v2 work).

**Acceptance:** build clean; entries inspected.

## Out of scope

- EFFIS/GWIS — still deferred.
- ECMWF derived index — Day 4.
- AIFS overlay — Day 5.
- Trace JSONB *population* — Day 6.
- Detectors consuming Open-Meteo or JTWC — post-v2.
- Frontend ops surface (per-skill cards, status header) — Day 7.

## Notes / gotchas

- **Validation idempotency.** Read-only against the DB; safe to run repeatedly.
- **Open-Meteo payload shape.** This is the moment to confirm Day-2 D2 produced the intended shape. If `rh_min` is missing because Cursor fell back to hourly-without-aggregation, surface here rather than discovering at Day 6 trace-population time.
- **JTWC 0 rows expected.** Live HTTP 403 from this environment per Day-2 closeout; will resolve on Modal. Categorize as "informational".
- **Retention windows live in skill code.** Tightening from 30d → 14d means editing `run_retention.py` and re-syncing — not a migration. Old rows prune on next housekeeping tick.
- **Dedup health check semantics.** The `BEFORE INSERT` trigger drops duplicates pre-insert, so post-insert row counts should naturally equal distinct-dedup-key counts. If they diverge, something is bypassing the trigger (e.g., raw COPY) — investigate.

## Done definition

- D1–D4 acceptance criteria met.
- `tools/validate_signals.py` committed and passing for all 6 sources.
- Volume check recorded in PROGRESS with retention decision noted.
- `signal_catalog` has 6 distinct `(source, signal_type)` pairs.
- `PROGRESS.md` updated: "v2 Day 3 complete — six sources validated, signals at \<size\>, retention \<window\>".
