# METHODS

How Envision works, end to end.

## 1. Data flow

```
Open data sources                       Authoritative ground truth
─────────────────                       ─────────────────────────
NASA FIRMS  ─┐                                  GDACS
NWS Alerts  ─┼──► signals                        │
NHC         ─┘                                   ▼
                  │                          ground_truth
                  ▼
                detectors
                  │
                  ▼
                forecasts ◄──┐
                  │           │
                  ▼           │
              evaluator ──────┘
                  │
                  ▼
              evaluations ──► Curator ──► skill_edit_proposals
                                              │
                                              ▼
                                         (human approval gate)
                                              │
                                              ▼
                                         updated skill code on disk
```

## 2. Ingestion

Four ingestion skills run on Hermes cron, polling each source on its appropriate cadence:

| Skill | Source | Cadence | Writes |
|---|---|---|---|
| `firms-active-fires` | NASA FIRMS VIIRS + MODIS | 30 min | `signals` (hotspot) |
| `nws-fire-alerts` | NWS Alerts API | 30 min | `signals` (fire_warning) |
| `nhc-cyclones` | NHC CurrentStorms.json | 3 h | `signals` (cyclone_advisory) |
| `gdacs-poller` | GDACS GeoRSS | 6 h | `ground_truth` |

Every signal is dedup'd via a payload hash trigger (migration 002) and stored in 2D WGS84.

## 3. Detection

Four detection skills convert raw signals into probabilistic forecasts. Each writes one or more `forecasts` rows per cycle, with `probability` capped at 0.85 by a database `CHECK` constraint.

| Skill | Logic |
|---|---|
| `wildfire_risk_elevated` | DBSCAN cluster (eps=10km, min_samples=5) on last-24h FIRMS hotspots; cluster geometry intersected with active NWS fire-weather alert polygons. |
| `wildfire_rapid_growth` | 50km grid cell in EPSG:3857; hotspot count must grow >50% day-over-day for 2 consecutive days. |
| `typhoon_intensifying` | NHC bulletin central pressure dropping >5 hPa over a ~12h window (±2h tolerance). |
| `typhoon_landfall_imminent` | Forward-extrapolated 72h cone from heading + speed, buffered with growing radii (40km → 200km), intersected with GeoNames cities of pop ≥ 10⁴. |

Forecast geometry is GeoJSON polygon; reasoning is templated (no LLM call at detection time, for cost reasons). Validity windows are 24h for wildfires, 48–72h for cyclones.

## 4. Evaluation

A nightly evaluator skill matches expired forecasts against GDACS ground-truth events:

- Disaster class must match (with aliases for GDACS code variants)
- Event must have occurred between `valid_from - 6h` and `valid_until + 12h`
- Geometries must intersect (`ST_Intersects`)

Each evaluation writes one row with `outcome ∈ {'hit', 'false_positive'}` and `brier_contribution = (probability − outcome_value)²`. `outcome_value` is 1 for hit, 0 for false positive. `miss` is a defined value but not computed in v1 because we don't generate low-probability forecasts.

The evaluator waits 12h past `valid_until` before scoring, so GDACS has time to publish.

## 5. Curation

Once daily, the Curator skill reads 14-day Brier statistics per detection skill and proposes parameter adjustments via Claude (`claude-sonnet-4-6`).

**Scope is enforced by prompt, not by sandbox.** The Curator is told it may only change numeric constants and templated reasoning strings — not function signatures, control flow, imports, SQL, or schema. The output is validated for Python syntax but not for semantic safety. Human review at promotion time is the real safety bar.

Every proposal lands in `skill_edit_proposals` with `status='pending'`. The Curator never writes to skill files on disk.

## 6. Approval workflow

```
curator → skill_edit_proposals (status='pending')
                │
                ▼
       tools/review_proposals.py list
                │
                ▼
       tools/review_proposals.py show <id>     ← human reads the diff
                │
                ▼
       tools/review_proposals.py approve <id>  ← row marked approved
                │
                ▼
       operator manually copies the proposed_code into the live
       skill file, increments the version, restarts cron.
```

The `approve` command does not overwrite files. This is intentional. The CLI marks the row's status and prints the deployment path; the operator does the file replacement manually. Rollback is also manual: revert the script, decrement the version.

## 7. Probability cap

`forecasts.probability` has a `CHECK (probability >= 0.0 AND probability <= 0.85)` constraint. Any skill that tries to write a higher value raises a database error. This is the hard ceiling on confidence.

## 8. Kill switch

`ENVISION_CURATOR_ENABLED=false` (in `~/.hermes/.env` or the environment) causes the Curator to exit immediately at the top of its cycle. It does not stop:
- Detection skills from running
- The evaluator from running
- The viewer from displaying data
- Pending proposals from being reviewed

To halt detection itself, remove the corresponding cron jobs with `hermes cron remove <id>`. To halt the viewer, undeploy from Vercel.

## 9. Known limitations

- **No baseline twin.** Plan §8 called for a frozen `is_baseline=true` copy of every skill running in parallel as a regression floor. This was cut for MVP. If a promoted mutation makes a skill worse, only manual rollback recovers.
- **No recency weighting.** Plan §8 called for Brier scores weighted by recency. We use a flat 14-day mean.
- **No JMA.** Plan §11 cut JMA Western Pacific ingestion. NHC covers Atlantic and East Pacific only.
- **NHC cone is approximated.** Real NHC cones come from ensemble track-error statistics; we extrapolate from heading + speed buffered with rough radii.
- **GHSL substitute.** Plan §7 called for the GHSL population raster; we substituted GeoNames cities with pop ≥ 10⁴.
- **Reasoning is templated.** Plan §6 schema describes `reasoning` as LLM-generated. We template it at detection time for cost; the LLM is only used in the Curator.
- **Probability calibration not validated.** No published calibration plots. Brier scores accumulate but the threshold for "well-calibrated" is not formally defined for v1.

## 10. Operational defaults

| Setting | Value | Where |
|---|---|---|
| Ingestion cadence (FIRMS, NWS) | 30 min | cron |
| Ingestion cadence (NHC) | 3 h | cron |
| Ingestion cadence (GDACS) | 6 h | cron |
| Detection cadence (wildfire) | 30 min | cron |
| Detection cadence (typhoon) | 3 h | cron |
| Evaluator cadence | 24 h | cron |
| Curator cadence | 24 h | cron |
| Probability cap | 0.85 | DB constraint |
| Evaluation grace period | 12 h after valid_until | evaluator |
| Brier window | 14 days | curator |
| Min evaluations for curation | 5 | curator |
| ISR revalidation (viewer) | 60 s | Next.js |
