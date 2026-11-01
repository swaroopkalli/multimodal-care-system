"""Uniform wearable ingestion: validate/normalize -> EWMA -> PostgreSQL + Redis.

Used by backend/wearable_ingestion/worker.py (stream consumer) and by tests.
Order of effects per event: PostgreSQL commit first (durable, idempotent on
event_id), then Redis (latest, recent, EWMA state). A crash in between is healed
on redelivery because the Redis update is guarded by the event time.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from services.ewma import EwmaConfig, EwmaState, load_config, step

log = logging.getLogger(__name__)

STREAM = os.getenv("WEARABLE_STREAM", "wearable:events")
DEAD_STREAM = os.getenv("WEARABLE_DEAD_STREAM", "wearable:dead")
LATEST_TTL = int(os.getenv("WEARABLE_LATEST_TTL_SECONDS", "86400"))
RECENT_MAX = int(os.getenv("WEARABLE_RECENT_MAX", "200"))

_INT_FIELDS = ("pedometer", "sleep_minutes", "screentime_minutes", "heartrate")
_DAILY_BOUNDS = {"sleep_minutes": (0, 1440), "screentime_minutes": (0, 1440)}


class ValidationError(ValueError):
    """Permanent rejection of an event (never retried)."""


@dataclass
class NormalizedEvent:
    event_id: str
    patient_id: int
    measured_at: datetime        # timezone-aware UTC
    pedometer: int
    sleep_minutes: int
    screentime_minutes: int
    heartrate: int
    source: str
    device_id: str | None
    is_simulated: bool

    @property
    def ts(self) -> float:
        return self.measured_at.timestamp()


def key_latest(pid: int) -> str: return f"patient:{pid}:vitals:latest"
def key_recent(pid: int) -> str: return f"patient:{pid}:vitals:recent"
def key_state(pid: int, signal: str) -> str: return f"patient:{pid}:ewma:{signal}"


def normalize_event(raw: Any, cfg: EwmaConfig | None = None, now: datetime | None = None) -> NormalizedEvent:
    """Validate and normalise a raw event dict. Raises ValidationError with a reason."""
    cfg = cfg or load_config()
    if not isinstance(raw, dict):
        raise ValidationError("event must be a JSON object")
    missing = [k for k in ("event_id", "patient_id", "measured_at", *_INT_FIELDS) if raw.get(k) is None]
    if missing:
        raise ValidationError(f"missing required fields: {sorted(missing)}")

    import uuid
    try:
        event_id = str(uuid.UUID(str(raw["event_id"])))
    except ValueError:
        raise ValidationError("event_id must be a UUID")

    values: dict[str, int] = {}
    for name in ("patient_id", *_INT_FIELDS):
        v = raw[name]
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ValidationError(f"{name} must be an integer")
        try:
            f = float(v)
        except ValueError:
            raise ValidationError(f"{name} must be an integer")
        if f != int(f):
            raise ValidationError(f"{name} must be a whole number")
        values[name] = int(f)
    if values["patient_id"] <= 0:
        raise ValidationError("patient_id must be positive")

    for name, sig in (("heartrate", cfg.heartrate), ("pedometer", cfg.pedometer)):
        if not sig.lo <= values[name] <= sig.hi:
            raise ValidationError(f"{name} out of plausible range")
    for name, (lo, hi) in _DAILY_BOUNDS.items():
        if not lo <= values[name] <= hi:
            raise ValidationError(f"{name} out of plausible range")

    try:
        measured = datetime.fromisoformat(str(raw["measured_at"]).replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError("measured_at is not a valid ISO-8601 timestamp")
    if measured.tzinfo is None:
        raise ValidationError("measured_at must include a UTC offset")
    measured = measured.astimezone(timezone.utc)
    now = now or datetime.now(timezone.utc)
    if (measured - now).total_seconds() > cfg.future_skew_seconds:
        raise ValidationError("measured_at is in the future")

    simulation = raw.get("simulation")
    if not isinstance(simulation, bool):
        raise ValidationError("simulation must be a boolean")
    source = str(raw.get("source") or ("simulator" if simulation else "device")).lower()
    if source not in ("simulator", "device"):
        raise ValidationError("source must be 'simulator' or 'device'")
    if (source == "simulator") != simulation:
        raise ValidationError("source and simulation flag disagree")

    device = raw.get("device_id")
    return NormalizedEvent(event_id, values["patient_id"], measured, values["pedometer"],
                           values["sleep_minutes"], values["screentime_minutes"], values["heartrate"],
                           source, str(device)[:128] if device else None, simulation)


# --------------------------------------------------------------------- Redis state

def _load_state(r, conn, pid: int, signal: str, column: str) -> EwmaState | None:
    d = r.hgetall(key_state(pid, signal))
    if d:
        try:
            return EwmaState.from_dict(d)
        except (KeyError, ValueError):
            pass
    # Redis lost the state: rebuild an approximation from the last stored smoothed value.
    cur = conn.cursor()
    cur.execute(f"SELECT {column} AS v, timestamp FROM wearable_data "
                f"WHERE patient_id = %s AND {column} IS NOT NULL ORDER BY timestamp DESC LIMIT 1", (pid,))
    row = cur.fetchone()
    if not row:
        return None
    cfg = load_config()
    sig = cfg.heartrate if signal == "hr" else cfg.pedometer
    return EwmaState(float(row["v"]), sig.min_dev, row["timestamp"].replace(tzinfo=timezone.utc).timestamp(),
                     cfg.warmup_samples)


def _write_redis(r, ev: NormalizedEvent, hr_ewma, ped_ewma, hr_state, ped_state, flags: list[str]) -> bool:
    """Idempotent, time-guarded write of latest/recent/state. Returns False if a newer event is already cached."""
    latest_key = key_latest(ev.patient_id)
    stored = r.hget(latest_key, "ts")
    if stored is not None and ev.ts <= float(stored):
        return False
    payload = {
        "event_id": ev.event_id, "measured_at": ev.measured_at.isoformat(), "ts": ev.ts,
        "heartrate": ev.heartrate, "pedometer": ev.pedometer, "sleep_minutes": ev.sleep_minutes,
        "screentime_minutes": ev.screentime_minutes,
        "heartrate_ewma": "" if hr_ewma is None else round(hr_ewma, 3),
        "pedometer_ewma": "" if ped_ewma is None else round(ped_ewma, 3),
        "source": ev.source, "is_simulated": int(ev.is_simulated), "quality_flags": ",".join(flags),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    pipe = r.pipeline()
    pipe.hset(latest_key, mapping=payload)
    if LATEST_TTL > 0:
        pipe.expire(latest_key, LATEST_TTL)
    pipe.lpush(key_recent(ev.patient_id), json.dumps(payload))
    pipe.ltrim(key_recent(ev.patient_id), 0, RECENT_MAX - 1)
    if LATEST_TTL > 0:
        pipe.expire(key_recent(ev.patient_id), LATEST_TTL)
    for signal, state in (("hr", hr_state), ("ped", ped_state)):
        if state is not None:
            pipe.hset(key_state(ev.patient_id, signal), mapping=state.to_dict())
    pipe.execute()
    return True


# ------------------------------------------------------------------- core pipeline

_INSERT_SQL = """
    INSERT INTO wearable_data (patient_id, timestamp, pedometer, sleep_minutes, screentime_minutes, heartrate,
        event_id, is_simulated, source, device_id, received_at, heartrate_ewma, pedometer_ewma,
        ewma_config_version, quality_flags)
    VALUES (%(patient_id)s, %(ts)s, %(pedometer)s, %(sleep)s, %(screen)s, %(hr)s, %(event_id)s,
        %(sim)s, %(source)s, %(device)s, now() AT TIME ZONE 'utc', %(hr_ewma)s, %(ped_ewma)s, %(ver)s, %(flags)s)
    ON CONFLICT (event_id) DO NOTHING RETURNING id
