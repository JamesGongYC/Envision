-- ============================================================================
-- Migration 012 — agent telemetry + forecast provenance
-- ----------------------------------------------------------------------------
-- Schema foundation for v4 agentic layer (T1 / W1).
--
-- Adds:
--   * agent_run  — one row per forecaster/critic invocation
--   * agent_step — ordered thought/action/observation/gated/terminal steps
--   * forecasts.producer + forecasts.agent_run_id — provenance for the two
--     production writers (rule vs agent). No cross-producer dedup; both are
--     scored. Existing rows default to producer='rule', agent_run_id NULL
--     (no backfill).
--
-- The existing forecasts.probability <= 0.85 CHECK is untouched and governs
-- both producers.
--
-- geo_focus on agent_step stores an envelope polygon:
--   write: ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(:bbox), 4326))
--   read:  ST_AsGeoJSON(geo_focus)
--
-- Retention: agent_run / agent_step pruning belongs in housekeeping-retention
-- (T-cleanup follow-up). ON DELETE CASCADE on agent_step so a run purge
-- drops its steps.
--
-- Single transaction. Verification asserts at the end fail the txn loudly.
-- Re-run safe via IF NOT EXISTS guards.
-- ============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid(); no-op if 001 ran
CREATE EXTENSION IF NOT EXISTS postgis;   -- geometry; no-op if 001 ran

CREATE TABLE IF NOT EXISTS agent_run (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_type        text NOT NULL CHECK (agent_type IN ('forecaster', 'critic')),
    trigger           text NOT NULL CHECK (trigger IN ('button', 'scheduled', 'operator')),
    status            text NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'gated')),
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz NULL,
    step_count        int NOT NULL DEFAULT 0,
    outcome           jsonb NULL,          -- emitted forecast ids | created proposal ids
    health_gate_state text NULL,
    error             text NULL
);

CREATE TABLE IF NOT EXISTS agent_step (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id  uuid NOT NULL REFERENCES agent_run(id) ON DELETE CASCADE,
    seq           int  NOT NULL,
    step_type     text NOT NULL CHECK (step_type IN ('thought', 'action', 'observation', 'gated', 'terminal')),
    tool          text NULL,
    tool_input    jsonb NULL,
    tool_output   jsonb NULL,             -- size-capped by the writer (16KB trace discipline)
    -- Envelope polygon; write via ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(:bbox),4326))
    geo_focus     geometry(Geometry, 4326) NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_step_run_seq
    ON agent_step (agent_run_id, seq);

ALTER TABLE forecasts
    ADD COLUMN IF NOT EXISTS producer text NOT NULL DEFAULT 'rule'
        CHECK (producer IN ('rule', 'agent')),
    ADD COLUMN IF NOT EXISTS agent_run_id uuid NULL REFERENCES agent_run(id);

CREATE INDEX IF NOT EXISTS idx_forecasts_producer
    ON forecasts (producer);

-- ---------------------------------------------------------------------------
-- Verification — fail the transaction if the migration did not fully apply.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'agent_run'
    ) THEN
        RAISE EXCEPTION 'migration 012: agent_run table was not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'agent_step'
    ) THEN
        RAISE EXCEPTION 'migration 012: agent_step table was not created';
    END IF;

    IF (SELECT count(*)
        FROM information_schema.columns
        WHERE table_name = 'agent_run'
          AND column_name IN
            ('id', 'agent_type', 'trigger', 'status', 'started_at',
             'finished_at', 'step_count', 'outcome', 'health_gate_state', 'error')) < 10 THEN
        RAISE EXCEPTION 'migration 012: expected columns missing on agent_run';
    END IF;

    IF (SELECT count(*)
        FROM information_schema.columns
        WHERE table_name = 'agent_step'
          AND column_name IN
            ('id', 'agent_run_id', 'seq', 'step_type', 'tool',
             'tool_input', 'tool_output', 'geo_focus', 'created_at')) < 9 THEN
        RAISE EXCEPTION 'migration 012: expected columns missing on agent_step';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forecasts' AND column_name = 'producer'
    ) THEN
        RAISE EXCEPTION 'migration 012: forecasts.producer was not added';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forecasts' AND column_name = 'agent_run_id'
    ) THEN
        RAISE EXCEPTION 'migration 012: forecasts.agent_run_id was not added';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'agent_step' AND indexname = 'idx_agent_step_run_seq'
    ) THEN
        RAISE EXCEPTION 'migration 012: idx_agent_step_run_seq missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'forecasts' AND indexname = 'idx_forecasts_producer'
    ) THEN
        RAISE EXCEPTION 'migration 012: idx_forecasts_producer missing';
    END IF;
END $$;

COMMIT;
