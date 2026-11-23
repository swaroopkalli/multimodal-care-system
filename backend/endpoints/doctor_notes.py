import logging
import re

from flask import jsonify, request

from db import get_db_connection
from endpoints.authz import current_user, resolve_patient_id, role_required
from services import llm
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


@role_required("doctor")
def add_journal_reply():
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    journal_id = data.get("journal_id")
    reply = data.get("reply")
    if not isinstance(journal_id, int):
        return jsonify({"error": "journal_id (integer) is required"}), 400
    if not isinstance(reply, str) or not reply.strip():
        return jsonify({"error": "reply is required"}), 400
    if len(reply) > MAX_NOTE_CHARS:
        return jsonify({"error": f"reply must be at most {MAX_NOTE_CHARS} characters"}), 400

    doctor_id, _ = current_user()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT j.id, j.patient_id FROM journal_entries j "
            "JOIN patients p ON j.patient_id = p.id "
            "WHERE j.id = %s AND p.doctor_id = %s",
            (journal_id, doctor_id)
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Journal entry not found or not assigned to you"}), 404

        cur.execute(
            "UPDATE journal_entries "
            "SET doctor_reply = %s, doctor_reply_at = CURRENT_TIMESTAMP, replied_by_doctor_id = %s "
            "WHERE id = %s RETURNING doctor_reply_at",
            (reply.strip(), doctor_id, journal_id)
        )
        updated = cur.fetchone()
        conn.commit()
        return jsonify({
            "message": "Doctor reply recorded successfully",
            "journal_id": journal_id,
            "doctor_reply": reply.strip(),
            "doctor_reply_at": updated["doctor_reply_at"].isoformat() if updated else None
        }), 200
    except Exception:
        conn.rollback()
        log.exception("add_journal_reply failed")
        return jsonify({"error": "Could not save doctor reply"}), 500
    finally:
        conn.close()


@role_required("doctor")
def add_patient_directive():
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    directive = data.get("directive")
    if not isinstance(directive, str) or not directive.strip():
        return jsonify({"error": "directive is required"}), 400
    if len(directive) > MAX_NOTE_CHARS:
        return jsonify({"error": f"directive must be at most {MAX_NOTE_CHARS} characters"}), 400

    patient_id, error = resolve_patient_id(data.get("patient_id"))
    if error:
        return error
    doctor_id, _ = current_user()

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO patient_care_directives (patient_id, doctor_id, directive, is_active) "
            "VALUES (%s, %s, %s, TRUE) RETURNING id, created_at",
            (patient_id, doctor_id, directive.strip())
        )
        row = cur.fetchone()
        conn.commit()
        return jsonify({
            "message": "Patient directive created successfully",
            "id": row["id"],
            "patient_id": patient_id,
            "directive": directive.strip(),
            "is_active": True,
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None
        }), 201
    except Exception:
        conn.rollback()
        log.exception("add_patient_directive failed")
        return jsonify({"error": "Could not save patient directive"}), 500
    finally:
        conn.close()


@role_required("doctor", "caretaker", "patient")
def get_patient_directives(patient_id):
    patient_id, error = resolve_patient_id(patient_id, strict=True)
    if error:
        return error
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT d.id, d.patient_id, d.doctor_id, doc.name AS doctor_name, d.directive, "
            "d.is_active, d.created_at, d.updated_at "
            "FROM patient_care_directives d "
            "LEFT JOIN doctors doc ON d.doctor_id = doc.id "
            "WHERE d.patient_id = %s "
            "ORDER BY d.created_at DESC, d.id DESC",
            (patient_id,)
        )
        rows = cur.fetchall()
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("updated_at"):
                r["updated_at"] = r["updated_at"].isoformat()
        return jsonify({"directives": rows}), 200
    except Exception:
        log.exception("get_patient_directives failed")
        return jsonify({"error": "Could not load patient directives"}), 500
    finally:
        conn.close()


@role_required("doctor", "caretaker")
def get_patient_chat_history(patient_id):
    patient_id, error = resolve_patient_id(patient_id, strict=True)
    if error:
        return error
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, patient_id, role, query, response, input_handling, created_at "
            "FROM chatbot_logs "
            "WHERE patient_id = %s AND role = 'patient' "
            "ORDER BY created_at DESC, id DESC LIMIT 50",
            (patient_id,)
        )
        logs = cur.fetchall()
        for l in logs:
            if l.get("created_at"):
                iso_time = l["created_at"].isoformat()
                l["created_at"] = iso_time
                l["timestamp"] = iso_time
        return jsonify({"chat_history": logs}), 200
    except Exception:
        log.exception("get_patient_chat_history failed")
        return jsonify({"error": "Could not load patient chat history"}), 500
    finally:
        conn.close()


