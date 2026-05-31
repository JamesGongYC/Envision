-- Envision — migration 004: v2 trace instrumentation + signal catalog
-- Apply once in Neon SQL Editor (001–003 must already be applied).
-- Not idempotent on re-run.

BEGIN;

-- Trace instrumentation
ALTER TABLE forecasts
  ADD COLUMN trace JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE skill_edit_proposals
  ADD COLUMN curator_trace JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Trace size cap (sanity)
ALTER TABLE forecasts
  ADD CONSTRAINT trace_size_cap CHECK (octet_length(trace::text) <= 16384);

-- Signal catalog (refreshed daily by housekeeping-retention)
CREATE MATERIALIZED VIEW signal_catalog AS
SELECT
  source,
  signal_type,
  COUNT(*) AS row_count,
  MIN(timestamp) AS first_seen,
  MAX(timestamp) AS last_seen,
  ST_Envelope(ST_Collect(geometry)) AS coverage_bbox,
  (array_agg(payload ORDER BY timestamp DESC))[1:3] AS sample_payloads
FROM signals
GROUP BY source, signal_type;

CREATE UNIQUE INDEX ON signal_catalog (source, signal_type);

COMMIT;
