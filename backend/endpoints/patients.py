"""Patient-facing data: self-reports (check-in, journal), caretaker observations, medications,
patient directory, and live/historical wearable summaries. All routes enforce ownership."""

import logging
from datetime import date

from flask import jsonify, request

from db import get_db_connection
from endpoints.authz import current_user, resolve_patient_id, role_required
from services import live_vitals
from services.graph.outbox import enqueue

log = logging.getLogger(__name__)


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _number(data, key, lo, hi, required=False):
    v = data.get(key)
    if v is None:
        return None, (f"{key} is required" if required else None)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        return None, f"{key} must be a number between {lo} and {hi}"
    return float(v), None


@role_required("patient")
def submit_checkin():
    data, (patient_id, _) = _body(), current_user()
    values, errors = {}, []
    for key, lo, hi in (("mood", 1, 5), ("stress", 0, 10), ("sleep_hours", 0, 24), ("energy", 0, 10)):
        values[key], err = _number(data, key, lo, hi)
        if err:
            errors.append(err)
    effects = data.get("side_effects", [])
    if not isinstance(effects, list) or len(effects) > 20 or not all(isinstance(e, str) and 0 < len(e) <= 64 for e in effects):
        errors.append("side_effects must be a list of up to 20 short strings")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO patient_checkins (patient_id, mood, stress, sleep_hours, energy, side_effects) "
                    "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                    (patient_id, values["mood"], values["stress"], values["sleep_hours"], values["energy"], effects))
        row_id = cur.fetchone()["id"]

        # Threshold-driven clinical alerts for doctors and caretakers
        from endpoints.alerts import record_alert
        if values.get("stress", 0) >= 8 or values.get("mood", 5) <= 2:
            record_alert(
                cur, patient_id, "severe_distress", "high",
                f"Patient reported high distress: stress {values.get('stress', 0):.0f}/10, mood {values.get('mood', 5):.0f}/5.",
                source="checkin"
            )
        if effects:
            record_alert(
                cur, patient_id, "side_effects", "medium",
                f"Patient reported medication side effects: {', '.join(effects)}.",
                source="checkin"
            )

        conn.commit()
        return jsonify({"message": "Check-in saved", "id": row_id}), 201
    except Exception:
        conn.rollback()
        log.exception("check-in failed")
        return jsonify({"error": "Could not save the check-in"}), 500
    finally:
        conn.close()


@role_required("patient")
def submit_journal():
    data, (patient_id, _) = _body(), current_user()
    entry = data.get("entry")
    if not isinstance(entry, str) or not entry.strip():
        return jsonify({"error": "entry is required"}), 400
    if len(entry) > 10_000:
        return jsonify({"error": "entry must be at most 10000 characters"}), 400
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO journal_entries (patient_id, entry) VALUES (%s,%s) RETURNING id",
                    (patient_id, entry.strip()))
        row_id = cur.fetchone()["id"]
        enqueue(cur, "journal", row_id, patient_id)
        conn.commit()
        return jsonify({"message": "Journal entry saved", "id": row_id}), 201
    except Exception:
        conn.rollback()
        log.exception("journal failed")
        return jsonify({"error": "Could not save the journal entry"}), 500
    finally:
        conn.close()


@role_required("patient")
def get_my_journals():
    patient_id, _ = current_user()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT j.id, j.patient_id, j.entry, j.created_at, j.doctor_reply, j.doctor_reply_at, "
            "d.name AS doctor_name "
            "FROM journal_entries j "
            "LEFT JOIN doctors d ON j.replied_by_doctor_id = d.id "
            "WHERE j.patient_id = %s "
            "ORDER BY j.created_at DESC, j.id DESC LIMIT 50",
            (patient_id,)
        )
        journals = cur.fetchall()
        for j in journals:
            if j.get("created_at"):
                j["created_at"] = j["created_at"].isoformat()
            if j.get("doctor_reply_at"):
                j["doctor_reply_at"] = j["doctor_reply_at"].isoformat()
        return jsonify({"journals": journals}), 200
    except Exception:
        log.exception("get_my_journals failed")
        return jsonify({"error": "Could not load journals"}), 500
    finally:
        conn.close()


