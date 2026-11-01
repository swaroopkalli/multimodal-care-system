"""2. Wearable ingestion: validation, Redis Stream publishing/consumption, PostgreSQL persistence."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from .framework import check, world


def make_event(patient_id, i=0, hr=72, base=None, **over):
    base = base or (datetime.now(timezone.utc) - timedelta(minutes=30))
    e = {"event_id": str(uuid.uuid4()), "patient_id": patient_id, "sequence": i,
         "measured_at": (base + timedelta(seconds=5 * i)).isoformat(), "simulation": True, "source": "simulator",
         "pedometer": 300, "sleep_minutes": 420, "screentime_minutes": 100, "heartrate": hr}
    e.update(over)
    return e


def redis_client():
    import redis
    return redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"), port=int(os.getenv("REDIS_PORT", "6379")),
                       decode_responses=True)


@check("2. Wearable ingestion")
def validation_accepts_a_well_formed_event_and_normalises_to_utc():
    from services.wearables import normalize_event
    ev = normalize_event(make_event(1, measured_at="2026-01-01T12:00:00+05:30"), now=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert ev.measured_at.utcoffset() == timedelta(0) and ev.measured_at.hour == 6 and ev.measured_at.minute == 30
    assert ev.is_simulated is True and ev.source == "simulator"


@check("2. Wearable ingestion")
def validation_rejects_malformed_events():
    from services.wearables import ValidationError, normalize_event
    bad = {
        "missing field": {k: v for k, v in make_event(1).items() if k != "heartrate"},
        "negative hr": make_event(1, heartrate=-5),
        "implausible hr": make_event(1, heartrate=400),
        "string hr": make_event(1, heartrate="lots"),
        "fractional steps": make_event(1, pedometer=10.5),
        "naive timestamp": make_event(1, measured_at="2026-01-01T12:00:00"),
        "bad timestamp": make_event(1, measured_at="yesterday"),
        "future timestamp": make_event(1, measured_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()),
        "bad uuid": make_event(1, event_id="abc"),
        "simulation not bool": make_event(1, simulation="yes"),
        "source/flag mismatch": make_event(1, simulation=False, source="simulator"),
        "not an object": [1, 2, 3],
    }
    for label, event in bad.items():
        try:
            normalize_event(event)
        except ValidationError:
            continue
        raise AssertionError(f"accepted invalid event: {label}")


@check("2. Wearable ingestion", needs=("postgres", "redis"))
def stream_to_postgres_and_redis_round_trip_with_dedup_and_dead_letter():
    from db import get_db_connection
    from services import wearables
    r = redis_client()
    stream, group = f"wearable:test:{uuid.uuid4().hex[:8]}", "bt"
    with world() as (w, _):
        conn = get_db_connection()
        try:
            wearables.ensure_group(r, stream, group)
            events = [make_event(w.patient_a, i, 70 + i % 3) for i in range(8)]
            for e in events:
                r.xadd(stream, {"data": json.dumps(e)})
            r.xadd(stream, {"data": json.dumps(events[2])})                          # duplicate event_id
            r.xadd(stream, {"data": json.dumps(make_event(w.patient_a, 9, heartrate=-1))})  # invalid
            r.xadd(stream, {"data": "{not json"})                                    # garbage
            r.xadd(stream, {"data": json.dumps(make_event(99999999, 10))})           # unknown patient
            dead_before = r.xlen(wearables.DEAD_STREAM)
            stats = wearables.consume_batch(r, conn, stream, group, "c1", count=100, block_ms=200)
            assert stats == {"stored": 8, "duplicate": 1, "rejected": 3}, stats
            assert r.xlen(wearables.DEAD_STREAM) == dead_before + 3, "rejected events must be dead-lettered"
            assert r.xpending(stream, group)["pending"] == 0, "everything should be acknowledged"

            cur = conn.cursor()
            cur.execute("SELECT count(*) n, bool_and(is_simulated) sim, count(heartrate_ewma) sm FROM wearable_data WHERE patient_id=%s",
                        (w.patient_a,))
            row = cur.fetchone()
            assert row["n"] == 8 and row["sim"] is True and row["sm"] == 8, dict(row)
            latest = r.hgetall(wearables.key_latest(w.patient_a))
            assert latest["event_id"] == events[-1]["event_id"] and latest["is_simulated"] == "1"
            assert r.llen(wearables.key_recent(w.patient_a)) == 8
        finally:
            conn.close()
            r.delete(stream)


@check("2. Wearable ingestion", needs=("postgres", "redis"))
def redelivery_after_a_crash_is_idempotent():
    """PostgreSQL committed but Redis was never updated: redelivery must heal Redis without double-counting."""
    from db import get_db_connection
    from services import wearables
    r = redis_client()
    with world() as (w, _):
        conn = get_db_connection()
        try:
            ev = make_event(w.patient_a, 0, 75)
            assert wearables.process_event(conn, r, ev)["status"] == "stored"
            for k in r.scan_iter(f"patient:{w.patient_a}:*"):
                r.delete(k)                                                         # simulate Redis losing its state
            result = wearables.process_event(conn, r, ev)                           # redelivery
            assert result["status"] == "duplicate" and result["cached"] is True
            assert r.hget(wearables.key_latest(w.patient_a), "event_id") == ev["event_id"]
            cur = conn.cursor()
            cur.execute("SELECT count(*) n FROM wearable_data WHERE patient_id=%s", (w.patient_a,))
            assert cur.fetchone()["n"] == 1
        finally:
            conn.close()


@check("2. Wearable ingestion", needs=("postgres", "redis"))
def device_and_simulated_provenance_are_kept_apart():
    from db import get_db_connection
    from services import wearables
    r = redis_client()
    with world() as (w, _):
        conn = get_db_connection()
        try:
            wearables.process_event(conn, r, make_event(w.patient_a, 0, 70))
            real = make_event(w.patient_a, 1, 71, simulation=False, source="device", device_id="watch-1")
            wearables.process_event(conn, r, real)
            cur = conn.cursor()
            cur.execute("SELECT is_simulated, source FROM wearable_data WHERE patient_id=%s ORDER BY timestamp", (w.patient_a,))
            assert [(x["is_simulated"], x["source"]) for x in cur.fetchall()] == [(True, "simulator"), (False, "device")]
        finally:
            conn.close()
