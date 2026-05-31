# v2 Day 7 — Frontend Ops Surface

**Scope.** Frontend-only day. Replace the existing `/agent` stats table with per-skill cards (description, version, Brier, hits/false-alarms, sparkline). Add a fixed explainer block at top of `/agent`. Add a status header on every page (skills active, last ingestion, curator activity). No backend changes — Day 7 reads from data Days 1–6 already produced.

## Canonical context

Attach via `@`:

- `@docs/envision_plan.md` §9 (viewer routes)
- `@docs/v2_plan.md`
- `@docs/PROGRESS.md`
- `@viewer/app/layout.tsx`
- `@viewer/app/agent/page.tsx`
- `@viewer/lib/skill-metadata.ts`
- `@viewer/lib/agent-queries.ts`
- `@viewer/lib/kill-switch.ts`
- `@viewer/lib/db.ts`

## Pre-decided

**Inherited from v1 viewer conventions:** Server components only; no client-side fetching except where interactivity strictly requires it. ISR with 60s revalidation. Tailwind + shadcn defaults; no over-design. Disclaimer banner stays on every page.

**New for Day 7:**

1. **Status header is a server component.** Fetches three values per ISR revalidation: distinct skill_id count from last 24h forecasts, max(ingested_at) from signals, max(proposed_at) from skill_edit_proposals (proxy for curator activity). Renders inline above the disclaimer banner; coexists with it, doesn't replace it.

2. **Curator status is inferred, not authoritative.** Post-Day-4 the curator lives on Modal and reads `ENVISION_CURATOR_ENABLED` from a Modal secret. The viewer (Vercel) cannot read Modal secrets. Display "Curator active — last run X ago" based on `max(proposed_at)` instead. If >30h since last proposal, render as "Curator inactive (stale)" — operator investigates. Authoritative kill-switch UI is a `system_config` table for v2.5+; out of scope here.

3. **Per-skill cards replace the stats table on `/agent`.** Grid layout, responsive (1 column mobile, 2 desktop). Each card pulls: skill_id, description from `skill-metadata.ts`, latest version present in forecasts, mean Brier across all evals (4-digit precision), hit count, false-positive count, and a sparkline of Brier per version. Cards ordered by `skill_id` alphabetically.

4. **Sparkline is inline SVG, no chart library.** A skill with N versions yields N data points; render as ~80×24px SVG with a polyline. Three or fewer versions → render as discrete bars instead of line (a line through 2 points is ambiguous). No tooltips on sparkline; precise numbers go in the card's main fields.

5. **Tooltip pattern for technical terms.** Brier, hit, false-positive get hover-tooltip definitions. Use native HTML `title` attribute (server-component-friendly) for simplicity; upgrade to shadcn's Tooltip later if interaction richness matters. The tooltip text is the canonical operator-facing definition — write it once, reuse in `/about` page and `METHODS.md`.

6. **Explainer block at top of `/agent` is 3 sentences max.** Plain language. Audience: a curious operator or visitor who doesn't yet know what they're looking at. Lock the text in this ticket; don't outsource the wording to Cursor.

7. **`skill-metadata.ts` becomes the canonical operator-facing description source.** Day 7 fills it out for all current skills (4 detection + 4 ingestion + 1 evaluator + 1 retention + 1 curator + AIFS multi-emission). Each entry: `{id, displayName, plainDescription, category}`.

## Deliverables

### D1 — Status header

`viewer/components/status-header.tsx` — server component. Renders:

```
Envision   |   12 skills active   |   Last ingestion: 4 min ago   |   Curator: active (last run 18h ago)
```

Data source via `viewer/lib/agent-queries.ts` (add three new queries):

- `getActiveSkillCount()`: `SELECT count(DISTINCT skill_id) FROM forecasts WHERE issued_at > now() - interval '24 hours'`
- `getLastIngestionTimestamp()`: `SELECT max(ingested_at) FROM signals`
- `getLastCuratorActivity()`: `SELECT max(proposed_at) FROM skill_edit_proposals`

Add to `viewer/app/layout.tsx` between `<html>` and the existing disclaimer banner. Style: thin slate background, monospace numbers, small text — looks like a status bar, not navigation.

