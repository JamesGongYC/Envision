# T14 — Scripted demo run: fixture trace + map choreography

**Goal:** Replace the live-agent Fire path on `/agent` with a **scripted demo run** — hand-written prose over real recorded skill data, stored as fixtures in `viewer/`, rotating across several variants — driven by the full map choreography (eased timeline, input-layer pulse, anchored candidate popups). The Fire forecaster button becomes the demo button.
**Supersedes:** T12 (choreography now consumes fixtures, not live events) and T13 (live prose abandoned).
**Scope:** `viewer/` only. No backend changes, no Modal deploy, no loop work.

House rules: viewer only; preserve producer badges elsewhere on the site, disclaimer/attribution on every page; `git push origin master:main`.

---

## Context
Three attempts to get the loop to emit model reasoning (`thought` steps) failed the same way — the prose channel starves. The demo's value doesn't require live reasoning, so the trace becomes a scripted artifact. The live agent infrastructure (loop, API, aggregator) is untouched and keeps running; only the `/agent` demo surface changes.

## Non-negotiable: no contamination of the scoring signal
1. **The demo must not write to `forecasts`.** Not one row. The Brier evaluator scores that table; fabricated candidates would corrupt the fitness signal the whole evolution loop depends on. The demo is render-only, client-side.
2. **No `agent_run` / `agent_step` rows** from the demo — nothing that a later diagnostic query could mistake for a real run.
3. **No fabricated geography or numbers.** Signal counts, candidate locations, probabilities, and hazard classes all come from recorded rows. Only the reasoning prose is authored.

## Header copy
- Remove the current header text — *"Live ReAct transcript with map spotlight. Public surface replays the last real run; operators can fire a new production cycle."*
- No `DEMO`/`SCRIPTED` badge, no `LIVE · STREAMING` / `RUNNING…` status chip.
- Replace with neutral copy that describes what's shown without asserting real-time execution — e.g. a short line framing it as a walkthrough of a detection pass (reasoning, detector runs, and the resulting forecasts). Do not use the words "live," "streaming," or "production" on this surface.
- The existing site-wide disclaimer and per-source attribution stay.

## Fixture design

### Source: mixed scripted prose + real data
- Take **real recorded outputs** from past runs — actual signal counts per source, actual `input_layers`, actual candidate geometry/locations and their hazard/probability/skill values. Real places, real clusters.
- **Hand-write only the prose** (intent + narration). Everything geographic and numeric stays real so the map reads convincingly and nothing but the reasoning is invented.

### Location & format
- Fixtures live in `viewer/` (e.g. `viewer/fixtures/agent-demo/*.json`) — pure frontend, no API dependency, no deploy risk.
- Each fixture is an ordered step list matching the shape the transcript/player already understands:
  - `thought` → scripted prose (intent before an action; narration after an observation)
  - `action` → `tool`, `skill_id`, `input_layers[]`, `geo_focus`
  - `observation` → structured result (candidate counts etc.)
  - `terminal` → per-candidate `{location, hazard, probability, skill, label}[]`
- Include a per-step `dwell_ms` (or equivalent) so pacing is authored, not guessed.

### Rotation
- **Several variants** (3+), e.g. a wildfire-heavy run, a mixed wildfire/cyclone run, a quiet run that finds little and says so. Rotate per click (cycle or random-without-immediate-repeat) so repeat presses don't replay the identical run.

## Player + choreography (as specified in T12, now fixture-driven)
- **Single eased-timeline player** (`RunPlayer.tsx`) advances the step list on authored pacing, driving transcript and map from the same clock.
- **Prose dominates** the transcript: `thought` blocks are full-width, typing-animated; tool calls are thin collapsed chips expandable to their raw payload.
- **Input-layer pulse:** on each `action`/`run_skill` step, pulse/highlight the signal layer(s) named in `input_layers` (FIRMS hotspots for wildfire skills, cyclone signals for typhoon skills) for that step's dwell; pan/zoom via `geo_focus`.
- **Anchored candidate popups:** on `terminal`, drop a Leaflet popup at each candidate's location with its detail; **persist for the rest of the run**; clear on reset/new run.
- Transcript and map advance in lockstep; no raw coordinates rendered as prose.

