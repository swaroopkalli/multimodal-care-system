"""
MindBridge – Mock Wearable Simulator
=====================================
Generates synthetic vital-sign measurements and publishes them to
the Redis ``wearable:vitals`` channel via Pub/Sub over TCP.

IMPORTANT DISCLAIMERS
---------------------
* All measurements are randomly generated for testing purposes.
* ``"simulation": true`` is embedded in every event payload.
* These values do NOT represent any real patient's health data.
* This simulator must never be connected to a real medical device
  or used in a clinical context.

ARCHITECTURE POSITION
----------------------
    [simulator.py]
          |
          | redis-py TCP  PUBLISH wearable:vitals <JSON>
          v
    [Redis 7 (Docker)]
          |
          +----> subscriber_postgres.py  (persists to Supabase PostgreSQL)
          +----> subscriber_redis_cache.py (updates Redis latest-vitals cache)

Usage
-----
    python simulator.py

Configuration (from .env in this directory)
-------------------------------------------
    REDIS_HOST               default: 127.0.0.1
    REDIS_PORT               default: 6379
    REDIS_CHANNEL            default: wearable:vitals
    SIMULATOR_PATIENT_IDS    default: 1   (comma-separated list)
    SIMULATOR_INTERVAL_SECONDS default: 5
    SIMULATOR_DEVICE_ID      default: sim-device-001
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# pyrefly: ignore[missing-import]
import redis
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

# Load .env from THIS directory (wearable_ingestion/), NOT the project root.
# This intentionally avoids reading the application's existing .env.
_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SIMULATOR] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_HOST: str = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL: str = os.getenv("REDIS_CHANNEL", "wearable:vitals")
INTERVAL: float = float(os.getenv("SIMULATOR_INTERVAL_SECONDS", "5"))
DEVICE_ID: str = os.getenv("SIMULATOR_DEVICE_ID", "sim-device-001")

_raw_patient_ids = os.getenv("SIMULATOR_PATIENT_IDS", "1")
PATIENT_IDS: list[int] = [int(p.strip()) for p in _raw_patient_ids.split(",") if p.strip()]

if not PATIENT_IDS:
    log.error("SIMULATOR_PATIENT_IDS must contain at least one patient ID.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Synthetic vital-sign ranges
# Derived from the existing wearable_data schema columns:
#   pedometer, sleep_minutes, screentime_minutes, heartrate
#
# Ranges are realistic but intentionally slightly noisy to simulate
# a real sensor stream.  Values are not clinically validated.
# ---------------------------------------------------------------------------

def _generate_vitals(patient_id: int, sequence: int) -> dict:
    """Return a single synthetic vital-sign event dict."""
    return {
        # Ingestion metadata
        "event_id": str(uuid.uuid4()),
        "device_id": DEVICE_ID,
        "patient_id": patient_id,
        "sequence": sequence,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "simulation": True,           # ALWAYS True — never real data

        # Columns matching wearable_data schema (backend/db.py)
        "pedometer": random.randint(100, 800),          # steps per interval
        "sleep_minutes": random.randint(200, 540),       # cumulative daily
        "screentime_minutes": random.randint(20, 480),   # cumulative daily
        "heartrate": random.randint(58, 105),            # resting bpm
    }


# ---------------------------------------------------------------------------
# Redis connection with retry
# ---------------------------------------------------------------------------

def _connect_redis() -> redis.Redis:
    """Return a Redis client.  Blocks until connection succeeds."""
    backoff = 1.0
    while True:
        try:
            client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            client.ping()
            log.info("Connected to Redis at %s:%s", REDIS_HOST, REDIS_PORT)
            return client
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning(
                "Redis connection failed (%s). Retrying in %.0f s…", exc, backoff
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run() -> None:
    log.info(
        "Simulator starting — channel=%s  patients=%s  interval=%.1fs",
        REDIS_CHANNEL, PATIENT_IDS, INTERVAL,
    )

    client = _connect_redis()

    # Cycle through patient IDs indefinitely, giving each one a turn.
    patient_cycle = itertools.cycle(PATIENT_IDS)
    sequence_counters: dict[int, int] = {pid: 0 for pid in PATIENT_IDS}

    while True:
        patient_id = next(patient_cycle)
        sequence_counters[patient_id] += 1
        seq = sequence_counters[patient_id]

        event = _generate_vitals(patient_id, seq)
        payload = json.dumps(event)

        try:
            subscriber_count = client.publish(REDIS_CHANNEL, payload)
            log.info(
                "Published event_id=%s  patient=%s  seq=%s  hr=%s bpm  "
                "sleep=%s min  subscribers=%s",
                event["event_id"][:8],
                patient_id,
                seq,
                event["heartrate"],
                event["sleep_minutes"],
                subscriber_count,
            )
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning("Redis publish failed: %s — reconnecting…", exc)
            client = _connect_redis()

        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Simulator stopped by user.")
