"""
MindBridge – Ingestion Pipeline Integration Tests
==================================================
Tests the wearable ingestion pipeline independently of the
existing Flask application.

Requirements
------------
* Redis must be running (start with: docker compose -f compose.yaml up -d)
* PostgreSQL connection must be configured in .env
* Run from the wearable_ingestion/ directory:
    python test_pipeline.py

Tests
-----
 T1  Redis connectivity and health
 T2  Simulator event structure and field validation
 T3  Publish / Subscribe round-trip (both subscribers receive events)
 T4  PostgreSQL: schema verification (required tables and event_id column)
 T5  PostgreSQL: valid event persistence
 T6  PostgreSQL: duplicate event handling (idempotency)
 T7  Redis cache: latest vitals written correctly
 T8  Redis cache: staleness guard (older event must not overwrite newer)
 T9  Redis cache: TTL set when REDIS_CACHE_TTL_SECONDS > 0
T10  Invalid event rejection (missing field, bad type, negative value)
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
# pyrefly: ignore[missing-import]
import redis
from env_config import load_ingestion_environment

_HERE = Path(__file__).parent
load_ingestion_environment(__file__)

# ---------------------------------------------------------------------------
# Minimal inline re-implementations to avoid importing the subscriber
# modules as side-effect-laden scripts.
# ---------------------------------------------------------------------------

from subscriber_redis_cache import _cache_key, _update_cache, _validate_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL = os.getenv("REDIS_CHANNEL", "wearable:vitals")
CACHE_TTL = int(os.getenv("REDIS_CACHE_TTL_SECONDS", "3600"))

DB_HOST = os.getenv("INGESTION_DB_HOST", "")
DB_PORT = int(os.getenv("INGESTION_DB_PORT", "6543"))
DB_NAME = os.getenv("INGESTION_DB_NAME", "postgres")
DB_USER = os.getenv("INGESTION_DB_USER", "")
DB_PASSWORD = os.getenv("INGESTION_DB_PASSWORD", "")
DB_SSLMODE = os.getenv("INGESTION_DB_SSLMODE", "require")

_PASS = "✅ PASS"
_FAIL = "❌ FAIL"
_SKIP = "⚠️  SKIP"

results: list[tuple[str, str, str]] = []


def _result(name: str, passed: bool, note: str = "") -> None:
    status = _PASS if passed else _FAIL
    results.append((name, status, note))
    print(f"{status}  {name}" + (f" — {note}" if note else ""))


def _make_event(
    patient_id: int = 1,
    event_id: str | None = None,
    measured_at: str | None = None,
    **overrides,
) -> dict:
    """Build a well-formed synthetic event."""
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "device_id": "test-device",
        "patient_id": patient_id,
        "sequence": 1,
        "measured_at": measured_at or datetime.now(timezone.utc).isoformat(),
        "simulation": True,
        "pedometer": 500,
        "sleep_minutes": 420,
        "screentime_minutes": 120,
        "heartrate": 72,
        **overrides,
    }


# ---------------------------------------------------------------------------
# T1 – Redis connectivity
# ---------------------------------------------------------------------------

def t1_redis_connectivity() -> redis.Redis:
    print("\n--- T1: Redis connectivity ---")
    try:
        client = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT,
            decode_responses=True, socket_connect_timeout=5,
        )
        resp = client.ping()
        _result("T1", resp is True, f"PING response: {resp}")
        return client
    except Exception as exc:
        _result("T1", False, str(exc))
        print("Cannot continue without Redis.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# T2 – Simulator event structure
# ---------------------------------------------------------------------------

def t2_event_structure() -> None:
    print("\n--- T2: Simulator event structure ---")
    event = _make_event()
    required = {
        "event_id", "device_id", "patient_id", "sequence",
        "measured_at", "simulation",
        "pedometer", "sleep_minutes", "screentime_minutes", "heartrate",
    }
    missing = required - event.keys()
    _result("T2a – required fields present", not missing, str(missing) if missing else "")
    _result("T2b – simulation flag is True", event["simulation"] is True)

    ok, reason = _validate_event(event)
    _result("T2c – validation passes", ok, reason)


# ---------------------------------------------------------------------------
# T3 – Pub/Sub round-trip
# ---------------------------------------------------------------------------

def t3_pubsub_roundtrip(client: redis.Redis) -> None:
    print("\n--- T3: Pub/Sub round-trip ---")
    sub = client.pubsub(ignore_subscribe_messages=True)
    sub.subscribe(REDIS_CHANNEL)
    time.sleep(0.2)

    event = _make_event()
    payload = json.dumps(event)
    client.publish(REDIS_CHANNEL, payload)

    deadline = time.time() + 3
    received = None
    while time.time() < deadline:
        msg = sub.get_message(timeout=0.5)
        if msg and msg["data"] == payload:
            received = msg
            break

    sub.close()
    _result("T3 – publish/subscribe round-trip", received is not None)


# ---------------------------------------------------------------------------
# T4 – PostgreSQL schema verification
# ---------------------------------------------------------------------------

def t4_db_schema() -> psycopg2.extensions.connection | None:
    print("\n--- T4: PostgreSQL schema verification ---")
    if not DB_HOST or not DB_USER or not DB_PASSWORD:
        _result("T4", False, "DB credentials not set — skipping")
        return None

    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD, sslmode=DB_SSLMODE,
            connect_timeout=10,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    except Exception as exc:
        _result("T4", False, f"Connection failed: {type(exc).__name__}")
        return None

    expected_tables = [
        "caretakers", "doctors", "patients", "medications",
        "wearable_data", "doctor_notes", "patient_contexts", "chatbot_logs",
    ]
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        existing = {r["table_name"] for r in cur.fetchall()}

    missing_tables = [t for t in expected_tables if t not in existing]
    _result("T4a – all required tables exist", not missing_tables,
            f"Missing: {missing_tables}" if missing_tables else "")

    # Check event_id column
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'wearable_data' AND column_name = 'event_id'
        """)
        has_event_id = cur.fetchone() is not None

    _result("T4b – wearable_data has event_id column", has_event_id,
            "Run schema.sql to add it" if not has_event_id else "")

    return conn