## Button behaviour
- The **Fire forecaster button becomes the demo button** — one click starts a scripted run. Available to all visitors (no operator token needed; it writes nothing).
- Remove/disable the live `fire` call from this surface. **Do not delete the backend route** — the live path stays intact server-side, just unreferenced by this button.
- Replace/retire the "public replays last real run" behaviour on this surface, since the demo now serves that purpose.

## Test plan
1. Clicking Fire starts a scripted run; transcript prose dominates, tool chips collapsed/expandable.
2. **Zero network writes:** no `forecasts`, `agent_run`, or `agent_step` rows created by a demo run (verify no `fire` POST is issued).
3. Layer pulse matches `input_layers` per step; map pans via `geo_focus`.
4. `terminal` drops anchored popups at real candidate locations; they persist to run end; clear on reset.
5. Repeated clicks rotate variants (no immediate repeat).
6. Header copy contains no "live"/"streaming"/"production" language and no status chip; no demo badge present.
7. Disclaimer + attribution present; producer badges elsewhere on the site unaffected.

## Acceptance
- [ ] Fire button plays a scripted fixture run; several variants rotate.
- [ ] Fixtures use real signal/candidate data with hand-written prose only.
- [ ] **No DB writes and no live `fire` call from the demo path.**
- [ ] Eased timeline drives transcript + map in lockstep; layer pulse + persistent anchored popups working.
- [ ] Header copy is neutral: no "live"/"streaming"/"production" language, no status chip, no demo badge.
- [ ] Backend loop/API/aggregator untouched.

## Out of scope
Loop/prose work (abandoned), backend changes of any kind, produced-cluster visualization, aggregator/critic behavior.

---

# Appendix A — Authored traces for the three rotating runs

Prose below is final copy. Every `⟨FILL⟩` is a **real-data slot** — populate from recorded rows before shipping (queries in Appendix B). Do not invent geography or numbers: if a slot can't be filled from real data, cut that step rather than fabricate it.

Shared conventions:
- Beat order per tool call: `thought` (intent) → `action` → `observation` → `thought` (narration).
- Prose is first person, concise, no raw lat/lng, no JSON echo.
- `dwell_ms` guidance: thought 2600–4000 (scale with length), action 900, observation 1200. Total run ≈ 60–90s.

---

## Variant 1 — "Wildfire-heavy" (the flagship run)

Shows the full arc including **aggregator corroboration** — two skills agreeing on one region, noisy-OR raising confidence, capped at 0.85. This is the run that demonstrates the architecture, so it should be the first one served.

