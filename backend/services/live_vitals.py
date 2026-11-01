"""Live wearable reads: Redis first, PostgreSQL only as a fallback."""

from __future__ import annotations

import json
import logging
import os

from db import get_db_connection
from services.wearables import key_latest, key_recent

log = logging.getLogger(__name__)
_client = None


def redis_client():
    global _client
    if _client is None:
        import redis
        _client = redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"), port=int(os.getenv("REDIS_PORT", "6379")),
                              decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
    return _client


def _num(v, cast=float):
    return None if v in (None, "") else cast(v)


def _from_cache(d: dict) -> dict:
    return {
        "measured_at": d.get("measured_at"), "heartrate": _num(d.get("heartrate"), int),
        "heartrate_ewma": _num(d.get("heartrate_ewma")), "pedometer": _num(d.get("pedometer"), int),
        "pedometer_ewma": _num(d.get("pedometer_ewma")), "sleep_minutes": _num(d.get("sleep_minutes"), int),
        "screentime_minutes": _num(d.get("screentime_minutes"), int),
        "is_simulated": str(d.get("is_simulated")) in ("1", "True", "true"),
        "quality_flags": [f for f in str(d.get("quality_flags", "")).split(",") if f], "source": "redis",
    }


def _from_row(row: dict) -> dict:
    return {
        "measured_at": row["timestamp"].isoformat() + "+00:00" if row["timestamp"] else None,
        "heartrate": row["heartrate"], "heartrate_ewma": row["heartrate_ewma"], "pedometer": row["pedometer"],
        "pedometer_ewma": row["pedometer_ewma"], "sleep_minutes": row["sleep_minutes"],
        "screentime_minutes": row["screentime_minutes"], "is_simulated": bool(row["is_simulated"]),
        "quality_flags": list(row["quality_flags"] or []), "source": "postgres",
    }


_COLS = ("timestamp, heartrate, heartrate_ewma, pedometer, pedometer_ewma, sleep_minutes, screentime_minutes, "
         "is_simulated, quality_flags")


def get_latest(patient_id: int) -> dict | None:
    try:
        d = redis_client().hgetall(key_latest(patient_id))
        if d:
            return _from_cache(d)
    except Exception as exc:
        log.warning("Redis unavailable for live vitals (%s); falling back to PostgreSQL", type(exc).__name__)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLS} FROM wearable_data WHERE patient_id = %s ORDER BY timestamp DESC LIMIT 1",
                    (patient_id,))
        row = cur.fetchone()
        return _from_row(row) if row else None
    finally:
        conn.close()


def get_recent(patient_id: int, n: int = 20) -> list[dict]:
    """Newest first."""
    n = max(1, min(int(n), 200))
    try:
        items = redis_client().lrange(key_recent(patient_id), 0, n - 1)
        if items:
            return [_from_cache(json.loads(i)) for i in items]
    except Exception as exc:
        log.warning("Redis unavailable for recent vitals (%s); falling back to PostgreSQL", type(exc).__name__)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLS} FROM wearable_data WHERE patient_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (patient_id, n))
        return [_from_row(r) for r in cur.fetchall()]
    finally:
        conn.close()
