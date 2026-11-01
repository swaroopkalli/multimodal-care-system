import logging
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def get_db_connection():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT"),
        sslmode=os.getenv("DB_SSLMODE", "require"),
        connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
        cursor_factory=RealDictCursor,
    )
    return conn


_BASE_TABLES = """
    CREATE TABLE IF NOT EXISTS caretakers (
        id SERIAL PRIMARY KEY,
        username VARCHAR(255) NOT NULL UNIQUE,
        name VARCHAR(255) NOT NULL,
        password VARCHAR(255) NOT NULL
    );

    CREATE TABLE IF NOT EXISTS doctors (
        id SERIAL PRIMARY KEY,
        username VARCHAR(255) NOT NULL UNIQUE,
        name VARCHAR(255) NOT NULL,
        password VARCHAR(255) NOT NULL
    );

    CREATE TABLE IF NOT EXISTS patients (
        id SERIAL PRIMARY KEY,
        username VARCHAR(255) NOT NULL UNIQUE,
        name VARCHAR(255) NOT NULL,
        password VARCHAR(255) NOT NULL,
        caretaker_id INTEGER REFERENCES caretakers(id) ON DELETE SET NULL,
        doctor_id INTEGER REFERENCES doctors(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS medications (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        "type" VARCHAR(255) NOT NULL,
        duration INTEGER NOT NULL,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        prescribed_by INTEGER REFERENCES doctors(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS wearable_data (
        id SERIAL PRIMARY KEY,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        pedometer INTEGER,
        sleep_minutes INTEGER,
        screentime_minutes INTEGER,
        heartrate INTEGER,
        event_id UUID UNIQUE
    );

    CREATE TABLE IF NOT EXISTS doctor_notes (
        id SERIAL PRIMARY KEY,
        doctor_id INTEGER NOT NULL REFERENCES doctors(id) ON DELETE CASCADE,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        note TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS patient_contexts (
        id SERIAL PRIMARY KEY,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        context TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS chatbot_logs (
        id SERIAL PRIMARY KEY,
        role VARCHAR(50) NOT NULL,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        query TEXT NOT NULL,
        response TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""


def apply_migrations(conn):
    """Run backend/migrations/*.sql in name order. Files are idempotent."""
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version VARCHAR(128) PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        cursor.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (path.name,))
        if cursor.fetchone():
            continue
        try:
            cursor.execute(path.read_text(encoding="utf-8"))
            cursor.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            conn.commit()
            log.info("Applied migration %s", path.name)
        except Exception:
            conn.rollback()
            raise
    cursor.close()


def create_tables():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(_BASE_TABLES)
        # Databases created before wearable event IDs existed.
        cursor.execute("ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS event_id UUID")
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS wearable_data_event_id_unique ON wearable_data (event_id)"
        )
        conn.commit()
        cursor.close()
        apply_migrations(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_tables()
    print("Schema is up to date.")