_CATEGORY_PATTERNS = [
    ("Crisis / Escalation", re.compile(r"\b(suicid|kill myself|end my life|die|harm myself|cant take this)\b", re.I)),
    ("Anxiety / Distress", re.compile(r"\b(anxious|anxiety|panic|overwhelm|scared|cry|stress|hopeless|depressed|lonely|sad)\b", re.I)),
    ("Sleep Disruption", re.compile(r"\b(sleep|insomnia|awake|tired|nightmare|restless|wake up|exhausted)\b", re.I)),
    ("Physical Symptom", re.compile(r"\b(nausea|headache|dizzy|dizziness|stomach|pain|ache|fatigue|shaking|tremor|vomit)\b", re.I)),
    ("Medication Query", re.compile(r"\b(medication|pill|dose|prescription|side effect|effects|skip dose|missed)\b", re.I)),
]


def _classify_chat_turn(query: str, response: str) -> str | None:
    text = f"{query} {response}"
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(text):
            return category
    return None


@role_required("doctor", "caretaker")
def get_patient_chat_digest(patient_id):
    patient_id, error = resolve_patient_id(patient_id, strict=True)
    if error:
        return error
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, patient_id, role, query, response, input_handling, created_at "
            "FROM chatbot_logs "
            "WHERE patient_id = %s AND role = 'patient' "
            "ORDER BY created_at DESC, id DESC LIMIT 40",
            (patient_id,)
        )
        logs = cur.fetchall()
        for l in logs:
            if l.get("created_at"):
                iso_time = l["created_at"].isoformat()
                l["created_at"] = iso_time
                l["timestamp"] = iso_time

        if not logs:
            return jsonify({
                "digest": "No patient chat interactions recorded in the recent period.",
                "flagged_exchanges": [],
                "total_turns": 0
            }), 200

        flagged = []
        for l in logs:
            cat = _classify_chat_turn(l.get("query", ""), l.get("response", ""))
            if cat:
                flagged.append({
                    "id": l["id"],
                    "category": cat,
                    "created_at": l["created_at"],
                    "query": l["query"],
                    "response": l.get("response", "")[:180] + ("..." if len(l.get("response", "")) > 180 else "")
                })

        turns_summary = "\n".join(
            f"[{l['created_at'][:16]}] Patient: {l['query']} | AI: {l['response'][:100]}"
            for l in logs[:15]
        )
        prompt_system = (
            "You are an analytical clinical assistant for a physician reviewing a patient's interactions "
            "with their AI wellness companion. Provide a concise executive clinical digest in EXACTLY 3 "
            "short bullet points:\n"
            "• Primary Concerns & Themes (e.g. sleep issues, daily routine)\n"
            "• Emotional & Distress Trajectory (e.g. anxiety peak, stabilizing)\n"
            "• Reported Physical Symptoms or Medication Inquiries\n"
            "Never provide treatment advice. Be objective, concise, and clinical."
        )
        digest = None
        try:
            result = llm.generate_response(prompt_system, "", f"Patient chat history:\n{turns_summary}")
            if result and result.strip():
                digest = result.strip()
        except Exception:
            log.warning("LLM digest generation failed, using heuristic summary")

        if not digest:
            cats_found = set(f["category"] for f in flagged)
            cat_text = ", ".join(cats_found) if cats_found else "routine wellness check-ins"
            digest = (
                f"• Primary Concerns & Themes: Patient engaged in {len(logs)} chat exchanges focusing on {cat_text}.\n"
                f"• Emotional & Distress Trajectory: {'Distress or anxiety flags identified in recent queries.' if 'Anxiety / Distress' in cats_found else 'Stable conversational tone without acute distress escalations.'}\n"
                f"• Reported Physical Symptoms or Medication: {'Physical symptoms or medication topics noted in conversations.' if ('Physical Symptom' in cats_found or 'Medication Query' in cats_found) else 'No severe physical symptoms reported in chat.'}"
            )

        return jsonify({
            "digest": digest,
            "flagged_exchanges": flagged[:6],
            "total_turns": len(logs)
        }), 200
    except Exception:
        log.exception("get_patient_chat_digest failed")
        return jsonify({"error": "Could not generate patient chat digest"}), 500
    finally:
        conn.close()
