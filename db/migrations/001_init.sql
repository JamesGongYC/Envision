-- Envision — initial schema (migration 001)
-- Target: Neon Postgres with PostGIS. Mirrors db/schemas.py (envision_plan.md §6).
--
-- Geometry is stored as native PostGIS geometry(Geometry, 4326). The app layer
-- exchanges GeoJSON; convert at the boundary:
--     write:  ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326)
--     read:   ST_AsGeoJSON(geometry)
--
-- Note: the plan's "approval_queue" (architecture diagram §3) is the
-- skill_edit_proposals table below, filtered to status = 'pending'.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- signals: normalized inbound observations from all data sources
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    "timestamp"  TIMESTAMPTZ NOT NULL,
    source       TEXT NOT NULL,
    signal_type  TEXT NOT NULL,
    geometry     geometry(Geometry, 4326) NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signals_geom      ON signals USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals ("timestamp");
CREATE INDEX IF NOT EXISTS idx_signals_source    ON signals (source);

-- ---------------------------------------------------------------------------
-- forecasts: detection-skill output. Probability hard-capped at 0.85 in v1.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecasts (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issued_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_from              TIMESTAMPTZ NOT NULL,
    valid_until             TIMESTAMPTZ NOT NULL,
    disaster_class          TEXT NOT NULL,
    geometry                geometry(Geometry, 4326) NOT NULL,
    probability             DOUBLE PRECISION NOT NULL
                              CHECK (probability >= 0.0 AND probability <= 0.85),
    skill_id                TEXT NOT NULL,
    skill_version           INTEGER NOT NULL,
    contributing_signal_ids UUID[] NOT NULL DEFAULT '{}',
    reasoning               TEXT NOT NULL DEFAULT '',
    is_baseline             BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_forecasts_geom      ON forecasts USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_forecasts_issued_at ON forecasts (issued_at);
CREATE INDEX IF NOT EXISTS idx_forecasts_class     ON forecasts (disaster_class);
CREATE INDEX IF NOT EXISTS idx_forecasts_skill     ON forecasts (skill_id, skill_version);
CREATE INDEX IF NOT EXISTS idx_forecasts_baseline  ON forecasts (is_baseline);

-- ---------------------------------------------------------------------------
-- ground_truth: confirmed events (GDACS etc.), consumed only by the evaluator
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ground_truth (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at     TIMESTAMPTZ NOT NULL,
    source          TEXT NOT NULL,
    disaster_class  TEXT NOT NULL,
    geometry        geometry(Geometry, 4326) NOT NULL,
    severity        TEXT,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_ground_truth_geom        ON ground_truth USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_ground_truth_occurred_at ON ground_truth (occurred_at);
CREATE INDEX IF NOT EXISTS idx_ground_truth_class       ON ground_truth (disaster_class);

-- ---------------------------------------------------------------------------
-- evaluations: per-forecast scoring against ground truth
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evaluations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    forecast_id             UUID NOT NULL REFERENCES forecasts(id) ON DELETE CASCADE,
    matched_ground_truth_id UUID REFERENCES ground_truth(id) ON DELETE SET NULL,
    outcome                 TEXT NOT NULL
                              CHECK (outcome IN ('hit', 'miss', 'false_positive')),
    brier_contribution      DOUBLE PRECISION NOT NULL,
    evaluated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evaluations_forecast ON evaluations (forecast_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_outcome  ON evaluations (outcome);

-- ---------------------------------------------------------------------------
-- skill_edit_proposals: Curator-proposed mutations, gated by manual approval
-- (the "approval_queue" in the architecture diagram is status = 'pending' here)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS skill_edit_proposals (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    skill_id          TEXT NOT NULL,
    current_version   INTEGER NOT NULL,
    proposed_code     TEXT NOT NULL,
    curator_reasoning TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'approved', 'rejected')),
    reviewed_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON skill_edit_proposals (status);
