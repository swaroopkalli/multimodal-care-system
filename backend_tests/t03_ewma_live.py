"""3. EWMA processing and live-vitals retrieval."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from .framework import check, world
from .t02_ingestion import make_event, redis_client


@check("3. EWMA / live vitals")
def time_aware_alpha_gives_the_same_smoothing_for_irregular_sampling():
    from services.ewma import EwmaState, load_config, step, time_aware_alpha
    cfg = load_config()
    sig = cfg.heartrate
    assert abs(time_aware_alpha(sig.tau_seconds, sig.tau_seconds) - (1 - 2.718281828 ** -1)) < 1e-6
    # two 30 s steps == one 60 s step toward the same target
    s = EwmaState(70.0, sig.min_dev, 0.0, 10)
    a, _, _ = step(s, 80.0, 30.0, sig, cfg)
    b, _, _ = step(EwmaState(70.0, sig.min_dev, 0.0, 10), 80.0, 60.0, sig, cfg)
    assert a.value < b.value < 80.0 and a.value > 70.0


@check("3. EWMA / live vitals")
def ewma_series_skips_nulls_and_keeps_order():
    from services.ewma import daily_ewma, ewma_series
    out = ewma_series([None, 10, None, 20, 30], 0.5)
    assert out == [None, 10.0, None, 15.0, 22.5], out
    from datetime import date
    d = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 6)]
    assert daily_ewma(d, [10, 20, 20], 0.2)[2] > ewma_series([10, 20, 20], 0.2)[2], "a 4-day gap must decay history faster"
    from services.context import calculate_ewma
    assert calculate_ewma([400, None, 410]) == [400.0, None, 402.0]     # previously raised TypeError


@check("3. EWMA / live vitals")
def gaps_out_of_order_outliers_and_level_shifts_are_handled():
    from services.ewma import EwmaState, load_config, step
    cfg, sig = load_config(), load_config().heartrate
    state, flags_seen = None, []
    for i in range(12):
        state, _, f = step(state, 72 + (i % 3), i * 5.0, sig, cfg)
    base = state.value
    state, sm, f = step(state, 200, 70.0, sig, cfg)
    assert "outlier" in f and abs(state.value - base) < 1e-9 and sm == base, "outlier must not move the state"
    _, sm, f = step(state, 72, 50.0, sig, cfg)                                   # older than last accepted sample (55 s)
    assert f == ["out_of_order"] and sm is None
    new, _, f = step(state, 75, 70.0 + cfg.max_gap_seconds + 1, sig, cfg)
    assert "reseeded" in f and new.value == 75
    shifted, saw_shift = state, False
    for k in range(cfg.outlier_reseed_after + 1):
        shifted, _, f = step(shifted, 120, 80.0 + k * 5, sig, cfg)
        saw_shift = saw_shift or "level_shift" in f
    assert saw_shift and abs(shifted.value - 120) < 1, "a sustained shift must be accepted as the new level"


@check("3. EWMA / live vitals", needs=("postgres", "redis"))
def live_vitals_come_from_redis_and_fall_back_to_postgres():
    from db import get_db_connection
    from services import live_vitals, wearables
    r = redis_client()
    with world() as (w, _):
        conn = get_db_connection()
        try:
            base = datetime.now(timezone.utc) - timedelta(minutes=10)
            for i in range(6):
                wearables.process_event(conn, r, make_event(w.patient_a, i, 70 + i, base=base))
            latest = live_vitals.get_latest(w.patient_a)
            assert latest["source"] == "redis" and latest["heartrate"] == 75 and latest["heartrate_ewma"] is not None
            assert latest["is_simulated"] is True
            recent = live_vitals.get_recent(w.patient_a, 4)
            assert [x["heartrate"] for x in recent] == [75, 74, 73, 72], "newest first"
            for k in r.scan_iter(f"patient:{w.patient_a}:*"):
                r.delete(k)
            fallback = live_vitals.get_latest(w.patient_a)
            assert fallback["source"] == "postgres" and fallback["heartrate"] == 75
        finally:
            conn.close()


@check("3. EWMA / live vitals", needs=("postgres", "redis"))
def lost_redis_state_is_rebuilt_from_postgres_so_smoothing_continues():
    from db import get_db_connection
    from services import wearables
    r = redis_client()
    with world() as (w, _):
        conn = get_db_connection()
        try:
            base = datetime.now(timezone.utc) - timedelta(minutes=10)
            for i in range(8):
                wearables.process_event(conn, r, make_event(w.patient_a, i, 80, base=base))
            for k in r.scan_iter(f"patient:{w.patient_a}:ewma:*"):
                r.delete(k)
            out = wearables.process_event(conn, r, make_event(w.patient_a, 9, 82, base=base))
            cur = conn.cursor()
            cur.execute("SELECT heartrate_ewma FROM wearable_data WHERE patient_id=%s ORDER BY timestamp DESC LIMIT 1", (w.patient_a,))
            assert 79 < cur.fetchone()["heartrate_ewma"] < 83, "state should continue from ~80, not restart or jump"
        finally:
            conn.close()
