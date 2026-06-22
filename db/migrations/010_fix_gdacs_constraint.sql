-- ============================================================================
-- 010_fix_gdacs_constraint.sql
-- ----------------------------------------------------------------------------
-- Fixes the GDACS ingestion crash:
--   psycopg.errors.InvalidColumnReference: there is no unique or exclusion
--   constraint matching the ON CONFLICT specification
--
-- Root cause: the ingest code uses INSERT ... ON CONFLICT (source, event_key)
-- DO UPDATE, but migration 009's unique constraint never landed on this DB.
-- Result: every ingest cycle threw, ground_truth froze (stale since 2026-06-07),
-- and pre-existing advisory-update duplicates (JANGMI-26 x22, ONE-E-26 x21)
-- were never collapsed.
--
-- Verified preconditions (from information_schema / pg_constraint at migration time):
--   - ground_truth.event_key EXISTS and is fully populated (141 rows, 0 NULL).
--     => plain UNIQUE (source, event_key) is sufficient; no NULLS NOT DISTINCT,
--        no COALESCE fallback needed.
--   - No (source, event_key) unique constraint exists yet.
--   - Legacy non-unique idx_ground_truth_dedup on (source, dedup_key) still present
--     (the v1 md5-payload mechanism that allowed the duplication). Retired here.
--
-- Order is load-bearing: collapse duplicates and repoint FKs BEFORE creating the
-- unique index, otherwise the index creation fails on the existing duplicates.
--
-- FK dependents on ground_truth.id (repointed to survivors below):
--   - evaluations.matched_ground_truth_id
--   - shadow_evaluations.matched_ground_truth_id
-- If other tables also FK to ground_truth.id, add them to step 2 before deploying.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- Step 0 -- Safety: confirm event_key is populated. Abort loudly if not.
-- (A NULL event_key here would mean the survivor-selection groups NULLs wrongly.)
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    n_null integer;
BEGIN
    SELECT count(*) INTO n_null
    FROM ground_truth
    WHERE source = 'gdacs' AND event_key IS NULL;

    IF n_null > 0 THEN
        RAISE EXCEPTION
          'Aborting: % gdacs rows have NULL event_key. '
          'Backfill event_key from payload->>''eventid'' before running this migration.',
          n_null;
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- Step 1 -- Identify survivors: the most-recent row per (source, event_key).
-- Materialized as a temp table so both the FK repoint and the delete agree.
-- ----------------------------------------------------------------------------
CREATE TEMP TABLE gt_survivors ON COMMIT DROP AS
SELECT DISTINCT ON (source, event_key)
       id AS survivor_id,
       source,
       event_key
FROM ground_truth
ORDER BY source, event_key, occurred_at DESC, id;

-- Map every row -> its survivor (survivors map to themselves).
CREATE TEMP TABLE gt_remap ON COMMIT DROP AS
SELECT g.id            AS old_id,
       s.survivor_id   AS new_id
FROM ground_truth g
JOIN gt_survivors s
  ON s.source = g.source
 AND s.event_key = g.event_key;

-- ----------------------------------------------------------------------------
-- Step 2 -- Repoint FK dependents from losers to survivors BEFORE deleting.
-- ----------------------------------------------------------------------------
UPDATE evaluations e
SET matched_ground_truth_id = r.new_id
FROM gt_remap r
WHERE e.matched_ground_truth_id = r.old_id
  AND r.old_id <> r.new_id;

UPDATE shadow_evaluations se
SET matched_ground_truth_id = r.new_id
FROM gt_remap r
WHERE se.matched_ground_truth_id = r.old_id
  AND r.old_id <> r.new_id;

-- ----------------------------------------------------------------------------
-- Step 3 -- Delete the duplicate (non-survivor) ground_truth rows.
-- ----------------------------------------------------------------------------
DELETE FROM ground_truth g
USING gt_remap r
WHERE g.id = r.old_id
  AND r.old_id <> r.new_id;

-- ----------------------------------------------------------------------------
-- Step 4 -- Retire the legacy md5-payload dedup index (the duplication source).
-- ----------------------------------------------------------------------------
DROP INDEX IF EXISTS idx_ground_truth_dedup;

-- ----------------------------------------------------------------------------
-- Step 5 -- Create the unique constraint the upsert's ON CONFLICT targets.
-- A UNIQUE CONSTRAINT (not just a unique index) so ON CONFLICT (source, event_key)
-- resolves cleanly. Safe now that duplicates are collapsed.
-- ----------------------------------------------------------------------------
ALTER TABLE ground_truth
    ADD CONSTRAINT uq_ground_truth_source_event_key UNIQUE (source, event_key);

-- ----------------------------------------------------------------------------
-- Step 6 -- Verify: no remaining duplicates by the new key.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    n_dupe integer;
BEGIN
    SELECT count(*) INTO n_dupe FROM (
        SELECT source, event_key
        FROM ground_truth
        GROUP BY source, event_key
        HAVING count(*) > 1
    ) d;

    IF n_dupe > 0 THEN
        RAISE EXCEPTION 'Post-collapse check failed: % duplicate (source, event_key) groups remain.', n_dupe;
    END IF;
END $$;

COMMIT;

-- ============================================================================
-- Post-migration manual steps (NOT part of this transaction):
--   1. Redeploy / restart the gdacs-ground-truth Modal app. Its next cycle should
--      now upsert cleanly instead of throwing InvalidColumnReference.
--   2. Confirm fresh rows land:  SELECT max(occurred_at) FROM ground_truth WHERE source='gdacs';
--      -- should advance past 2026-06-07 within one cycle (6h cadence).
--   3. Re-run the evolve diagnostic Query 5 (gotcha checks): gdacs_dedup and
--      gt_freshness should both flip to OK once a cycle lands.
--   4. The shadow Brier comparison (improvement-over-baseline) is now scored
--      against a clean, de-duplicated, fresh GT pool -- re-run the promote check
--      for wildfire_rapid_growth (4baa8dda) before finalizing its promotion.
-- ============================================================================
