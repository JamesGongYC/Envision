-- ============================================================================
-- Migration 013 — llm_call_log.call_site: forecaster + critic
-- ----------------------------------------------------------------------------
-- Extends the call_site CHECK so v4 agent paths can log through llm_client.
-- 'critic' included now so T6 does not need another CHECK migration.
--
-- Single transaction. Re-run safe (drop + add by constraint name).
-- ============================================================================

BEGIN;

ALTER TABLE llm_call_log
    DROP CONSTRAINT IF EXISTS llm_call_log_call_site_check;

ALTER TABLE llm_call_log
    ADD CONSTRAINT llm_call_log_call_site_check
    CHECK (call_site IN (
        'mutator', 'curator', 'generator', 'narrator', 'probe',
        'forecaster', 'critic'
    ));

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'llm_call_log_call_site_check'
    ) THEN
        RAISE EXCEPTION 'migration 013: llm_call_log_call_site_check missing';
    END IF;
END $$;

COMMIT;
