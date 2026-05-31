-- Envision — migration 002: dedup + retention hardening
-- Run this in the Neon SQL Editor BEFORE turning on the cron, so the every-30-min
-- ingestion can run repeatedly without bloating the database.
--
-- Approach: a generated md5(payload) key per row, plus a BEFORE INSERT trigger
-- that silently skips any row whose (source, dedup_key) already exists. The
-- existing ingestion skills need NO code changes — re-runs simply no-op on
-- records they've already stored.

-- ===== signals =============================================================
ALTER TABLE signals
  ADD COLUMN IF NOT EXISTS dedup_key TEXT
  GENERATED ALWAYS AS (md5(payload::text)) STORED;

-- collapse any duplicates already inserted during Day-2 testing
DELETE FROM signals a USING signals b
WHERE a.source = b.source AND a.dedup_key = b.dedup_key AND a.ctid > b.ctid;

CREATE INDEX IF NOT EXISTS idx_signals_dedup ON signals (source, dedup_key);

CREATE OR REPLACE FUNCTION skip_duplicate_signal() RETURNS trigger AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM signals
    WHERE source = NEW.source AND dedup_key = md5(NEW.payload::text)
  ) THEN
    RETURN NULL;  -- already have this record; skip silently
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_dedup_signals ON signals;
CREATE TRIGGER trg_dedup_signals
  BEFORE INSERT ON signals
  FOR EACH ROW EXECUTE FUNCTION skip_duplicate_signal();

-- ===== ground_truth ========================================================
ALTER TABLE ground_truth
  ADD COLUMN IF NOT EXISTS dedup_key TEXT
  GENERATED ALWAYS AS (md5(payload::text)) STORED;

DELETE FROM ground_truth a USING ground_truth b
WHERE a.source = b.source AND a.dedup_key = b.dedup_key AND a.ctid > b.ctid;

CREATE INDEX IF NOT EXISTS idx_ground_truth_dedup ON ground_truth (source, dedup_key);

CREATE OR REPLACE FUNCTION skip_duplicate_ground_truth() RETURNS trigger AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM ground_truth
    WHERE source = NEW.source AND dedup_key = md5(NEW.payload::text)
  ) THEN
    RETURN NULL;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_dedup_ground_truth ON ground_truth;
CREATE TRIGGER trg_dedup_ground_truth
  BEFORE INSERT ON ground_truth
  FOR EACH ROW EXECUTE FUNCTION skip_duplicate_ground_truth();

-- ===== retention ===========================================================
-- Retention is automated by the housekeeping-retention skill (v2 Day 1):
--   DELETE FROM signals   WHERE ingested_at < now() - interval '30 days';
--   DELETE FROM forecasts WHERE issued_at    < now() - interval '60 days';
-- ground_truth, evaluations, and skill_edit_proposals are kept indefinitely.