"""


def process_event(conn, r, raw: Any, cfg: EwmaConfig | None = None) -> dict:
    """Process one raw event. Returns {'status': 'stored'|'duplicate', ...}.

    Raises ValidationError for permanent rejections; other exceptions are transient.
    """
    cfg = cfg or load_config()
    ev = normalize_event(raw, cfg)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM patients WHERE id = %s", (ev.patient_id,))
    if cur.fetchone() is None:
        raise ValidationError("unknown patient_id")

    hr_state = _load_state(r, conn, ev.patient_id, "hr", "heartrate_ewma")
    ped_state = _load_state(r, conn, ev.patient_id, "ped", "pedometer_ewma")
    hr_state, hr_ewma, hr_flags = step(hr_state, ev.heartrate, ev.ts, cfg.heartrate, cfg)
    ped_state, ped_ewma, ped_flags = step(ped_state, ev.pedometer, ev.ts, cfg.pedometer, cfg)
    flags = sorted({f for f in hr_flags + ped_flags if f != "warmup" or (hr_state.n < cfg.warmup_samples)})

    try:
        cur.execute(_INSERT_SQL, {
            "patient_id": ev.patient_id, "ts": ev.measured_at.replace(tzinfo=None), "pedometer": ev.pedometer,
            "sleep": ev.sleep_minutes, "screen": ev.screentime_minutes, "hr": ev.heartrate,
            "event_id": ev.event_id, "sim": ev.is_simulated, "source": ev.source, "device": ev.device_id,
            "hr_ewma": hr_ewma, "ped_ewma": ped_ewma, "ver": cfg.version, "flags": flags,
        })
        inserted = cur.fetchone()
        if inserted is None:                       # redelivery: heal Redis from the stored row
            cur.execute("SELECT heartrate_ewma, pedometer_ewma, quality_flags FROM wearable_data WHERE event_id = %s",
                        (ev.event_id,))
            row = cur.fetchone()
            hr_ewma, ped_ewma, flags = row["heartrate_ewma"], row["pedometer_ewma"], list(row["quality_flags"] or [])
            hr_state = ped_state = None
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    cached = _write_redis(r, ev, hr_ewma, ped_ewma, hr_state, ped_state, flags)
    return {"status": "stored" if inserted else "duplicate", "patient_id": ev.patient_id,
            "event_id": ev.event_id, "flags": flags, "cached": cached, "is_simulated": ev.is_simulated}


# --------------------------------------------------------------- stream consumption

def ensure_group(r, stream: str, group: str) -> None:
    import redis
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def consume_batch(r, conn, stream: str, group: str, consumer: str, count: int = 50,
                  block_ms: int = 1000, on_stored=None) -> dict:
    """Read this consumer's pending entries first, then new ones. Returns counters.

    Permanent rejections go to the dead-letter stream and are acknowledged;
    transient failures are left pending and re-raised after the batch so the caller can reconnect.
    """
    stats = {"stored": 0, "duplicate": 0, "rejected": 0}
    transient: Exception | None = None
    for start in ("0", ">"):
        resp = r.xreadgroup(group, consumer, {stream: start}, count=count,
                            block=block_ms if start == ">" else None)
        for _stream, entries in resp or []:
            for entry_id, fields in entries:
                try:
                    result = process_event(conn, r, json.loads(fields.get("data", "null")))
                    stats[result["status"]] += 1
                    if on_stored:
                        on_stored(result)
                except (ValidationError, json.JSONDecodeError) as exc:
                    r.xadd(DEAD_STREAM, {"reason": str(exc)[:200], "entry": entry_id}, maxlen=1000, approximate=True)
                    stats["rejected"] += 1
                except Exception as exc:               # transient: leave pending
                    transient = exc
                    continue
                r.xack(stream, group, entry_id)
    if transient is not None:
        raise transient
    return stats