| # | type | tool / layers | content |
|---|------|---------------|---------|
| 1 | thought | — | "Starting a detection pass. Before running anything I want to see what's actually arrived — there's no point running a detector against a stale feed, so I'll check freshness and volume across every source first." |
| 2 | action | `inspect_signals` · pulse: all signal layers | — |
| 3 | observation | — | ⟨FILL: per-source counts + freshness⟩ |
| 4 | thought | — | "Good coverage on the fire side — ⟨FILL: N⟩ FIRMS hotspots in the last cycle, and the fire-weather fields are current. ⟨FILL: region⟩ is dense enough that something is likely burning at scale. The cyclone feeds are quiet, which is expected right now. I'll focus the pass on wildfire." |
| 5 | action | `list_skills` | — |
| 6 | observation | — | ⟨FILL: 4 skills + recent Brier/hit-rate⟩ |
| 7 | thought | — | "Four detectors available. `wildfire_rapid_growth` is the stronger performer since its last revision — it's looking for day-over-day expansion rather than a single hot day, which is the harder thing to fake. I'll run it first and treat it as my primary read." |
| 8 | action | `run_skill: wildfire_rapid_growth` · pulse: `firms_hotspots`, `open_meteo_fire_weather`, `nws_fire_alerts` · `geo_focus`: ⟨FILL⟩ | — |
| 9 | observation | — | ⟨FILL: N candidates⟩ |
| 10 | thought | — | "⟨FILL: N⟩ areas showing sustained growth. The cluster over ⟨FILL: place⟩ is the one that stands out — it's been expanding two days running, not just flaring. That's the profile that usually precedes a significant event rather than a burn that self-extinguishes." |
| 11 | action | `run_skill: wildfire_risk_elevated` · pulse: `firms_hotspots`, `nws_fire_alerts` · `geo_focus`: ⟨FILL⟩ | — |
| 12 | observation | — | ⟨FILL: N candidates⟩ |
| 13 | thought | — | "This detector works differently — it clusters hotspots and gates on active fire-weather warnings, so it's an independent line of evidence. It's landed on ⟨FILL: place⟩ as well. Two detectors reaching the same region by different routes is worth more than either one alone, so I'll carry both forward and let the aggregator price the overlap." |
| 14 | action | `emit` | — |
| 15 | terminal | popups at ⟨FILL: candidate locations⟩ | ⟨FILL: per-candidate hazard / probability / skill⟩ |
| 16 | thought | — | "Emitted ⟨FILL: N⟩ forecasts. Where both detectors agreed, confidence combines and lands at the 0.85 ceiling — that cap is fixed, so corroboration can raise certainty but never push it past what the evidence supports. The isolated detections keep their own confidence. I don't set these numbers; the aggregator does." |

---

## Variant 2 — "Mixed: cyclone check, wildfire outcome"

Demonstrates ruling something out — the agent spends real steps on cyclones, finds nothing actionable, and says why. Shows judgment rather than just firing everything.

| # | type | tool / layers | content |
|---|------|---------------|---------|
| 1 | thought | — | "Two hazard classes to consider this pass. I'll look at the signal picture first and let the data decide where the attention goes, rather than running all four detectors by rote." |
| 2 | action | `inspect_signals` · pulse: all | — |
| 3 | observation | — | ⟨FILL⟩ |
| 4 | thought | — | "Fire signals are healthy. The cyclone side is thinner than I'd like — ⟨FILL: cyclone source status⟩. I'll still run both typhoon detectors, because ruling a hazard out is worth the two steps; I just won't expect much." |
| 5 | action | `run_skill: typhoon_intensifying` · pulse: cyclone signal layer · `geo_focus`: ⟨FILL: basin⟩ | — |
| 6 | observation | — | `0 candidates` |
| 7 | thought | — | "Nothing intensifying. With the current advisory coverage that's a weak negative rather than a confident all-clear — absence of signal isn't absence of storm. I'll note it as unresolved rather than clear." |
| 8 | action | `run_skill: typhoon_landfall_imminent` · pulse: cyclone signal layer + `populated_places` | — |
| 9 | observation | — | `0 candidates` |
| 10 | thought | — | "Also empty. No track cone is intersecting populated coastline in the current advisories. Both cyclone detectors agree there's nothing to act on, so I'll move to wildfire where the coverage is real." |
| 11 | action | `run_skill: wildfire_rapid_growth` · pulse: `firms_hotspots`, `open_meteo_fire_weather` · `geo_focus`: ⟨FILL⟩ | — |
| 12 | observation | — | ⟨FILL: N candidates⟩ |
| 13 | thought | — | "⟨FILL: N⟩ growth candidates, concentrated around ⟨FILL: place⟩. ⟨FILL: one-line distinguishing detail — terrain, proximity to population, or fire-weather severity⟩. That's enough to forecast on." |
| 14 | action | `emit` | — |
| 15 | terminal | popups at ⟨FILL⟩ | ⟨FILL⟩ |
| 16 | thought | — | "⟨FILL: N⟩ forecasts emitted, all wildfire. The cyclone half of this pass produced nothing — which is the correct outcome, not a failed one. A pass that emits less because the evidence is thin is doing its job." |

