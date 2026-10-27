"""
MindBridge – PostgreSQL Persistence Subscriber
===============================================
Subscribes independently to the Redis ``wearable:vitals`` Pub/Sub
channel and persists valid inbound measurements to the fresh
Supabase PostgreSQL database.

ARCHITECTURE POSITION
---------------------
    [Redis wearable:vitals channel]
              |
              | (this process)
              v
    [Supabase PostgreSQL – wearable_data table]

DESIGN DECISIONS
----------------
* Uses the ingestion DB settings from repository-root .env, with optional
  feature-local overrides.
  It does NOT import or reuse backend/db.py.
* Parameterized SQL only — no string formatting of user data.
* Validates required fields and types before touching the database.
* Duplicate prevention via event_id UNIQUE constraint (see schema.sql).
  If the constraint fires, the event is logged and skipped — not an error.
* Transactional: commit on success, rollback on failure.
* Reconnects to both Redis and PostgreSQL after transient failures.
* Does NOT modify any existing Flask routes, context builders, or auth.

KNOWN LIMITATIONS (Redis Pub/Sub)
----------------------------------
* A subscriber that is disconnected will NOT receive messages published
  while it was offline.  There is no replay mechanism.
* Retries in this process apply only to events already received in memory.
* Exactly-once delivery is NOT guaranteed across Redis and PostgreSQL.

Usage
-----
    python subscriber_postgres.py

Configuration (root .env; optional local .env overrides)
-------------------------------------------
    INGESTION_DB_HOST
    INGESTION_DB_PORT
    INGESTION_DB_NAME
    INGESTION_DB_USER
    INGESTION_DB_PASSWORD
    INGESTION_DB_SSLMODE   (default: require)
    REDIS_HOST             (default: 127.0.0.1)
    REDIS_PORT             (default: 6379)
    REDIS_CHANNEL          (default: wearable:vitals)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
# pyrefly: ignore[missing-import]
import redis
from env_config import load_ingestion_environment

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
load_ingestion_environment(__file__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PG-SUB] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_HOST: str = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL: str = os.getenv("REDIS_CHANNEL", "wearable:vitals")

DB_HOST: str = os.getenv("INGESTION_DB_HOST", "")
DB_PORT: int = int(os.getenv("INGESTION_DB_PORT", "6543"))
DB_NAME: str = os.getenv("INGESTION_DB_NAME", "postgres")
DB_USER: str = os.getenv("INGESTION_DB_USER", "")
DB_PASSWORD: str = os.getenv("INGESTION_DB_PASSWORD", "")
DB_SSLMODE: str = os.getenv("INGESTION_DB_SSLMODE", "require")

if not DB_HOST or not DB_USER or not DB_PASSWORD:
    log.error(
        "INGESTION_DB_HOST, INGESTION_DB_USER, and INGESTION_DB_PASSWORD "
        "must be set in the repository root .env or exported in the shell"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {
    "event_id", "patient_id", "measured_at",
    "pedometer", "sleep_minutes", "screentime_minutes", "heartrate",
}

_INT_FIELDS = {"patient_id", "pedometer", "sleep_minutes", "screentime_minutes", "heartrate"}


def _validate_event(event: dict[str, Any]) -> tuple[bool, str]:
    """Return (is_valid, reason).  Validates structure and types only."""
    missing = _REQUIRED_FIELDS - event.keys()
    if missing:
        return False, f"Missing required fields: {missing}"

    for field in _INT_FIELDS:
        try:
            val = int(event[field])
            if val < 0:
                return False, f"Field '{field}' must be non-negative, got {val}"
        except (TypeError, ValueError):
            return False, f"Field '{field}' must be an integer, got {event[field]!r}"

    try:
        datetime.fromisoformat(str(event["measured_at"]).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False, f"Field 'measured_at' is not a valid ISO timestamp: {event['measured_at']!r}"

    if not isinstance(event.get("simulation"), bool):
        return False, "Field 'simulation' must be a boolean"

    return True, ""


# ---------------------------------------------------------------------------
# Database connection with retry
# ---------------------------------------------------------------------------

def _connect_db() -> psycopg2.extensions.connection:
    """Return a psycopg2 connection.  Blocks until connection succeeds."""
    backoff = 1.0
    while True:
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                sslmode=DB_SSLMODE,
                connect_timeout=10,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            conn.autocommit = False
            log.info("Connected to PostgreSQL at %s:%s db=%s", DB_HOST, DB_PORT, DB_NAME)
            return conn
        except psycopg2.OperationalError as exc:
            # Do NOT log the exception message in full — it may include
            # connection-string fragments with credentials.
            log.warning(
                "PostgreSQL connection failed. Retrying in %.0f s…", backoff
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


# ---------------------------------------------------------------------------
# Redis connection with retry
# ---------------------------------------------------------------------------

def _connect_redis_pubsub() -> tuple[redis.Redis, redis.client.PubSub]:
    backoff = 1.0
    while True:
        try:
            client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=10,
            )
            client.ping()
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(REDIS_CHANNEL)
            log.info("Subscribed to Redis channel '%s'", REDIS_CHANNEL)
            return client, pubsub
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning(
                "Redis connection failed (%s). Retrying in %.0f s…", exc, backoff
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

# INSERT uses ON CONFLICT (event_id) DO NOTHING to handle duplicates.
# event_id is the UUID included in every simulator event.
# The UNIQUE constraint on event_id is defined in schema.sql.
_INSERT_SQL = """
    INSERT INTO wearable_data (
        patient_id,
        timestamp,
        pedometer,
        sleep_minutes,
        screentime_minutes,
        heartrate,
        event_id
    ) VALUES (
        %(patient_id)s,
        %(measured_at)s,
        %(pedometer)s,
        %(sleep_minutes)s,
        %(screentime_minutes)s,
        %(heartrate)s,
        %(event_id)s
    )
    ON CONFLICT (event_id) DO NOTHING
    RETURNING id;
