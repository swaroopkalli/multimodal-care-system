"""
MindBridge – Redis Cache Subscriber
=====================================
Subscribes independently to the Redis ``wearable:vitals`` Pub/Sub
channel and maintains a ``patient:<id>:vitals:latest`` key for each
patient in Redis.

ARCHITECTURE POSITION
---------------------
    [Redis wearable:vitals channel]
              |
              | (this process)
              v
    [Redis – patient:<id>:vitals:latest hash]

DESIGN DECISIONS
----------------
* Operates entirely independently of the PostgreSQL subscriber.
  A failure in this process does NOT affect persistence.
* Uses Redis HSET + EXPIRE to store the latest vitals as a hash.
* Staleness guard: reads the existing ``measured_at`` before writing.
  If the incoming event is older than the stored value, it is skipped.
  This handles out-of-order Pub/Sub delivery.
* Does NOT compute or store clinical scores.
  It does NOT call the existing patient-context builder.
  It caches raw vital values only.
* The cache is entirely rebuildable from PostgreSQL wearable_data rows.
* This process does NOT import or alter any existing application code.

KNOWN LIMITATIONS (Redis Pub/Sub)
----------------------------------
* A disconnected subscriber misses all messages published while offline.
* Cache and PostgreSQL are updated independently; they are NOT atomic.
  If PostgreSQL persists a row and this process fails before caching it,
  the cache will be stale until the next successful event arrives.
* For this prototype, this inconsistency window is acceptable and documented.

Cache key schema
----------------
    patient:<patient_id>:vitals:latest   →  Redis Hash
        pedometer          : int
        sleep_minutes      : int
        screentime_minutes : int
        heartrate          : int
        measured_at        : ISO-8601 string
        event_id           : UUID string
        cached_at          : ISO-8601 string (when this key was written)

Usage
-----
    python subscriber_redis_cache.py

Configuration (from .env in this directory)
-------------------------------------------
    REDIS_HOST              (default: 127.0.0.1)
    REDIS_PORT              (default: 6379)
    REDIS_CHANNEL           (default: wearable:vitals)
    REDIS_CACHE_TTL_SECONDS (default: 3600, set 0 to disable expiry)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# pyrefly: ignore[missing-import]
import redis
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [REDIS-SUB] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REDIS_HOST: str = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL: str = os.getenv("REDIS_CHANNEL", "wearable:vitals")
CACHE_TTL: int = int(os.getenv("REDIS_CACHE_TTL_SECONDS", "3600"))


# ---------------------------------------------------------------------------
# Cache key helper
# ---------------------------------------------------------------------------

def _cache_key(patient_id: int) -> str:
    """Return the Redis key for a patient's latest vitals hash."""
    return f"patient:{patient_id}:vitals:latest"


# ---------------------------------------------------------------------------
# Validation (same rules as the PostgreSQL subscriber)
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {
    "event_id", "patient_id", "measured_at",
    "pedometer", "sleep_minutes", "screentime_minutes", "heartrate",
}
_INT_FIELDS = {"patient_id", "pedometer", "sleep_minutes", "screentime_minutes", "heartrate"}


