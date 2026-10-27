import os
import psycopg2

from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT"),
        cursor_factory=RealDictCursor,
    )
    return conn


def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
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
            name VARCHAR(255) PRIMARY KEY,
            "type" VARCHAR(255) NOT NULL,
            duration INTEGER NOT NULL,
            patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
            prescribed_by INTEGER NOT NULL REFERENCES doctors(id) ON DELETE SET NULL
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
    """)

    # Additive migration for databases created before wearable event IDs existed.
    cursor.execute("ALTER TABLE wearable_data ADD COLUMN IF NOT EXISTS event_id UUID")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS wearable_data_event_id_unique ON wearable_data (event_id)")

    conn.commit()
    cursor.close()
    conn.close()


if __name__ == "__main__":
    create_tables()
