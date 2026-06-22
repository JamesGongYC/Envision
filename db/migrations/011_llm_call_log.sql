-- ============================================================================
-- Migration 011 — llm_call_log
-- ----------------------------------------------------------------------------
-- Establishes the telemetry table backing the v3.2 LLM-API status layer.
--
-- One row PER HTTP ATTEMPT (including each retry), grouped by call_group_id,
-- so the health gate can compute the rolling-window 529 rate directly from
-- this table without losing retry-level granularity.
--
-- Consumers:
--   * Health gate (curator/generator pre-flight probe + in-run abort):
--     rolling 529 rate over a time window, with a minimum-sample floor.
--   * /agent LLM-dependency indicator.
--   * Post-hoc correlation with status.claude.com via request_id.
--
-- Single transaction. Verification asserts at the end fail the txn loudly.
-- Retention of this table is handled by housekeeping-retention, not here.
-- ============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid(); no-op if 001 ran

CREATE TABLE llm_call_log (
    id                       uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Groups all attempts of one logical call (initial + retries).
    call_group_id            uuid        NOT NULL,
    -- 1-based attempt index within the call group.
    attempt                  smallint    NOT NULL DEFAULT 1
        CHECK (attempt >= 1),
    -- Which LLM invention/usage point issued the call. 'probe' = the
    -- pre-flight health-gate probe (logged so it feeds the rolling window).
    call_site                text        NOT NULL
        CHECK (call_site IN ('mutator','curator','generator','narrator','probe')),
    -- Pinned model string actually sent (e.g. 'claude-sonnet-4-6').
    model                    text        NOT NULL,
    -- HTTP status. NULL when no response was received (network/timeout).
    status_code              integer,
    -- Coarse outcome classifier.
    outcome                  text        NOT NULL
        CHECK (outcome IN ('success','error','timeout','network_error')),
    -- Anthropic error.type when outcome='error' (e.g. 'overloaded_error',
    -- 'rate_limit_error', 'api_error'). NULL otherwise.
    error_type               text,
    -- Wall-clock latency for this attempt. NULL on immediate network failure.
    latency_ms               integer     CHECK (latency_ms IS NULL OR latency_ms >= 0),
    input_tokens             integer     CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens            integer     CHECK (output_tokens IS NULL OR output_tokens >= 0),
    cache_read_input_tokens  integer     CHECK (cache_read_input_tokens IS NULL OR cache_read_input_tokens >= 0),
    -- Anthropic request-id header (req_...). Correlation key for support and
    -- status.claude.com. NULL when no response was received.
    request_id               text,
    created_at               timestamptz NOT NULL DEFAULT now()
);

-- Rolling-window gate: scans recent rows by time, then filters to 529s.
CREATE INDEX idx_llm_call_log_created_at
    ON llm_call_log (created_at DESC);

-- Per-call-site slicing for the /agent indicator and diagnostics.
CREATE INDEX idx_llm_call_log_site_created_at
    ON llm_call_log (call_site, created_at DESC);

-- request_id lookups when investigating a specific failed call.
CREATE INDEX idx_llm_call_log_request_id
    ON llm_call_log (request_id)
    WHERE request_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Verification — fail the transaction if the migration did not fully apply.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'llm_call_log'
    ) THEN
        RAISE EXCEPTION 'migration 011: llm_call_log table was not created';
    END IF;

    IF (SELECT count(*)
        FROM information_schema.columns
        WHERE table_name = 'llm_call_log'
          AND column_name IN
            ('call_group_id','attempt','call_site','model','status_code',
             'outcome','request_id','created_at')) < 8 THEN
        RAISE EXCEPTION 'migration 011: expected columns missing on llm_call_log';
    END IF;

    IF (SELECT count(*) FROM pg_indexes WHERE tablename = 'llm_call_log') < 3 THEN
        RAISE EXCEPTION
            'migration 011: expected >= 3 indexes on llm_call_log, found %',
            (SELECT count(*) FROM pg_indexes WHERE tablename = 'llm_call_log');
    END IF;
END $$;

COMMIT;

-- ===========================================================================
-- Reference — canonical health-gate query (NOT executed by this migration).
-- Rolling 529 rate over the last :window_minutes, with a minimum sample
-- count :min_samples so a lone 529 in a quiet window cannot trip the gate.
--
--   SELECT
--       count(*)                                          AS attempts,
--       count(*) FILTER (WHERE status_code = 529)         AS overloaded,
--       count(*) FILTER (WHERE status_code = 529)::float
--           / NULLIF(count(*), 0)                         AS overloaded_rate
--   FROM llm_call_log
--   WHERE created_at >= now() - (:window_minutes * interval '1 minute');
--
--   -- Gate trips (abort cycle) when:
--   --   attempts >= :min_samples AND overloaded_rate >= :threshold
-- ===========================================================================