"""

# Validate patient exists before inserting (prevents FK violation).
_PATIENT_CHECK_SQL = "SELECT id FROM patients WHERE id = %(patient_id)s"


def _persist_event(conn: psycopg2.extensions.connection, event: dict[str, Any]) -> bool:
    """
    Persist a validated event to wearable_data.

    Returns True if the row was inserted, False if it was a known duplicate.
    Raises on unexpected errors (caller rolls back and reconnects).
    """
    with conn.cursor() as cur:
        # Validate patient exists in DB (avoids FK error leaking raw IDs in logs)
        cur.execute(_PATIENT_CHECK_SQL, {"patient_id": event["patient_id"]})
        if cur.fetchone() is None:
            raise ValueError(f"Unknown patient_id={event['patient_id']}")

        cur.execute(_INSERT_SQL, {
            "patient_id": int(event["patient_id"]),
            "measured_at": event["measured_at"],
            "pedometer": int(event["pedometer"]),
            "sleep_minutes": int(event["sleep_minutes"]),
            "screentime_minutes": int(event["screentime_minutes"]),
            "heartrate": int(event["heartrate"]),
            "event_id": event["event_id"],
        })
        row = cur.fetchone()

    if row is None:
        # ON CONFLICT did nothing — genuine duplicate
        conn.commit()
        return False

    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run() -> None:
    log.info("PostgreSQL subscriber starting — channel=%s", REDIS_CHANNEL)

    db_conn = _connect_db()
    _redis_client, pubsub = _connect_redis_pubsub()

    while True:
        try:
            message = pubsub.get_message(timeout=1.0)
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning("Redis error while polling: %s — reconnecting…", exc)
            try:
                pubsub.close()
            except Exception:
                pass
            _redis_client, pubsub = _connect_redis_pubsub()
            continue

        if message is None:
            continue

        raw = message.get("data", "")
        if not isinstance(raw, str):
            continue

        # Parse JSON
        try:
            event: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("Received non-JSON message: %s", exc)
            continue

        # Validate structure
        ok, reason = _validate_event(event)
        if not ok:
            log.warning("Rejected invalid event: %s", reason)
            continue

        # Persist to PostgreSQL
        short_id = str(event.get("event_id", ""))[:8]
        try:
            inserted = _persist_event(db_conn, event)
            if inserted:
                log.info(
                    "Persisted event_id=%s  patient=%s  hr=%s bpm",
                    short_id,
                    event["patient_id"],
                    event["heartrate"],
                )
            else:
                log.info("Duplicate event skipped: event_id=%s", short_id)

        except psycopg2.OperationalError:
            # Connection dropped — roll back and reconnect
            try:
                db_conn.rollback()
            except Exception:
                pass
            log.warning("PostgreSQL connection lost — reconnecting…")
            db_conn = _connect_db()

        except ValueError as exc:
            # Business-logic rejection (e.g. unknown patient)
            log.warning("Event rejected: %s  event_id=%s", exc, short_id)

        except Exception as exc:
            # Unexpected error — roll back to keep connection usable
            try:
                db_conn.rollback()
            except Exception:
                pass
            # Log without patient data
            log.error(
                "Unexpected error persisting event_id=%s: %s",
                short_id, type(exc).__name__,
            )


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("PostgreSQL subscriber stopped by user.")