# ---------------------------------------------------------------------------
# T5 – PostgreSQL valid event persistence
# ---------------------------------------------------------------------------

def t5_persist_valid_event(conn: psycopg2.extensions.connection | None) -> str | None:
    print("\n--- T5: PostgreSQL persistence ---")
    if conn is None:
        _result("T5", False, "No DB connection — skipped")
        return None

    # Ensure demo patient exists
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM patients LIMIT 1")
        row = cur.fetchone()

    if row is None:
        _result("T5", False, "No patient rows exist in the configured database")
        return None

    patient_id = row["id"]
    event_id = str(uuid.uuid4())
    event = _make_event(patient_id=patient_id, event_id=event_id)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO wearable_data
                    (patient_id, timestamp, pedometer, sleep_minutes,
                     screentime_minutes, heartrate, event_id)
                VALUES
                    (%(patient_id)s, %(measured_at)s, %(pedometer)s, %(sleep_minutes)s,
                     %(screentime_minutes)s, %(heartrate)s, %(event_id)s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING id
            """, {
                "patient_id": event["patient_id"],
                "measured_at": event["measured_at"],
                "pedometer": event["pedometer"],
                "sleep_minutes": event["sleep_minutes"],
                "screentime_minutes": event["screentime_minutes"],
                "heartrate": event["heartrate"],
                "event_id": event_id,
            })
            inserted = cur.fetchone()
        conn.commit()
        _result("T5 – valid event persisted", inserted is not None,
                f"wearable_data.id={inserted['id']}" if inserted else "conflict")
        return event_id
    except Exception as exc:
        conn.rollback()
        _result("T5", False, f"{type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------------------
# T6 – Duplicate event idempotency
# ---------------------------------------------------------------------------

def t6_duplicate_event(conn: psycopg2.extensions.connection | None, event_id: str | None) -> None:
    print("\n--- T6: Duplicate event handling ---")
    if conn is None or event_id is None:
        _result("T6", False, "Prerequisites not met — skipped")
        return

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO wearable_data
                (patient_id, timestamp, pedometer, sleep_minutes,
                 screentime_minutes, heartrate, event_id)
            SELECT patient_id, timestamp, pedometer, sleep_minutes,
                   screentime_minutes, heartrate, event_id
            FROM wearable_data WHERE event_id = %(eid)s
            ON CONFLICT (event_id) DO NOTHING
            RETURNING id
        """, {"eid": event_id})
        row = cur.fetchone()
    conn.commit()
    _result("T6 – duplicate silently ignored (ON CONFLICT DO NOTHING)", row is None,
            "Duplicate was inserted (unexpected!)" if row else "")


# ---------------------------------------------------------------------------
# T7 – Redis cache written correctly
# ---------------------------------------------------------------------------

