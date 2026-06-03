-- v3 Day 2: candidate lineage rows (version NULL until operator promotion)
-- Requires 006_evolution.sql applied.

BEGIN;

ALTER TABLE skill_lineage ALTER COLUMN version DROP NOT NULL;

ALTER TABLE skill_lineage DROP CONSTRAINT IF EXISTS skill_lineage_skill_id_version_key;

CREATE UNIQUE INDEX skill_lineage_promoted_version
  ON skill_lineage (skill_id, version)
  WHERE version IS NOT NULL;

ALTER TABLE skill_lineage
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'candidate'
    CHECK (status IN ('candidate', 'shadow', 'promoted', 'archived'));

UPDATE skill_lineage SET status = 'promoted' WHERE version IS NOT NULL;

COMMIT;
