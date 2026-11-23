-- MindBridge schema migration 002: Clinician-in-the-Loop & Active Caregiver Collaboration
-- Idempotent and additive; safe to re-run.

-- ---------------------------------------------------------------------------
-- 1. Journal entries: doctor replies / remarks with timestamps
-- ---------------------------------------------------------------------------
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS doctor_reply TEXT;
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS doctor_reply_at TIMESTAMP;
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS replied_by_doctor_id INTEGER REFERENCES doctors(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_journal_entries_reply ON journal_entries (patient_id, doctor_reply_at);

-- ---------------------------------------------------------------------------
-- 2. Patient Care Directives: doctor instructions active in AI context & RAG
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS patient_care_directives (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
    directive TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_directives_patient_active ON patient_care_directives (patient_id, is_active, created_at DESC);

-- ---------------------------------------------------------------------------
-- 3. Clinical Alerts: threshold-driven alerts for doctors and caretakers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clinical_alerts (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    alert_type VARCHAR(48) NOT NULL,
    severity VARCHAR(16) NOT NULL, -- 'critical' | 'high' | 'medium' | 'low'
    message TEXT NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'checkin', -- 'checkin' | 'chat' | 'wearable'
    is_acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_at TIMESTAMP,
    acknowledged_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_patient_ack ON clinical_alerts (patient_id, is_acknowledged, created_at DESC);