Time-ago formatting: "4 min ago", "18h ago", "2d ago". Plain function in `viewer/lib/time-ago.ts`.

**Acceptance:** header appears on `/`, `/forecast/[id]`, `/agent`, `/about`. Numbers are accurate to within the ISR window.

### D2 — `skill-metadata.ts` update

Expand existing file with all current skills (12+ entries by end of v2 Day 6). Each entry:

```ts
{
  id: 'wildfire-risk-elevated',
  displayName: 'Wildfire Risk Elevated',
  plainDescription: 'Detects clusters of fire hotspots in regions currently under official fire weather warnings. Flags areas where active fires meet pre-warned conditions.',
  category: 'detection'  // 'detection' | 'ingestion' | 'evaluation' | 'curation' | 'housekeeping'
}
```

**Required entries (write descriptions for each):**

Detection: `wildfire-risk-elevated`, `wildfire-rapid-growth`, `typhoon-intensifying`, `typhoon-landfall-imminent`.

Ingestion: `firms-active-fires`, `nws-fire-alerts`, `nhc-cyclones`, `jtwc-cyclones`, `open-meteo-fire-weather`, `gdacs-ground-truth`, `ecmwf-fire-weather-derived`, `aifs-overlay`.

Other: `forecast-evaluator`, `curator`, `housekeeping-retention`.

Descriptions: 1–2 plain sentences. No jargon. Audience is someone who doesn't know what Brier scores or DBSCAN are.

**Acceptance:** every skill emitting forecasts or signals has a metadata entry. Card rendering in D3 fails gracefully (shows skill_id only) if metadata is missing — but for Day 7 done, no skill should be missing.

### D3 — Per-skill cards on `/agent`

Rewrite `viewer/app/agent/page.tsx`'s skill stats section. Replace existing table with `<SkillCard>` components in a grid.

`viewer/components/skill-card.tsx` — server component receiving props:

```ts
type SkillCardProps = {
  id: string
  displayName: string
  plainDescription: string
  currentVersion: number
  brierMean: number  // 4 decimal places
  hits: number
  falsePositives: number
  brierByVersion: { version: number, brier: number }[]
}
```

Card layout:
- Header: displayName + version badge (v3, v2, etc.)
- Body: plain description
- Stats row: Brier (with tooltip), Hits (with tooltip), False positives (with tooltip)
- Sparkline: 80×24px SVG (D4)

Query layer: extend `viewer/lib/agent-queries.ts` with:

```sql
-- per-skill aggregates
SELECT 
  f.skill_id,
  max(f.skill_version) AS current_version,
  avg(e.brier_contribution) AS brier_mean,
  sum(CASE WHEN e.outcome = 'hit' THEN 1 ELSE 0 END) AS hits,
  sum(CASE WHEN e.outcome = 'false_positive' THEN 1 ELSE 0 END) AS false_positives,
  count(e.*) AS eval_count
FROM forecasts f
LEFT JOIN evaluations e ON e.forecast_id = f.id
WHERE f.issued_at > now() - interval '30 days'
GROUP BY f.skill_id;

-- per-version Brier (for sparkline)
SELECT f.skill_id, f.skill_version, avg(e.brier_contribution) AS brier
FROM forecasts f JOIN evaluations e ON e.forecast_id = f.id
WHERE f.issued_at > now() - interval '30 days'
GROUP BY f.skill_id, f.skill_version
ORDER BY f.skill_id, f.skill_version;
```

Order cards alphabetically by skill_id. If a skill has no evaluations yet, show the card with "—" in stat fields.

**Acceptance:** `/agent` page shows cards instead of table; each card has accurate numbers; cards render even when underlying skill has zero evaluations.

### D4 — Sparkline component

`viewer/components/brier-sparkline.tsx` — server component, pure SVG.

```ts
type SparklineProps = {
  data: { version: number, brier: number }[]
  width?: number  // default 80
  height?: number  // default 24
}
```

Rendering rules:

- ≤1 data point: render nothing (no sparkline shown on card).
- 2–3 points: vertical bars at fixed positions, height proportional to (1 − brier) so "good" trends upward.
- ≥4 points: polyline through points, y-mapped so lower Brier is higher on the chart.

Y-axis range: 0 to max(0.5, max(brier in data)) so most charts share a visual scale. Color: muted slate — informational, not alarming.

**Acceptance:** sparkline renders for skills with 2+ versions; absent for skills with 0–1 versions.

### D5 — `/agent` explainer block

Insert above the cards on `/agent`. Fixed text (lock here, no Cursor wording variance):

```
Envision is an experimental, self-evolving agent system that monitors 
global wildfires and tropical cyclones. Detection skills consume signals 
from public data sources and emit probabilistic forecasts; an evaluator 
scores forecasts against ground truth events; a curator periodically 
proposes refinements to the skill library, gated by operator review. 
The system is research, not a calibrated alerting product.
```

(That's 4 sentences; v2_plan said 3, but the role separation needs the extra. Keep at 4.)

Styling: prose, max-width-2xl, slate-700 text, no headers.

**Acceptance:** block renders at top of `/agent`, above any other content, below the status header.

### D6 — Tooltip definitions

Lock these strings in `viewer/lib/tooltips.ts`:

```ts
export const TOOLTIPS = {
  brier: "Brier score: a calibration metric for probabilistic forecasts. Lower is better. A perfect skill scores 0; random guessing scores around 0.25.",
  hit: "Hit: forecast issued and a matching ground-truth event occurred within the validity window.",
  falsePositive: "False positive: forecast issued but no matching ground-truth event occurred within the validity window.",
}
```

Used via `title={TOOLTIPS.brier}` on hover targets in skill cards. Reuse in `/about` page if any explanation lands there.

**Acceptance:** hovering Brier/Hit/False positive on any card shows the corresponding definition.

## Out of scope

- Authoritative kill-switch UI (`system_config` table) — v2.5+.
- Activity feed strip (per v2_plan §8 Day 8 — defer).
- Per-card "drill into proposals for this skill" links — could surface but not load-bearing for v2.
- Per-skill trace inspection on cards — Day 8.
- Mobile-first redesign — viewer is desktop-only per envision_plan §9.
- Curator no-agent mode visualization — N/A (already on Modal).
- Internationalization.

## Notes / gotchas

- **Server components and DB queries.** Use `viewer/lib/db.ts` (already wraps `@neondatabase/serverless`). No client-side fetches; all queries run during ISR build/revalidation.
- **Numbers stale by up to 60s.** That's the ISR window. Acceptable for ops display; no need for streaming or websockets.
- **shadcn Card primitive.** Use it if available in the project; otherwise plain Tailwind. Don't pull in additional dependencies for the card layout.
- **Sparkline y-axis scaling.** Watch for a single bad version with Brier 0.5+ stretching the entire chart. Cap y-axis at 0.5 unless data exceeds; clip data above 0.5 with a visual marker (small "↑" at the cap).
- **Mobile responsiveness.** envision_plan §10 cut list and §15 explicitly defer mobile, but a 1-column grid on narrow viewports is free with Tailwind responsive utilities. Don't over-style for mobile, but don't break it.
- **No client-side state.** Cards are pure rendered output. If you find yourself reaching for `useState`, you're solving the wrong problem.
- **TypeScript types should reflect DB nullability.** `brierMean` is `number | null` for skills with no evals; `currentVersion` is `number | null` for skills with no forecasts. Card renders "—" for null.
- **Status header timing display.** Be honest about ISR staleness — "4 min ago" might actually be "4–5 min ago" because of the cache window. Don't pad the time to make it look fresher.

## Done definition

- D1–D6 acceptance criteria met.
- `/agent` renders cards in place of the prior table; visually scannable in <5 seconds.
- Status header appears on all 4 routes (`/`, `/forecast/[id]`, `/agent`, `/about`).
- Every active skill has a `skill-metadata.ts` entry.
- Build clean: `cd viewer && npm run build` passes without TS errors.
- Deployed to Vercel.
- `PROGRESS.md` "v2 Day 7 complete" section: ops surface live, frontend now legible without DB access.
