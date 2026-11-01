import logging

from flask import jsonify, request

from db import get_db_connection
from endpoints.authz import current_user, resolve_patient_id, role_required
from services.graph.outbox import enqueue

log = logging.getLogger(__name__)
MAX_NOTE_CHARS = 10_000


@role_required("doctor")
def add_doctor_note():
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    note = data.get("note")
    if not isinstance(note, str) or not note.strip():
        return jsonify({"error": "note is required"}), 400
    if len(note) > MAX_NOTE_CHARS:
        return jsonify({"error": f"note must be at most {MAX_NOTE_CHARS} characters"}), 400
    patient_id, error = resolve_patient_id(data.get("patient_id"))
    if error:
        return error
    doctor_id, _ = current_user()               # the author is always the authenticated doctor

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO doctor_notes (doctor_id, patient_id, note) VALUES (%s,%s,%s) RETURNING id",
                    (doctor_id, patient_id, note.strip()))
        note_id = cur.fetchone()["id"]
        enqueue(cur, "note", note_id, patient_id)
        conn.commit()
        return jsonify({"message": "Doctor note added successfully", "note_id": note_id}), 201
    except Exception:
        conn.rollback()
        log.exception("add_doctor_note failed")
        return jsonify({"error": "Could not save the note"}), 500
    finally:
        conn.close()


@role_required("doctor", "caretaker")
def get_doctor_notes(patient_id):
    patient_id, error = resolve_patient_id(patient_id, strict=True)
    if error:
        return error
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, doctor_id, patient_id, note, created_at FROM doctor_notes WHERE patient_id = %s "
                    "ORDER BY created_at DESC, id DESC", (patient_id,))
        notes = cur.fetchall()
        for n in notes:
            n["created_at"] = n["created_at"].isoformat() if n["created_at"] else None
        return jsonify({"notes": notes}), 200
    except Exception:
        log.exception("get_doctor_notes failed")
        return jsonify({"error": "Could not load notes"}), 500
    finally:
        conn.close()


@role_required("patient", "doctor", "caretaker")
def get_wearable_data(patient_id):
    patient_id, error = resolve_patient_id(patient_id, strict=True)
    if error:
        return error
    try:
        limit = max(1, min(int(request.args.get("limit", 500)), 5000))
    except ValueError:
        limit = 500
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, patient_id, timestamp, pedometer, sleep_minutes, screentime_minutes, heartrate, "
            "heartrate_ewma, pedometer_ewma, is_simulated, quality_flags FROM wearable_data "
            "WHERE patient_id = %s ORDER BY timestamp DESC LIMIT %s", (patient_id, limit))
        data = cur.fetchall()
        for entry in data:
            entry["timestamp"] = entry["timestamp"].isoformat() if entry["timestamp"] else None
        return jsonify({"wearable_data": data}), 200
    except Exception:
        log.exception("get_wearable_data failed")
        return jsonify({"error": "Could not load wearable data"}), 500
    finally:
        conn.close()