@role_required("doctor", "caretaker")
def get_patient_journals(patient_id):
    patient_id, error = resolve_patient_id(patient_id, strict=True)
    if error:
        return error
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT j.id, j.patient_id, j.entry, j.created_at, j.doctor_reply, j.doctor_reply_at, "
            "d.name AS doctor_name "
            "FROM journal_entries j "
            "LEFT JOIN doctors d ON j.replied_by_doctor_id = d.id "
            "WHERE j.patient_id = %s "
            "ORDER BY j.created_at DESC, j.id DESC LIMIT 50",
            (patient_id,)
        )
        journals = cur.fetchall()
        for j in journals:
            if j.get("created_at"):
                j["created_at"] = j["created_at"].isoformat()
            if j.get("doctor_reply_at"):
                j["doctor_reply_at"] = j["doctor_reply_at"].isoformat()
        return jsonify({"journals": journals}), 200
    except Exception:
        log.exception("get_patient_journals failed")
        return jsonify({"error": "Could not load journals"}), 500
    finally:
        conn.close()


@role_required("caretaker")
def submit_observation():
    data = _body()
    patient_id, error = resolve_patient_id(data.get("patient_id"))
    if error:
        return error
    caretaker_id, _ = current_user()
    flags = {k: data.get(k, False) for k in ("did_not_sleep", "restless", "seems_better")}
    confirmed = data.get("medication_confirmed")
    if not all(isinstance(v, bool) for v in flags.values()) or not (confirmed is None or isinstance(confirmed, bool)):
        return jsonify({"error": "observation flags must be booleans"}), 400
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO caretaker_observations (patient_id, caretaker_id, did_not_sleep, restless, "
                    "seems_better, medication_confirmed) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                    (patient_id, caretaker_id, flags["did_not_sleep"], flags["restless"], flags["seems_better"], confirmed))
        row_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({"message": "Observation saved", "id": row_id}), 201
    except Exception:
        conn.rollback()
        log.exception("observation failed")
        return jsonify({"error": "Could not save the observation"}), 500
    finally:
        conn.close()


@role_required("doctor")
def add_medication():
    data = _body()
    patient_id, error = resolve_patient_id(data.get("patient_id"))
    if error:
        return error
    name, mtype, duration = data.get("name"), data.get("type"), data.get("duration")
    if not isinstance(name, str) or not name.strip() or not isinstance(mtype, str) or not mtype.strip() \
            or isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        return jsonify({"error": "name, type and a positive integer duration (days) are required"}), 400
    doctor_id, _ = current_user()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO medications (name, type, duration, patient_id, prescribed_by) VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT (patient_id, name) DO UPDATE SET type=EXCLUDED.type, duration=EXCLUDED.duration "
                    "RETURNING id", (name.strip(), mtype.strip(), duration, patient_id, doctor_id))
        row_id = cur.fetchone()["id"]
        enqueue(cur, "medication", row_id, patient_id)
        conn.commit()
        return jsonify({"message": "Medication recorded", "id": row_id}), 201
    except Exception:
        conn.rollback()
        log.exception("add medication failed")
        return jsonify({"error": "Could not record the medication"}), 500
    finally:
        conn.close()


