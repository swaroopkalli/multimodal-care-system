"""Live wearable reads: Redis Stream first, Redis hash/list cache, and PostgreSQL only as a fallback."""

from __future__ import annotations

import json
import logging
import os

from db import get_db_connection
from services.wearables import key_latest, key_recent

log = logging.getLogger(__name__)
_client = None
STREAM = os.getenv("WEARABLE_STREAM", "wearable:events")


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
        "quality_flags": [f for f in str(d.get("quality_flags", "")).split(",") if f],
        "source": "redis_stream",
    }


def _from_stream_event(ev: dict) -> dict:
    return {
        "measured_at": ev.get("measured_at"),
        "heartrate": _num(ev.get("heartrate"), int),
        "heartrate_ewma": _num(ev.get("heartrate_ewma")),
        "pedometer": _num(ev.get("pedometer"), int),
        "pedometer_ewma": _num(ev.get("pedometer_ewma")),
        "sleep_minutes": _num(ev.get("sleep_minutes"), int),
        "screentime_minutes": _num(ev.get("screentime_minutes"), int),
        "is_simulated": bool(ev.get("simulation", True)),
        "quality_flags": list(ev.get("quality_flags") or []),
        "source": "redis_stream",
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
    r = redis_client()
    try:
        # 1. Patient latest cache (updated on each processed stream event)
        d = r.hgetall(key_latest(patient_id))
        if d:
            return _from_cache(d)

        # 2. Redis Stream "wearable:events" direct inspection
        entries = r.xrevrange(STREAM, count=100)
        for _, fmap in entries:
            raw = fmap.get("data")
            if raw:
                try:
                    ev = json.loads(raw)
                    if ev.get("patient_id") == patient_id:
                        return _from_stream_event(ev)
                except Exception:
                    continue

        # 3. If no patient-specific events yet in stream, provide the active stream event
        for _, fmap in entries:
            raw = fmap.get("data")
            if raw:
                try:
                    ev = json.loads(raw)
                    return _from_stream_event(ev)
                except Exception:
                    continue
    except Exception as exc:
        log.warning("Redis stream unavailable for live vitals (%s); falling back to PostgreSQL", type(exc).__name__)

    # 4. Fallback to PostgreSQL only when Redis is unavailable or empty
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
    r = redis_client()
    try:
        # 1. Check patient-specific recent cache in Redis
        items = r.lrange(key_recent(patient_id), 0, n - 1)
        if items:
            return [_from_cache(json.loads(i)) for i in items]

        # 2. Read directly from Redis Stream "wearable:events"
        entries = r.xrevrange(STREAM, count=max(n * 4, 100))
        matching = []
        for _, fmap in entries:
            raw = fmap.get("data")
            if raw:
                try:
                    ev = json.loads(raw)
                    if ev.get("patient_id") == patient_id:
                        matching.append(_from_stream_event(ev))
                        if len(matching) >= n:
                            break
                except Exception:
                    continue
        if matching:
            return matching

        # 3. If no events specifically matching this patient_id, return the latest stream events
        stream_events = []
        for _, fmap in entries:
            raw = fmap.get("data")
            if raw:
                try:
                    ev = json.loads(raw)
                    stream_events.append(_from_stream_event(ev))
                    if len(stream_events) >= n:
                        break
                except Exception:
                    continue
        if stream_events:
            return stream_events
    except Exception as exc:
        log.warning("Redis stream unavailable for recent vitals (%s); falling back to PostgreSQL", type(exc).__name__)

    # 4. Fallback to PostgreSQL
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {_COLS} FROM wearable_data WHERE patient_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (patient_id, n))
        return [_from_row(r) for r in cur.fetchall()]
    finally:
        conn.close()
