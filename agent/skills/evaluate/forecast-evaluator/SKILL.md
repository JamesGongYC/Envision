---
name: forecast-evaluator
description: Matches expired forecasts against GDACS ground-truth events and writes per-forecast Brier contributions to the evaluations table. Runs nightly.
---

# forecast-evaluator

Evaluation skill — Day 4. The feedback signal the Curator will eventually consume.

## What it does
1. Selects `forecasts` whose `valid_until + 12h` has passed AND that have
   no row in `evaluations` yet.
2. For each, searches `ground_truth` for events that:
   - share the disaster class (with aliases: `WF`/`wildfires`/`fire` map to `wildfire`; `TC`/`tropical_cyclone`/`cyclone`/`hurricane` map to `typhoon`),
   - occurred within `(valid_from - 6h, valid_until + 12h)`,
   - have geometry intersecting the forecast geometry.
3. Writes one row per forecast to `evaluations`:
   - `outcome = 'hit'` if a match was found, else `'false_positive'`.
   - `brier_contribution = (probability - outcome_value)²` where
     `outcome_value` is 1.0 for hit, 0.0 for false positive.
4. Prints a per-skill summary (hits, false positives, mean Brier).

## Inputs (read)
- `forecasts` (unevaluated, with expired validity windows)
- `ground_truth`

## Outputs (write)
- `evaluations` rows

## Cadence
24h. Nightly run. Once cron is registered, fires once per day.

## How to run
```sh
python scripts/evaluate_forecasts.py
```

## Dependencies
- `psycopg` (already installed)

## What 'miss' would mean (and why we don't write it)
Schema allows `outcome = 'miss'` for events that occurred without any
forecast covering them. We don't compute this in v1 because:
1. Our detectors only fire when they see signals, so a "miss" by any one
   skill isn't tied to a specific forecast row — it's a gap.
2. Gap analysis is more naturally a v2 dashboard query
   (`ground_truth` events with zero overlapping forecasts).

## Idempotency
The query joins against `evaluations` to skip forecasts that already have
a row. Safe to re-run any time; will only process newly-expired forecasts
on each tick.

## Tuning knobs (constants at top of script)
- `PRE_BUFFER_HOURS` (6h): how early before `valid_from` an event still counts as a hit
- `POST_BUFFER_HOURS` (12h): GDACS publication lag tolerance
- `EVAL_DELAY_HOURS` (12h): how long after `valid_until` we wait to evaluate
- `BATCH_SIZE` (1000): max forecasts processed per run
