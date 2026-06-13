-- Envision — migration 009: GDACS natural-key dedup on ground_truth.eventid
-- Replaces md5-only dedup for GDACS advisories that change payload on every update.

-- ===== event_key column ====================================================
ALTER TABLE ground_truth
  ADD COLUMN IF NOT EXISTS event_key TEXT
  GENERATED ALWAYS AS (NULLIF(payload->>'eventid', '')) STORED;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ground_truth_source_event_key
  ON ground_truth (source, event_key)
  WHERE event_key IS NOT NULL;

-- ===== collapse duplicate GDACS rows (keep latest todate, earliest occurred_at)
CREATE TEMP TABLE _gt_collapse_map AS
SELECT
  gt.id AS old_id,
  survivor.id AS keep_id
FROM ground_truth gt
JOIN LATERAL (
  SELECT g2.id
  FROM ground_truth g2
  WHERE g2.source = gt.source
    AND g2.event_key IS NOT NULL
    AND g2.event_key = gt.event_key
  ORDER BY (g2.payload->>'todate') DESC NULLS LAST, g2.occurred_at ASC
  LIMIT 1
) survivor ON TRUE
WHERE gt.event_key IS NOT NULL
  AND gt.id <> survivor.id;

UPDATE evaluations e
SET matched_ground_truth_id = m.keep_id
FROM _gt_collapse_map m
WHERE e.matched_ground_truth_id = m.old_id;

DELETE FROM ground_truth gt
USING _gt_collapse_map m
WHERE gt.id = m.old_id;

DROP TABLE _gt_collapse_map;

-- GDACS rows without eventid still use md5 dedup_key trigger from 002_hardening.sql
