# T5 — Viewer demo layer (forecaster spotlight + critic window + provenance)

**Goal:** On `/agent`, an operator can live-fire the forecaster and watch its reasoning trace, tool use, and a map spotlight that follows its attention; the public sees a read-only replay of the last real run. The critic gets a standard trace window (no map). Forecasts render their `rule`/`agent` provenance.
**Depends on:** T4. **Blocks:** none.

House rules apply. Disclaimer banner + per-source attribution stay on every page (invariant).

---

## Context
D10 (live-fire operator-gated; public = replay-only), D7 (map spotlight from `geo_focus`), D9 (producer badge). Reuse the existing viewer stack: Next.js 14, Leaflet + OpenStreetMap, the typing-animated reasoning component, React Flow lineage tree.

## Files (confirm paths under `viewer/`)
- `viewer/app/agent/page.tsx` — add the demo section.
- `viewer/components/agent/TracePanel.tsx` — thought/action/observation stream (reuse typing animation).
- `viewer/components/agent/ToolUseCards.tsx` — per-step tool cards + lightweight data viz.
- `viewer/components/agent/MapSpotlight.tsx` — drives the existing Leaflet map from `geo_focus`.
- `viewer/components/agent/FireControl.tsx` — operator-gated fire button; hidden/disabled for public.
- `viewer/lib/sse.ts` — SSE client for `fire`/`replay`.
- Forecast rendering components — add the `producer` badge.

## Forecaster demo
- **Fire control:** operator-gated. Operator presence is established by holding the token (kept server-side / in an operator-only env, never shipped to public bundles). Public users: the Fire control is absent/disabled and the page auto-loads `replay` of the last real run.
- **Trace panel:** streams `thought`/`action`/`observation` via SSE, typing-animated to match existing reasoning UX. `gated`/`terminal` render as end states.
- **Tool-use cards:** one card per action step — `inspect_signals` shows per-source counts/freshness; `run_skill` shows a candidate table; `emit` shows the selected set. Keep viz lightweight (counts, small tables), not heavy charts.
- **Map spotlight:** on each step with non-null `geo_focus`, pan/zoom the existing Leaflet map to that envelope; hold position when null. Draw agent-emitted candidates as they appear, badged `agent`.

## Critic demo
- **Standard window, no map.** Trace panel + tool-use cards + the data it reads: per-skill Brier, the existing React Flow lineage tree, ground-truth matches. `mutate`/`generate` terminal steps link to the resulting proposal in the review queue.

## Provenance
- `rule` vs `agent` forecasts visually distinct everywhere they render (badge/color), per D9.

## Live vs replay
- Live: subscribe to `POST …/fire` SSE (operator only).
- Replay: subscribe to `GET …/run/{id}/replay` SSE (public). Identical rendering path — same components, same map spotlight — only the source differs.

## Test plan
1. Operator (token present) can live-fire; trace + spotlight + emitted candidates render in real time.
2. Public (no token) sees no Fire control and gets replay of the last run; no fire request is issuable from the public bundle.
3. Map recenters on `run_skill`/`inspect_signals(bbox)` steps, holds on `thought` steps.
4. `rule` and `agent` forecasts are distinguishable in the map + lists.
5. Critic window renders trace + lineage + Brier with no map; terminal step links to the proposal.
6. Disclaimer banner + attribution present on the page.

## Acceptance
- [ ] Operator live-fire renders live trace, tool cards, map spotlight, and badged emitted candidates.
- [ ] Public surface is replay-only; Fire control never reaches public users.
- [ ] Spotlight follows `geo_focus`; holds on null.
- [ ] Producer badges render across the viewer.
- [ ] Critic window is trace+tools+data, no map; links to proposals.

## Out of scope
Any change to the fire/replay contract (T4) or the agents themselves (T2/T6).
