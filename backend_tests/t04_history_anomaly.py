"""4. Historical data retrieval and anomaly detection."""

import uuid
from datetime import datetime, timedelta, timezone

from .framework import check, world


def seed_history(conn, patient_id, days=20, anomaly_sleep=None, samples=24, simulated=True):
    """Insert ``days`` complete UTC days ending yesterday (newest day gets ``anomaly_sleep`` if given).
    Rows are inserted newest-first on purpose, so ordering bugs would show."""
    cur = conn.cursor()
    today = datetime.now(timezone.utc).date()
    for offset in range(1, days + 1):                                   # newest first
        day = today - timedelta(days=offset)
        sleep = 410 + (offset * 7) % 40
        if offset == 1 and anomaly_sleep is not None:
            sleep = anomaly_sleep
        for s in range(samples):
            ts = datetime(day.year, day.month, day.day, 0, 0) + timedelta(minutes=s * 30)
            cur.execute(
                "INSERT INTO wearable_data (patient_id, timestamp, pedometer, sleep_minutes, screentime_minutes, heartrate,"
                " event_id, is_simulated, source) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (patient_id, ts, 400, sleep, 120 + offset % 5, 70 + (s % 4), str(uuid.uuid4()), simulated,
                 "simulator" if simulated else "device"))
    conn.commit()


@check("4. History / anomalies")
def anomaly_scoring_uses_only_prior_days_and_requires_enough_history():
    from services.wearable_analytics import MIN_HISTORY_DAYS, evaluate_day
    history = [420, 415, 430, 425, 418, 422, 428, 419, 424, 421]
    hit = evaluate_day(history, 150.0, "low", 20.0, 0.2)
    assert hit and hit["direction"] == "low" and hit["severity"] == "high", hit
    assert evaluate_day(history, 415.0, "low", 20.0, 0.2) is None, "a normal day must not be flagged"
    assert evaluate_day(history, 600.0, "low", 20.0, 0.2) is None, "only the concerning direction is flagged"
    assert evaluate_day(history[:MIN_HISTORY_DAYS - 1], 150.0, "low", 20.0, 0.2) is None, "insufficient history"
    assert evaluate_day([None] * 10, 150.0, "low", 20.0, 0.2) is None, "NULL-only history"


@check("4. History / anomalies", needs=("postgres",))
def rollup_and_detection_flag_a_real_drop_in_sleep_from_the_patients_own_history():
    from db import get_db_connection
    from services import wearable_analytics as wa
    with world() as (w, _):
        conn = get_db_connection()
        try:
            seed_history(conn, w.patient_a, days=20, anomaly_sleep=150)
            seed_history(conn, w.patient_b, days=20)                           # same patient shape, no anomaly
            for pid in (w.patient_a, w.patient_b):
                wa.rollup_patient(conn, pid)
            found_a = wa.detect_anomalies(conn, w.patient_a, days_back=3)
            found_b = wa.detect_anomalies(conn, w.patient_b, days_back=3)
            assert [f["signal"] for f in found_a] == ["sleep"], found_a
            assert found_a[0]["history_days"] >= 7 and found_a[0]["day"] == datetime.now(timezone.utc).date() - timedelta(days=1)
            assert found_b == [], "a patient with a normal history must not be flagged"
            cur = conn.cursor()
            cur.execute("SELECT is_simulated, ewma_config_version FROM wearable_anomalies WHERE patient_id=%s", (w.patient_a,))
            assert dict(cur.fetchone()) == {"is_simulated": True, "ewma_config_version": 1}
            cur.execute("SELECT count(*) n FROM wearable_anomalies WHERE patient_id=%s", (w.patient_b,))
            assert cur.fetchone()["n"] == 0
        finally:
            conn.close()


@check("4. History / anomalies", needs=("postgres",))
def daily_rollups_are_chronological_with_a_running_ewma():
    from db import get_db_connection
    from services import wearable_analytics as wa
    with world() as (w, _):
        conn = get_db_connection()
        try:
            seed_history(conn, w.patient_a, days=12)
            wa.rollup_patient(conn, w.patient_a)
            cur = conn.cursor()
            cur.execute("SELECT day, sample_count, sleep_minutes, sleep_ewma FROM wearable_daily WHERE patient_id=%s ORDER BY day", (w.patient_a,))
            rows = cur.fetchall()
            assert len(rows) == 12 and all(r["sample_count"] == 24 for r in rows)
            assert rows[0]["sleep_ewma"] == rows[0]["sleep_minutes"], "EWMA is seeded with the first (oldest) day"
            expected = rows[0]["sleep_minutes"]
            for r in rows[1:]:
                expected += 0.2 * (r["sleep_minutes"] - expected)
                assert abs(r["sleep_ewma"] - expected) < 1e-6, "EWMA must run oldest -> newest"
        finally:
            conn.close()


@check("4. History / anomalies", needs=("postgres",))
def patient_context_uses_the_newest_days_in_order_and_labels_synthetic_data():
    from db import get_db_connection
    from services import wearable_analytics as wa
    from services.context import build_context
    with world() as (w, _):
        conn = get_db_connection()
        try:
            seed_history(conn, w.patient_a, days=20, anomaly_sleep=150)
            wa.rollup_patient(conn, w.patient_a)
            wa.detect_anomalies(conn, w.patient_a, days_back=3)
        finally:
            conn.close()
        text = build_context(w.patient_a, "staff").text()
        today = datetime.now(timezone.utc).date()
        newest, oldest_hidden = today - timedelta(days=1), today - timedelta(days=20)
        assert str(newest) in text and str(oldest_hidden) not in text, "the newest 7 days must be shown, not the oldest"
        positions = [text.index(str(today - timedelta(days=k))) for k in range(7, 0, -1)]
        assert positions == sorted(positions), "days must read oldest -> newest"
        assert "[SIMULATED]" in text and "Detected changes" in text and "sleep low" in text


@check("4. History / anomalies", needs=("postgres",))
def context_is_refreshed_when_source_data_changes_not_served_stale():
    from db import get_db_connection
    from services.context import get_latest_patient_context
    with world() as (w, client):
        first = get_latest_patient_context(w.patient_a)
        assert "None." in first
        r = client.post("/api/doctor_notes", json={"patient_id": w.patient_a, "note": "Marker note for staleness check."},
                        headers={"Authorization": f"Bearer {w.tokens['doctor']}"})
        assert r.status_code == 201
        second = get_latest_patient_context(w.patient_a)
        assert "Marker note for staleness check." in second, "a new note must invalidate the stored context"
        assert get_latest_patient_context(w.patient_a) == second
