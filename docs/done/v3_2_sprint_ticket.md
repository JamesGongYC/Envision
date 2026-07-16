# Cursor Sprint Ticket — v3.2: Generator + LLM-API Status Layer

**Goal:** turn on the second LLM invention point (the **generator**) and ship a single observability/health layer over every Anthropic call. Execute the work items in order — the status layer (A–C) gates the generator (D–F).

This ticket is self-contained. The decisions below are **locked** — do not re-litigate them in implementation.

---

## Locked decisions

| ID | Decision |
|----|----------|
| A1 | De-novo promotion bar is **absolute base-rate Brier**, no incumbent comparison: promote-eligible when `shadow_brier < base_rate_brier − noise_floor` at `N ≥ 20`. |
| A2 | Generator trigger is **operator-seeded, condition-gated, one disaster class per run** — never on the daily curator tick. |
| A3 | **No per-parent child cap.** Load control is held entirely by A2's gated trigger. |
| B1 | **Single-provider** observability + same-provider model-tier fallback. No cross-provider failover (v4). |
| B2 | **One LLM client wrapper** for all four call sites (mutator, curator, generator, narrator). |
| B3 | Health gate = **pre-flight cold-start probe + in-run rolling-window 529 gate**, with a minimum-sample floor. No-op the cycle on degradation. Independent of `ENVISION_CURATOR_ENABLED`. |
| B4 | **`llm_call_log`** telemetry table (migration 011), one row per HTTP attempt, capturing `request-id`. |

---

## Guardrails (do not drift)

- **Exactly two LLM invention points** — mutator and generator. Everything else (AST, sandbox, backtest, shadow scoring, selector, evaluator, wrapper, health gate) is deterministic hardcoded infrastructure, deliberately outside the mutation surface.
- **Only `run.py`** is fed to the model. Generator output is `run.py` + `SKILL.md`; `app.py`/entrypoint is scaffolded deterministically so `emit_forecasts` cannot be copied in.
- **Production promotion stays human-gated** via `review_proposals.py`. Generated skills enter through shadow → manual review like every mutant. No auto-promotion.
- **Shadow Brier stays the trusted fitness signal**; backtest remains a pathology filter only.
- The **health gate must not depend on the backtest signal**, and wrapper retry/abort logic is infrastructure — never a fitness input.
- Disclaimer banner + per-source attribution on every viewer page.

---

## Work items (ordered)

### A. LLM client wrapper  *(foundation — do first)*
Consolidate mutator, curator, generator, and narrator onto one shared wrapper module.
- Typed handling: catch the SDK's `APIStatusError`, branch on `status_code`; never string-match.
- Retry policy: **429** honor the `retry-after` header; **529 / 5xx** bounded exponential backoff + jitter; **4xx** invalid requests are **not** retried.
- Emits one `llm_call_log` row per HTTP attempt (see B), grouped by a `call_group_id`, carrying `request_id`, `status_code`, `error_type`, latency, and token counts.
- Same-provider model-tier fallback is allowed (B1); cross-provider is out of scope.
- **Gotcha:** Modal ships `app.py` but not sibling modules — register the wrapper with `add_local_python_source` everywhere skill/LLM code runs (curator, shadow-runner, evolution detection apps).

**Acceptance:** all four call sites import the wrapper; no direct SDK calls remain (grep clean); unit test asserts 4xx is not retried and `retry-after` is honored on 429. Tests must not write to the prod DB (`.cursor/rules/test-db-isolation.mdc`).

### B. Migration 011 + telemetry wiring
Apply `011_llm_call_log.sql` (provided). Wire the wrapper to write one row per attempt.
**Acceptance:** migration applies as a single transaction and passes its verification block; a live mutator pass produces rows; `request_id` is populated on responses.

### C. Health gate  *(rolling window)*
Two parts, because at curator/generator entry the rolling window is usually empty (calls are daily/bursty):
- **Pre-flight (cold start):** one cheap probe call (`call_site='probe'`) at curator + generator entry. On a capacity error, no-op the cycle and log.
- **In-run (sustained degradation):** rolling-window 529 rate over `llm_call_log` (default **10-minute** window, configurable) drives a graceful mid-cycle abort. A **minimum-sample floor** (`min_samples`) prevents a lone 529 in a quiet window from tripping the gate. Use the canonical query in the migration's footer comment. Gate releases automatically as clean calls refill the window.
- Independent of `ENVISION_CURATOR_ENABLED` (that's operator intent; this is provider availability). Narrator keeps its existing template fallback.

**Acceptance:** a simulated sustained 529 storm aborts the cycle cleanly (no shadow rows, no crash); a single isolated 529 does **not** trip the gate; toggling `ENVISION_CURATOR_ENABLED` is orthogonal to the gate.

### D. Generator module
Writes a de-novo `run.py` + `SKILL.md` from a fresh `signal_catalog` + an operator seed prompt. Scaffold `app.py` deterministically.
- **Generation context constraints:** hand the model the allowed-import set (the `skill_exec_image` deps), the `Forecast` contract, and the **0.85 probability cap**; explicitly **forbid any module-level `Path(__file__)` bootstrap** (exec-from-string strips `__file__`); require a unique `skill_id` validated against `skill_lineage`.
- `REFRESH MATERIALIZED VIEW signal_catalog` **before** the pass (matview gotcha).
- Flows through the existing path: AST + import + sandbox validation → light viability gate → `forecasts_shadow`.

**Acceptance:** a generated candidate passes validation and emits to `forecasts_shadow`; its lineage row has `generation_method='generated'`, `parent_skill_id=NULL`.

### E. Selector — absolute base-rate bar
For `generation_method='generated'`, replace the parent-comparison with the A1 rule: compute `base_rate_brier` from `ground_truth` over the candidate's eval window (constant forecaster at the class event frequency); promote-eligible when `shadow_brier < base_rate_brier − noise_floor` at `N ≥ 20`.
**Acceptance:** a generated candidate below base-rate is flagged promote-eligible; one above is not; the **mutant path is unchanged**.

### F. Curator orchestration — gated generation trigger
Add the A2 trigger: operator-seeded, condition-gated (e.g. a signal type with no covering detection skill), exactly one disaster class per run. Not on the daily worst-K tick.
**Acceptance:** generation fires only when seeded **and** the condition is met, and emits exactly one disaster class.

### G. Viewer — LLM-dependency indicator
Add an indicator on `/agent` read from `llm_call_log` (folds in the deferred per-source-staleness idea). Preserve disclaimer banner + attribution.
**Acceptance:** indicator reflects recent API health; renders with the dark/Palantir aesthetic; functional color reserved for data.

### H. Docs + lineage column check
- **Verify first:** confirm `skill_lineage` already carries `generation_method` and `parent_skill_id`. If absent, write **migration 012** to add them (single transaction + verification) before D/E land.
- Renumber the roadmap (generator → v3.2); update `PROGRESS.md` open-state and `Future_plans.md`. Record the A1 redundancy consequence and the A2↔A3 coupling in the docs.

---

## Definition of done

1. All four call sites route through the wrapper; `011_llm_call_log.sql` applied and logging live.
2. Health gate aborts a sustained-529 cycle gracefully and ignores isolated blips, independent of the kill switch.
3. A seeded generation run produces a `generated` candidate that reaches `forecasts_shadow` and is scored against the base-rate bar.
4. `/agent` shows LLM-dependency health; docs renumbered and consequences recorded.
5. Promotion remains human-gated; no evolution component writes a production skill file or runs `modal deploy`.
