-- MindBridge schema migration 001. Idempotent and additive; safe to re-run.
-- Applied by backend/db.py (apply_migrations) after the base tables exist.

-- ---------------------------------------------------------------------------
-- medications: name alone was the primary key (one row per drug name for ALL
-- patients) and prescribed_by was NOT NULL while its FK said ON DELETE SET NULL.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'medications'
                     AND column_name = 'id') THEN
        ALTER TABLE medications DROP CONSTRAINT IF EXISTS medications_pkey;
        ALTER TABLE medications ADD COLUMN id SERIAL PRIMARY KEY;
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS medications_patient_name_unique ON medications (patient_id, name);
ALTER TABLE medications ALTER COLUMN prescribed_by DROP NOT NULL;

-- ---------------------------------------------------------------------------
-- wearable_data: provenance + smoothed values (raw columns are never modified)
-- ---------------------------------------------------------------------------
ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS is_simulated BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS source VARCHAR(32);
ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS device_id VARCHAR(128);
ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS received_at TIMESTAMP;
ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS heartrate_ewma DOUBLE PRECISION;
ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS pedometer_ewma DOUBLE PRECISION;
ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS ewma_config_version INTEGER;
ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS quality_flags TEXT[] NOT NULL DEFAULT '{}';

-- Every pre-existing row carries an event_id, which only the simulator pipeline
-- ever produced; mark them as synthetic.
UPDATE wearable_data SET is_simulated = TRUE, source = 'simulator'
 WHERE event_id IS NOT NULL AND source IS NULL;

CREATE INDEX IF NOT EXISTS idx_wearable_data_patient_ts ON wearable_data (patient_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_chatbot_logs_patient_created ON chatbot_logs (patient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_doctor_notes_patient_created ON doctor_notes (patient_id, created_at);

-- ---------------------------------------------------------------------------
-- Daily rollups and anomalies (derived from wearable_data, rebuildable)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wearable_daily (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    sample_count INTEGER NOT NULL,
    steps_total INTEGER,
    sleep_minutes INTEGER,
    screentime_minutes INTEGER,
    hr_mean DOUBLE PRECISION,
    hr_min INTEGER,
    hr_max INTEGER,
    hr_mean_ewma DOUBLE PRECISION,
    steps_ewma DOUBLE PRECISION,
    sleep_ewma DOUBLE PRECISION,
    screentime_ewma DOUBLE PRECISION,
    is_simulated BOOLEAN NOT NULL DEFAULT FALSE,
    ewma_config_version INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (patient_id, day)
);

CREATE TABLE IF NOT EXISTS wearable_anomalies (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    signal VARCHAR(32) NOT NULL,
    direction VARCHAR(8) NOT NULL,
    observed DOUBLE PRECISION NOT NULL,
    baseline DOUBLE PRECISION NOT NULL,
    spread DOUBLE PRECISION NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    severity VARCHAR(16) NOT NULL,
    history_days INTEGER NOT NULL,
    is_simulated BOOLEAN NOT NULL DEFAULT FALSE,
    ewma_config_version INTEGER,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (patient_id, day, signal)
);

-- ---------------------------------------------------------------------------
-- Patient / caretaker submissions that the UI previously only pretended to save
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS patient_checkins (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    mood REAL,
    stress REAL,
    sleep_hours REAL,
    energy REAL,
    side_effects TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    entry TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS caretaker_observations (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    caretaker_id INTEGER REFERENCES caretakers(id) ON DELETE SET NULL,
    did_not_sleep BOOLEAN NOT NULL DEFAULT FALSE,
    restless BOOLEAN NOT NULL DEFAULT FALSE,
    seems_better BOOLEAN NOT NULL DEFAULT FALSE,
    medication_confirmed BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_checkins_patient_created ON patient_checkins (patient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_journal_patient_created ON journal_entries (patient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_observations_patient_created ON caretaker_observations (patient_id, created_at);

-- ---------------------------------------------------------------------------
-- Chat / context bookkeeping
-- ---------------------------------------------------------------------------
-- 'direct' = sent as written, 'condensed' = a long message was condensed before
-- generation (the original text is always kept in chatbot_logs.query).
ALTER TABLE chatbot_logs ADD COLUMN IF NOT EXISTS input_handling VARCHAR(16) NOT NULL DEFAULT 'direct';
-- Hash of the source rows a stored context was built from; a changed hash means stale.
ALTER TABLE patient_contexts ADD COLUMN IF NOT EXISTS source_hash VARCHAR(64);

CREATE TABLE IF NOT EXISTS guardrail_events (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER REFERENCES patients(id) ON DELETE CASCADE,
    role VARCHAR(16) NOT NULL,
    stage VARCHAR(8) NOT NULL,          -- 'input' | 'output'
    category VARCHAR(48) NOT NULL,
    action VARCHAR(16) NOT NULL,        -- refused | crisis | retried | fallback
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_guardrail_events_patient ON guardrail_events (patient_id, created_at);

-- ---------------------------------------------------------------------------
-- Outbox: PostgreSQL stays authoritative; a worker mirrors rows into Neo4j.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS graph_sync_outbox (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(16) NOT NULL,   -- note | turn | journal | window | anomaly | medication
    entity_id BIGINT NOT NULL,
    patient_id INTEGER NOT NULL,
    op VARCHAR(8) NOT NULL DEFAULT 'upsert',
    status VARCHAR(12) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS graph_sync_outbox_pending_unique
    ON graph_sync_outbox (entity_type, entity_id, op) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_graph_sync_outbox_status ON graph_sync_outbox (status, id);