---

## Variant 3 — "Quiet run" (restraint)

Shortest variant. The agent looks, finds little, and declines to emit — or emits a single low-confidence forecast. Demonstrates that the system doesn't manufacture alarms, which is the most credible thing a hazard demo can show.

| # | type | tool / layers | content |
|---|------|---------------|---------|
| 1 | thought | — | "Routine pass. Checking what's come in since the last cycle." |
| 2 | action | `inspect_signals` · pulse: all | — |
| 3 | observation | — | ⟨FILL: lower counts⟩ |
| 4 | thought | — | "Quieter than usual. ⟨FILL: N⟩ hotspots, and the fire-weather fields aren't showing the dryness or wind that turns detections into events. Nothing here is obviously urgent, but I'd rather confirm that with a detector than assume it from the signal counts." |
| 5 | action | `run_skill: wildfire_rapid_growth` · pulse: `firms_hotspots`, `open_meteo_fire_weather` | — |
| 6 | observation | — | ⟨FILL: 0 or 1 candidate⟩ |
| 7 | thought | — | "⟨FILL: Nothing meeting the growth threshold / A single marginal candidate over ⟨place⟩⟩. ⟨FILL: The hotspots that are active aren't expanding day over day — they read as isolated burns, not developing events.⟩" |
| 8 | action | `run_skill: wildfire_risk_elevated` · pulse: `firms_hotspots`, `nws_fire_alerts` | — |
| 9 | observation | — | ⟨FILL: 0 candidates⟩ |
| 10 | thought | — | "The second detector agrees — no clusters coinciding with active fire-weather warnings. Two independent reads both coming back empty is a much stronger negative than one." |
| 11 | action | `emit` (empty set, or single candidate) | — |
| 12 | terminal | ⟨FILL: no popups, or one⟩ | ⟨FILL⟩ |
| 13 | thought | — | "⟨FILL: Nothing emitted this pass / One low-confidence forecast emitted⟩. A quiet cycle is a real result. Emitting on weak evidence would cost more than it's worth — false alarms are how a warning system loses the attention it needs when something genuine develops." |

---

## Appendix B — Filling the real-data slots

Pull from production and paste into the fixtures. Read-only; no writes.

```sql
-- Per-source counts + freshness (steps 3 / observation)
SELECT source, count(*), max(timestamp)
FROM signals
WHERE timestamp > now() - interval '24 hours'
GROUP BY source ORDER BY 2 DESC;

-- Real candidate geometry + detail for popups (terminal steps)
SELECT skill_id, hazard_class, probability,
       ST_AsGeoJSON(geometry) AS geom, valid_from, valid_to
FROM forecasts
WHERE producer = 'rule'
  AND created_at > now() - interval '30 days'
ORDER BY created_at DESC
LIMIT 40;

-- Skill roster + recent performance (steps 6 / observation)
SELECT skill_id, status, version FROM skill_lineage WHERE status = 'promoted';
```

**Selection guidance.** Pick one coherent geographic story per variant — candidates clustered in one or two regions, not scattered globally, or the map choreography pans erratically and reads as noise. For Variant 1's corroboration beat, choose a region where **both** `wildfire_rapid_growth` and `wildfire_risk_elevated` actually produced forecasts, so the "two detectors agreed" narration matches the geometry on screen. Round nothing; use the recorded values.

**Cyclone honesty note.** Variant 2's cyclone prose is written to be true whether the feeds are quiet seasonally or degraded by the known JTWC year-parse issue — it says coverage is thin and calls the result a weak negative, which is accurate in either case. Don't rewrite it to claim a confident all-clear.
