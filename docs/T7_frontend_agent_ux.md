# T7 — Frontend: nav placement + agent transcript redesign

**Goal:** Move the Agent nav button up beside Forecasts, and reshape the forecaster/critic visibility window into a natural-language-dominant chat transcript with collapsed tool-usage summaries that expand to full logs on click.
**Depends on:** T5 (viewer demo layer). **Blocks:** none.

House rules: viewer only (`viewer/`), no change to the SSE contract (T4), the agents (T2/T6), or the aggregator (T3). Preserve producer badges, the map spotlight, operator-Fire gating, and the disclaimer/attribution on every page. `git push origin master:main`.

---

## Part A — Nav placement

Reorder the top-nav panel buttons to: **Forecasts · Agent · How it works**, i.e. Agent sits between Forecasts and How it works (adjacent to Forecasts, immediately to its right). This elevates the demo out of its current position.

- **File (confirm path):** the primary nav/header component (e.g. `viewer/components/Nav.tsx` / wherever the panel buttons are declared).
- Change is ordering only — no route, label, or active-state logic changes.
- Keep active-route highlighting correct after the reorder.

---

## Part B — Agent transcript redesign

Replace the current step-card stream (`TracePanel` + `ToolUseCards`) with a single-column chat transcript — Claude/ChatGPT style — where the agent's **reasoning is the hero** and tool calls are subordinate, collapsed artifacts. Shared by both forecaster and critic demos.

### Files (confirm paths under `viewer/`)
- **New** `components/agent/AgentTranscript.tsx` — the transcript column; consumes the SSE event stream, renders messages + tool rows. Replaces `TracePanel.tsx` + `ToolUseCards.tsx` (delete or reduce those to thin wrappers).
- **New** `components/agent/ToolCallRow.tsx` — one collapsed disclosure row per tool call; expands to full logs.
- **New** `components/agent/summarizeTool.ts` — client-side one-line summary per tool (no backend change).
- Modify `app/agent/` ForecasterDemo + CriticDemo to render `AgentTranscript`.
- Reuse `lib/sse.ts`, the existing typing-animation, the map spotlight, and producer badges unchanged.

### Event → UI mapping (SSE types from T4 §5)
| `step_type` | Render |
|---|---|
| `thought` | **Primary.** Assistant-style message block, readable prose, typing-animated. This is the dominant visual content. |
| `action` + next `observation` | Fold the pair into **one collapsed `ToolCallRow`**: header = tool name + a one-line summary from `summarizeTool`; body (hidden until clicked) = full `tool_input` + `tool_output` JSON (already 16KB-capped). Muted, compact, monospace label. |
| `gated` | System notice block ("Run paused — provider degraded / capacity"). Non-error styling. |
| `terminal` | Closing **summary card**: forecaster → "Emitted N forecasts" (+ ids/links, badged `agent`); critic → "Proposed mutate/generate of X" (+ link to the review-queue entry). |
| `failed` | System error block. |

### `summarizeTool` (client-side, per tool)
One short line, no JSON:
- `inspect_signals` → region + per-source counts ("NW US · FIRMS 41, NWS 3").
- `list_skills` → "listed N skills".
- `run_skill` → skill id + candidate count ("wildfire-rapid-growth → 3 candidates").
- `emit` → "selected N of M candidates".
- `mutate_skill` / `generate_skill` → target skill / class.
- Fallback → tool name only. Full detail always available on expand.

> Optional follow-on (not this ticket): have the loop emit an explicit `summary` per step so the client stops deriving it. Client-side derivation ships now.

### "Looks intelligent" — concrete requirements
- Reasoning prose is the largest, highest-contrast element; tool rows are small and muted — clear hierarchy, reasoning : tool ≈ dominant : incidental.
- Collapsed by default; expanding a `ToolCallRow` reveals full input/output; independently collapsible; keyboard-accessible (button/`<details>` semantics, focus ring).
- Smooth streaming append; typing animation on **`thought` text only** (never on tool JSON). A subtle "thinking…" pulse between a thought and its next action.
- Auto-scroll to newest, but **pause auto-scroll when the user scrolls up** and show a "jump to latest" affordance.
- One transcript component for both agents. **Forecaster** keeps the map spotlight (layout: transcript + map side-by-side on wide viewports, stacked on narrow). **Critic** is transcript-only, no map.
- Identical rendering for **live** (`fire`) and **replay** streams — only the source differs.

### Guardrails
- No SSE schema changes; consume `thought/action/observation/gated/terminal/failed` and `geo_focus` as-is.
- Map spotlight still driven only by `geo_focus` (present on region-scoped steps, holds on null).
- Producer badges, operator-Fire gating (public = replay-only), disclaimer + attribution all preserved.

### Test plan
1. Nav renders `Forecasts · Agent · How it works`; active highlight correct on each route.
2. A forecaster run renders reasoning as dominant prose; each tool call is a collapsed row with a correct one-line summary; expanding shows full input/output.
3. Expanding/collapsing one tool row doesn't affect others; keyboard-operable.
4. `terminal` renders the summary card with emitted ids (forecaster) / proposal link (critic).
5. Auto-scroll follows newest; scrolling up pauses it; "jump to latest" resumes.
6. Forecaster shows transcript + map (spotlight follows `geo_focus`); critic shows transcript only.
7. Live and replay render identically; public surface has no Fire control.
8. Producer badges + disclaimer present.

### Acceptance
- [ ] Nav order updated, active states correct.
- [ ] Reasoning-dominant chat transcript replaces the step-card stream, shared by both demos.
- [ ] Tool calls collapsed with derived summaries; full logs on click; typing animation on prose only.
- [ ] Forecaster keeps the map spotlight; critic is transcript-only.
- [ ] Live + replay identical; badges, gating, disclaimer/attribution intact.

### Out of scope
SSE/loop changes, an explicit backend `summary` field, aggregator/critic behavior, any promotion-UX work.
