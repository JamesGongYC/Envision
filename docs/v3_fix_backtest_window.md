# Envision v3 — Fix Ticket: Backtest Trailing-Window Bug

**Goal:** harness reports backtest Brier within ±0.02 of live for **all 4** detection skills. Fix the broken trailing-time window in the parametrized signal queries, fix the alert temporal join, and upgrade the leakage guard to cover the *past* edge so this class of bug cannot pass silently again.

**Canonical context:** `docs/v3_day1_ticket.md`, `agent/evolution/backtest_harness.py`, `agent/evolution/test_backtest_sanity.py`, all 4 `agent/modal_skills/<detect>/run.py`, the archived pre-refactor skills in `agent/_archive/skills/`, `agent/lib/scoring.py`, `agent/lib/trace_builder.py`.

---

## Root cause (from the failing sanity run)

`wildfire_risk_elevated` processed ~12,000 hotspots / 480 clusters per tick mid-window versus ~80–250 / ~8 live. The skill consumed a **cumulative** set (`timestamp <= now`) instead of a **trailing window** (`now − 24h <= timestamp <= now`). Result: `backtest_brier=0.357` vs `live_brier=0.267`, delta 0.09 (4.5× the 0.02 gate).

The Day-1 persistence-extraction refactor most likely dropped or mis-anchored the *lower* time bound. The future-edge leakage guard passed because the bug is on the *past* edge — the window is too wide, not too far forward.

> The absolute Brier being above 0.25 is **not** the bug — that's a real over-confidence/calibration property of the skill (it emits 0.55–0.85, capped at 0.85, and verifies below the ~0.68 break-even). The bug is the backtest-vs-live **gap**. The fix target is *matching live*, not pushing Brier under 0.25.

---

## Scope

1. Fix the trailing-window bounds in all 4 detection skills.
2. Fix the NWS alert temporal join (active-as-of-`t`).
3. Upgrade the harness guard to enforce the past edge (full window), not just the future edge.
4. Hold deployment of the refactored skills until fixed — same bug = forecast spam in production. Re-verify parity.
5. Re-run and extend the sanity test to all 4 skills; ±0.02 gate.

---

## 1. Window bounds — both edges off `now`

Each detection skill has a temporal lookback. Both edges must key off the `now` parameter — never wall-clock, never unbounded.

Per-skill lookback (confirm each against the archived skill, do not trust this table blindly):

| Skill | Lookback | Note |
|---|---|---|
| `wildfire-risk-elevated` | 24h | FIRMS hotspots last 24h |
| `wildfire-rapid-growth` | **~48h** | compares consecutive 24h buckets day-over-day — **not** 24h |
| `typhoon-intensifying` | ~14h | 12h pressure-drop window + ±2h tolerance (per PROGRESS) |
| `typhoon-landfall-imminent` | ~6h | latest advisory per storm; 72h cone is *forward* extrapolation, not lookback |

- Query pattern: `WHERE timestamp > %(now)s - %(lookback)s AND timestamp <= %(now)s`.
- Grep every `run.py` query path for `NOW()`, `CURRENT_TIMESTAMP`, `datetime.utcnow()`, `datetime.now()` — none may appear in the signal-selection path. All time references resolve through the `now` parameter.
- **Diff each refactored query against `agent/_archive/skills/<id>`** to confirm the lower bound was the casualty and nothing else drifted in the refactor.

## 2. Alert temporal join — active as of `t`

`wildfire-risk-elevated` intersects hotspot clusters with active NWS fire-weather polygons. "Active" must mean *active as of `t`*, read from the alert validity in the `fire_warning` signal payload:

```
effective <= t AND (expires IS NULL OR expires >= t)
```

Currently it likely keys off currently-active or latest-ingested alerts — which is why the tail ticks (1,300 hotspots emitting 21–24) show a different emit/cluster ratio than the bulk. Apply the same as-of-`t` predicate to any other skill that joins alert/advisory state.

## 3. Harness guard — close the past edge

Generalize guard #2 from a future-cutoff into a full-window invariant. This is the safety net that should have caught the original bug.

- Add `SKILL_LOOKBACK` dict (same values as §1).
- Wrap the connection passed into `run()` with a proxy that, for any `SELECT` touching `signals`, inspects returned rows and asserts every `timestamp` falls in `[t − SKILL_LOOKBACK[skill_id], t]`. Abort loudly on the first violation with `skill_id`, `t`, and the offending timestamp.
- This is the **truth** check — it catches the bug regardless of how the SQL is written, where the existing future-only assertion did not.
- Optional legibility add (useful to the v3 mutator): have each skill record `window_start` / `window_end` in `trace.inputs`. The interceptor remains the enforcing guard; the trace is just disclosure.
- Keep the existing future-edge assertion; it is now a subset of this one.

## 4. Production safety — do not deploy yet

The refactored skills are **not yet in production** (Modal still runs the pre-refactor v2.5 skills). Do **not** `modal deploy` the refactored detection skills until this ticket passes. Deploying the cumulative-window version would, at wall-clock `now`, return every retained signal (30d, no window) and emit thousands of forecasts per tick — map spam and evaluator pollution.

After the fix: re-run the §3 production-emission parity diff at wall-clock `now` **and** confirm the new window guard passes over a historical replay. Both clean → safe to deploy.

## 5. Re-run + extend the sanity gate

- Extend `test_backtest_sanity.py` to run **all 4** detection skills over the trailing 7 days, each compared to its live trailing-7d Brier from `evaluations`.
- Pass condition unchanged: `|backtest − live| ≤ 0.02` for every skill. Print per-skill backtest / live / delta.
- A skill with too few live evals for a stable live Brier: **skip with a logged WARN**, don't fail — but record it as *unverified*. v3 must not proceed trusting an unverified skill's backtest.

---

## Acceptance checklist

- [ ] All 4 detection queries bound both edges to `now`; no wall-clock calls in the query path; per-skill lookback documented in the skill.
- [ ] Each refactored query diffed against its archived version; only intended changes present.
- [ ] NWS alert join filters to alerts active as of `t`.
- [ ] Harness enforces `[t − lookback, t]` on consumed `signals` rows via the connection proxy; any violation aborts the run.
- [ ] Sanity test runs all 4 skills; every verifiable skill within ±0.02; unverifiable skills logged, not silently passed.
- [ ] Refactored skills NOT deployed until parity diff + window guard are both clean.

## Gotchas

- **Don't chase Brier under 0.25.** The target is matching live (~0.267), not beating the no-skill baseline. A harness "fix" that drags Brier down is hiding the bug, not fixing it.
- **`wildfire-rapid-growth` is ~48h, not 24h.** It compares consecutive day buckets; a 24h lower bound silently truncates the day-over-day comparison and emits nothing. That's a *too-narrow* window — the §3 guard only flags *too-wide* windows, so it won't catch this. Verify the lookback against the archived logic explicitly.
- Typhoon skills run on 3h cadence; the guard's lookback is per-skill, never a global default.
- Run from `~/Downloads/envision/`.
