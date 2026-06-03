-- v3 Day 1: evolution loop tables (skill lineage, backtest runs, shadow forecasts)
-- Requires 001–005 applied (forecasts.trace from 004; 005 wind_fields optional).

BEGIN;

CREATE TABLE skill_lineage (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id          TEXT NOT NULL,
    parent_skill_id   TEXT,
    version           INTEGER NOT NULL,
    source_code       TEXT NOT NULL,
    skill_md          TEXT NOT NULL DEFAULT '',
    generation_method TEXT NOT NULL DEFAULT 'manual'
        CHECK (generation_method IN ('manual', 'mutated', 'generated')),
    proposal_id       UUID REFERENCES skill_edit_proposals(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (skill_id, version)
);

CREATE TABLE backtest_run (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id          TEXT NOT NULL,
    version           INTEGER,
    lineage_id        UUID REFERENCES skill_lineage(id),
    window_start      TIMESTAMPTZ NOT NULL,
    window_end        TIMESTAMPTZ NOT NULL,
    brier_score       DOUBLE PRECISION,
    hits              INTEGER NOT NULL DEFAULT 0,
    false_positives   INTEGER NOT NULL DEFAULT 0,
    misses            INTEGER NOT NULL DEFAULT 0,
    forecasts_emitted INTEGER NOT NULL DEFAULT 0,
    run_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_backtest_run_skill ON backtest_run (skill_id, version);

CREATE TABLE forecasts_shadow (
    LIKE forecasts INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES
);
ALTER TABLE forecasts_shadow
    ADD COLUMN shadow_promotion_status TEXT NOT NULL DEFAULT 'evaluating'
        CHECK (shadow_promotion_status IN ('evaluating', 'promoted', 'discarded')),
    ADD COLUMN lineage_id UUID REFERENCES skill_lineage(id);

ALTER TABLE skill_edit_proposals
    ADD COLUMN lineage_id UUID REFERENCES skill_lineage(id);

COMMIT;
