"""Apply the ingestion SQL schema using root or ingestion-local .env config."""

from pathlib import Path

import psycopg2

from env_config import load_ingestion_environment


def main() -> None:
    load_ingestion_environment(__file__)
    import os

    required = ("INGESTION_DB_HOST", "INGESTION_DB_USER", "INGESTION_DB_PASSWORD")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise SystemExit(f"Missing required environment settings: {', '.join(missing)}")

    conn = psycopg2.connect(
        host=os.environ["INGESTION_DB_HOST"],
        port=os.getenv("INGESTION_DB_PORT", "6543"),
        dbname=os.getenv("INGESTION_DB_NAME", "postgres"),
        user=os.environ["INGESTION_DB_USER"],
        password=os.environ["INGESTION_DB_PASSWORD"],
        sslmode=os.getenv("INGESTION_DB_SSLMODE", "require"),
        connect_timeout=10,
    )
    try:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with conn.cursor() as cursor:
            cursor.execute(schema)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("Schema applied successfully; wearable_data.event_id is available.")


if __name__ == "__main__":
    main()