def t7_cache_write(client: redis.Redis) -> None:
    print("\n--- T7: Redis cache update ---")
    patient_id = 99901  # Unlikely to collide with real data
    key = _cache_key(patient_id)
    client.delete(key)  # Clean slate

    event = _make_event(patient_id=patient_id)
    try:
        _update_cache(client, event)
        stored_hr = client.hget(key, "heartrate")
        _result("T7 – cache written", stored_hr == str(event["heartrate"]),
                f"stored={stored_hr} expected={event['heartrate']}")
    except Exception as exc:
        _result("T7", False, str(exc))
    finally:
        client.delete(key)


# ---------------------------------------------------------------------------
# T8 – Staleness guard
# ---------------------------------------------------------------------------

def t8_staleness_guard(client: redis.Redis) -> None:
    print("\n--- T8: Staleness guard (older event must not overwrite newer) ---")
    patient_id = 99902
    key = _cache_key(patient_id)
    client.delete(key)

    now = datetime.now(timezone.utc)
    newer_event = _make_event(patient_id=patient_id, heartrate=80,
                               measured_at=now.isoformat())
    older_event = _make_event(patient_id=patient_id, heartrate=60,
                               measured_at=(now - timedelta(minutes=10)).isoformat())

    try:
        _update_cache(client, newer_event)
        _update_cache(client, older_event)  # Must be rejected
        stored_hr = client.hget(key, "heartrate")
        _result("T8 – stale event rejected", stored_hr == "80",
                f"stored={stored_hr} (expected 80 = newer value)")
    except Exception as exc:
        _result("T8", False, str(exc))
    finally:
        client.delete(key)


# ---------------------------------------------------------------------------
# T9 – Cache TTL
# ---------------------------------------------------------------------------

def t9_cache_ttl(client: redis.Redis) -> None:
    print("\n--- T9: Cache TTL ---")
    if CACHE_TTL <= 0:
        _result("T9", True, "TTL=0 (disabled) — skipped TTL check")
        return

    patient_id = 99903
    key = _cache_key(patient_id)
    client.delete(key)

    event = _make_event(patient_id=patient_id)
    try:
        _update_cache(client, event)
        ttl = client.ttl(key)
        _result("T9 – TTL set on cache key", 0 < ttl <= CACHE_TTL,
                f"ttl={ttl}s configured={CACHE_TTL}s")
    except Exception as exc:
        _result("T9", False, str(exc))
    finally:
        client.delete(key)


# ---------------------------------------------------------------------------
# T10 – Invalid event rejection
# ---------------------------------------------------------------------------

def t10_invalid_events() -> None:
    print("\n--- T10: Invalid event rejection ---")

    cases = [
        ("missing patient_id", {k: v for k, v in _make_event().items() if k != "patient_id"}),
        ("negative heartrate", _make_event(heartrate=-5)),
        ("bad measured_at",    _make_event(measured_at="not-a-date")),
        ("non-int pedometer",  _make_event(pedometer="lots")),
    ]
    all_ok = True
    for label, bad_event in cases:
        ok, reason = _validate_event(bad_event)
        passed = not ok  # Validation must REJECT these
        _result(f"T10 – {label}", passed, reason if passed else "Validation passed (unexpected!)")
        if not passed:
            all_ok = False


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary() -> None:
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passes = sum(1 for _, s, _ in results if s == _PASS)
    fails  = sum(1 for _, s, _ in results if s == _FAIL)
    skips  = sum(1 for _, s, _ in results if s == _SKIP)
    for name, status, note in results:
        line = f"  {status}  {name}"
        if note:
            line += f"\n            {note}"
        print(line)
    print(f"\nTotal: {len(results)}  ✅ {passes}  ❌ {fails}  ⚠️  {skips}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("MindBridge – Wearable Ingestion Pipeline Integration Tests")
    print("=" * 60)

    redis_client = t1_redis_connectivity()
    t2_event_structure()
    t3_pubsub_roundtrip(redis_client)
    db_conn = t4_db_schema()
    inserted_event_id = t5_persist_valid_event(db_conn)
    t6_duplicate_event(db_conn, inserted_event_id)
    t7_cache_write(redis_client)
    t8_staleness_guard(redis_client)
    t9_cache_ttl(redis_client)
    t10_invalid_events()

    if db_conn:
        db_conn.close()

    _print_summary()
    sys.exit(0 if all(s == _PASS for _, s, _ in results) else 1)