@role_required("patient", "doctor", "caretaker")
def list_patients():
    user_id, role = current_user()
    column = {"patient": "id", "doctor": "doctor_id", "caretaker": "caretaker_id"}[role]
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT p.id, p.name, p.username,
                   (SELECT count(*) FROM wearable_anomalies a WHERE a.patient_id = p.id
                      AND a.day >= (now() AT TIME ZONE 'utc')::date - 7) AS recent_anomalies,
                   (SELECT max(timestamp) FROM wearable_data w WHERE w.patient_id = p.id) AS last_reading
                FROM patients p WHERE p.{column} = %s ORDER BY p.name, p.id""", (user_id,))
        rows = cur.fetchall()
        for r in rows:
            r["last_reading"] = r["last_reading"].isoformat() if r["last_reading"] else None
        return jsonify({"patients": rows}), 200
    finally:
        conn.close()


@role_required("patient", "doctor", "caretaker")
def patient_summary(patient_id):
    patient_id, error = resolve_patient_id(patient_id, strict=True)
    if error:
        return error
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM patients WHERE id = %s", (patient_id,))
        patient = cur.fetchone()
        cur.execute("SELECT * FROM (SELECT day, sample_count, steps_total, sleep_minutes, screentime_minutes, hr_mean, "
                    "hr_mean_ewma, sleep_ewma, is_simulated FROM wearable_daily WHERE patient_id = %s "
                    "ORDER BY day DESC LIMIT 7) t ORDER BY day ASC", (patient_id,))
        daily = cur.fetchall()
        for d in daily:
            d["day"] = d["day"].isoformat()
        cur.execute("SELECT day, signal, direction, severity, observed, baseline, is_simulated FROM wearable_anomalies "
                    "WHERE patient_id = %s ORDER BY day DESC, id DESC LIMIT 10", (patient_id,))
        anomalies = cur.fetchall()
        for a in anomalies:
            a["day"] = a["day"].isoformat()
        cur.execute("SELECT count(*) AS n FROM medications WHERE patient_id = %s", (patient_id,))
        meds = cur.fetchone()["n"]

        cur.execute("SELECT mood, stress, sleep_hours, energy, side_effects, created_at FROM patient_checkins "
                    "WHERE patient_id = %s ORDER BY id DESC LIMIT 7", (patient_id,))
        checkins = cur.fetchall()
        for c in checkins:
            if c.get("created_at"):
                c["created_at"] = c["created_at"].isoformat()

        cur.execute("SELECT count(*) AS total, count(*) FILTER (WHERE medication_confirmed = true) AS confirmed "
                    "FROM caretaker_observations WHERE patient_id = %s", (patient_id,))
        obs = cur.fetchone()
        adherence_pct = round(100.0 * obs["confirmed"] / obs["total"]) if (obs and obs["total"] > 0) else None

        valid_moods = [c["mood"] for c in checkins if c.get("mood") is not None]
        mood_avg = round(sum(valid_moods) / len(valid_moods), 1) if valid_moods else None

        valid_daily_sleep = [d["sleep_minutes"] for d in daily if d.get("sleep_minutes") is not None]
        wearable_sleep_avg = round(sum(valid_daily_sleep) / (60.0 * len(valid_daily_sleep)), 1) if valid_daily_sleep else None

        valid_steps = [d["steps_total"] for d in daily if d.get("steps_total") is not None]
        steps_avg = round(sum(valid_steps) / len(valid_steps)) if valid_steps else None
    finally:
        conn.close()
    return jsonify({
        "patient": patient,
        "daily": daily,
        "anomalies": anomalies,
        "medication_count": meds,
        "checkins": checkins,
        "mood_avg": mood_avg,
        "adherence_pct": adherence_pct,
        "wearable_sleep_avg": wearable_sleep_avg,
        "steps_avg": steps_avg,
        "live": live_vitals.get_latest(patient_id),
    }), 200


@role_required("patient", "doctor", "caretaker")
def live_vitals_route(patient_id):
    patient_id, error = resolve_patient_id(patient_id, strict=True)
    if error:
        return error
    try:
        n = int(request.args.get("recent", 20))
    except ValueError:
        n = 20
    return jsonify({"latest": live_vitals.get_latest(patient_id), "recent": live_vitals.get_recent(patient_id, n)}), 200
