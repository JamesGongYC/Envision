-- v3 Day 3: shadow forecast evaluations (mirror of evaluations for forecasts_shadow)
-- Requires 006_evolution.sql (forecasts_shadow) applied.

BEGIN;

CREATE TABLE shadow_evaluations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shadow_forecast_id      UUID NOT NULL REFERENCES forecasts_shadow(id),
    matched_ground_truth_id UUID REFERENCES ground_truth(id),
    outcome                 TEXT NOT NULL,
    brier_contribution      DOUBLE PRECISION NOT NULL,
    evaluated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_shadow_eval_fc ON shadow_evaluations (shadow_forecast_id);

COMMIT;
