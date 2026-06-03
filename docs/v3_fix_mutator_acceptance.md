# Envision v3 — Fix Ticket: Mutator Acceptance Path

**Goal:** the mutator reliably produces an *accepted* candidate on the happy path, and the happy path is covered by a deterministic test rather than a live LLM call that's allowed to skip. The validator is correct and stays untouched — the fixes are upstream of it: what the model is shown, how it's asked, and retrying when it misses.

**Symptom:** `test_mutate_wildfire_accepted` *skipped* (not passed) because the Sonnet candidate contained `emit_forecasts()`, correctly rejected by no-persistence (check #4). A skip here hides a zero end-to-end success rate behind a green run.

**Canonical context:** `docs/v3_day2_ticket.md`, `agent/evolution/mutator.py`, `agent/evolution/test_mutator.py`, `agent/modal_skills/<id>/run.py` + `app.py`, `agent/modal_skills/curator/scripts/run_curator.py` (validator).

---

## 1. Self-diagnosing pre-send guard

The candidate included `emit_forecasts()`. Either the model was *shown* it (input-assembly bug) or it *added* it (prompt bug). Stop guessing per-run: assert the parent surface is clean before the LLM is ever called.

- Run the validator's **no-persistence check (#4) against `parent_surface`** as a setup assertion. If the parent surface contains `emit_forecasts`, any DB write, or imports the writer, raise immediately:
  `"parent_surface includes persistence — fix input assembly (§2), not the prompt"`.
- This makes the input case fail loud and instantly, forever. If this assertion passes and the model *still* emits persistence, it's unambiguously the prompt (§3).

## 2. Feed only the mutation surface

Per Day-1 §3, `run.py` is the pure surface (`run(now, db) -> list[Forecast]` + skill-local helpers/constants) and `app.py` holds the entrypoint `emit_forecasts(run(now, db), db)`. The model must see and rewrite **only the surface**.

- `parent_surface` = contents of `run.py` (the pure function + its helpers + its imports). **Never** `app.py`, never a concatenation of both.
- If any `run.py` still bundles persistence (left over from the refactor), extract just `run()` and its skill-local helpers/constants into the surface; the entrypoint stays in `app.py`. The pre-send guard (§1) will flag any file that still bundles it.
- `skill_lineage.source_code` stores the **surface only**. The immutable scaffolding (the `app.py` entrypoint that calls `emit_forecasts`) is system-owned and recomposed with the surface at sandbox/deploy time — the model never authors it.

## 3. Positive return contract in the prompt

Negative constraints ("do NOT call `emit_forecasts`") hold weakly — a detection skill "obviously" needs to save its output, so the model adds it. Lead with the positive contract:

> Your function computes and returns `list[Forecast]`. It ends with `return forecasts`. Persistence is handled entirely by the caller — your code never imports or calls the writer and never executes `INSERT`/`UPDATE`/`DELETE`. Any database write will be rejected.

Keep the ban, but as the stated consequence after the contract, not the lead.

## 4. Bounded retry-with-feedback

LLM mutation always has a nonzero reject rate; one-shot-or-skip is too brittle for a daily loop.

```python
MAX_ATTEMPTS = 3
feedback = None
attempts = []
for i in range(MAX_ATTEMPTS):
    candidate = call_sonnet(parent_surface, trajectory, traces, inventory, feedback=feedback)
    result = validate(candidate)
    attempts.append({"n": i + 1, "rejection_reasons": result.rejection_reasons, "cost": ...})
    if result.accepted:
        break
    feedback = result.rejection_reasons   # fed back verbatim into the next prompt
```

- On rejection, re-prompt with the specific `rejection_reasons` ("Your previous attempt was rejected for: …. Return a corrected version. Remember: <return contract>.").
- Record `attempts` (count, reasons, cost) into `curator_trace`.
- ≤3 Sonnet calls per skill per pass — still well under the $5/pass cap.
- After `MAX_ATTEMPTS` without acceptance, return `MutationResult(accepted=False, attempts=…)`. Write no rows.

## 5. Test hygiene — stub the LLM for the happy path

The only happy-path coverage must not depend on a live network call.

- `test_mutate_accepts_fixture_candidate` — stub `call_sonnet` to return a hand-written valid mutant (e.g. wildfire DBSCAN `eps` 10→11km, surface only, no persistence). Assert: accepted; linked `skill_edit_proposals` (pending) + `skill_lineage` (candidate, version NULL) rows written; **no** `forecasts`/`signals`/`evaluations` writes.
- `test_mutate_retries_then_accepts` — stub returns a persistence-laden candidate on attempt 1, a valid one on attempt 2. Assert it retries with feedback, accepts on attempt 2, and `curator_trace.attempts` length is 2.
- `test_mutate_gives_up_after_max_attempts` — stub always returns a rejectable candidate. Assert `accepted=False` after `MAX_ATTEMPTS`, no rows written.
- `test_parent_surface_rejects_bundled_persistence` — pass a parent surface containing `emit_forecasts`; assert the §1 setup guard raises.
- Keep `test_mutate_wildfire_live` (real Sonnet) as a **separate** smoke test, allowed to skip with a WARN that a reject signals a low acceptance rate to investigate — never the sole happy-path proof.

## Acceptance checklist

- [ ] §1 guard runs the no-persistence check on `parent_surface` and raises on a bundled-persistence input.
- [ ] `parent_surface` is `run.py` only; `skill_lineage.source_code` is the surface only; scaffolding recomposed, not authored by the model.
- [ ] Prompt leads with the positive `return forecasts` contract.
- [ ] Bounded retry-with-feedback (≤3) implemented; attempts + cost recorded in `curator_trace`.
- [ ] Deterministic stubbed happy-path, retry, and give-up tests pass without network.
- [ ] Live Sonnet test is separate and skippable; not the happy-path proof.
- [ ] Validator unchanged — no check was loosened to make a test green.

## Gotchas

- **Do not weaken the no-persistence gate.** Same anti-pattern as chasing Brier under 0.25 — the gate is right; the input to it was wrong.
- **Recompose discipline:** because the surface excludes the entrypoint, the sandbox smoke-run (Day-2 §4.7) must wrap the surface with the scaffolding before executing, or `run()` exists but nothing calls `emit_forecasts` — which is fine for backtest (it scores the returned list) but means the sandbox must call `run()` directly, not the composed app entrypoint.
- **Feedback can loop:** if all 3 attempts fail with the *same* reason, that's a signal the prompt or surface is wrong, not bad luck — surface it in `curator_trace`, don't silently give up.
- Run from `~/Downloads/envision/`.