def _validate_event(event: dict[str, Any]) -> tuple[bool, str]:
    missing = _REQUIRED_FIELDS - event.keys()
    if missing:
        return False, f"Missing required fields: {missing}"

    for field in _INT_FIELDS:
        try:
            val = int(event[field])
            if val < 0:
                return False, f"Field '{field}' must be non-negative, got {val}"
        except (TypeError, ValueError):
            return False, f"Field '{field}' must be int, got {event[field]!r}"

    try:
        datetime.fromisoformat(str(event["measured_at"]).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False, f"'measured_at' is not a valid ISO timestamp: {event['measured_at']!r}"

    return True, ""


def _parse_utc(ts: str) -> datetime:
    """Parse an ISO timestamp string into a UTC-aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Redis connection with retry
# ---------------------------------------------------------------------------

def _connect_redis() -> redis.Redis:
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
            log.info("Connected to Redis at %s:%s", REDIS_HOST, REDIS_PORT)
            return client
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning("Redis connect failed (%s). Retrying in %.0f s…", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)


# ---------------------------------------------------------------------------
# Cache update with staleness guard
# ---------------------------------------------------------------------------

def _update_cache(client: redis.Redis, event: dict[str, Any]) -> None:
    """
    Update ``patient:<id>:vitals:latest`` with the event's readings.

    Uses a Redis pipeline to:
      1. Read the existing ``measured_at`` from the hash.
      2. Compare it to the incoming event's ``measured_at``.
      3. Write only if the incoming event is newer (or there is no existing entry).

    Because pipeline.execute() is not atomic against concurrent writers,
    a tiny race window exists in a multi-process setup.  For this prototype
    with a single cache subscriber, this is acceptable.  Use a Lua script
    for strict atomicity if needed.
    """
    patient_id = int(event["patient_id"])
    key = _cache_key(patient_id)

    incoming_ts_str = str(event["measured_at"])
    try:
        incoming_ts = _parse_utc(incoming_ts_str)
    except ValueError:
        log.warning("Cannot parse measured_at='%s', skipping cache.", incoming_ts_str)
        return

    # Read existing timestamp (may be None if key doesn't exist yet)
    existing_ts_str: str | None = client.hget(key, "measured_at")

    if existing_ts_str is not None:
        try:
            existing_ts = _parse_utc(existing_ts_str)
            if incoming_ts <= existing_ts:
                log.debug(
                    "Stale event for patient=%s (incoming=%s <= stored=%s) — skipped.",
                    patient_id, incoming_ts_str, existing_ts_str,
                )
                return
        except ValueError:
            # Corrupt stored value — overwrite it
            log.warning("Corrupt cached timestamp for patient=%s — overwriting.", patient_id)

    cached_at = datetime.now(timezone.utc).isoformat()

    # Write the new hash atomically (pipeline batches the commands)
    pipe = client.pipeline()
    pipe.hset(key, mapping={
        "pedometer":          int(event["pedometer"]),
        "sleep_minutes":      int(event["sleep_minutes"]),
        "screentime_minutes": int(event["screentime_minutes"]),
        "heartrate":          int(event["heartrate"]),
        "measured_at":        incoming_ts_str,
        "event_id":           str(event["event_id"]),
        "cached_at":          cached_at,
    })
    if CACHE_TTL > 0:
        pipe.expire(key, CACHE_TTL)
    pipe.execute()

    log.info(
        "Cache updated — patient=%s  hr=%s bpm  sleep=%s min  event_id=%s",
        patient_id,
        event["heartrate"],
        event["sleep_minutes"],
        str(event["event_id"])[:8],
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run() -> None:
    log.info(
        "Redis cache subscriber starting — channel=%s  ttl=%ss",
        REDIS_CHANNEL, CACHE_TTL if CACHE_TTL > 0 else "∞",
    )

    client = _connect_redis()
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(REDIS_CHANNEL)
    log.info("Subscribed to channel '%s'", REDIS_CHANNEL)

    while True:
        try:
            message = pubsub.get_message(timeout=1.0)
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning("Redis error: %s — reconnecting…", exc)
            try:
                pubsub.close()
            except Exception:
                pass
            client = _connect_redis()
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(REDIS_CHANNEL)
            continue

        if message is None:
            continue

        raw = message.get("data", "")
        if not isinstance(raw, str):
            continue

        try:
            event: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("Non-JSON message received: %s", exc)
            continue

        ok, reason = _validate_event(event)
        if not ok:
            log.warning("Rejected invalid event: %s", reason)
            continue

        try:
            _update_cache(client, event)
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            log.warning("Redis write failed: %s — reconnecting…", exc)
            client = _connect_redis()
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(REDIS_CHANNEL)
        except Exception as exc:
            log.error("Unexpected error updating cache: %s", type(exc).__name__)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Redis cache subscriber stopped by user.")
