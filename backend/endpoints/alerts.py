"""Threshold-driven clinical alerts for doctors and caretakers.

Alerts are automatically triggered by severe distress check-ins, crisis queries,
and wearable biometric anomalies. They are visible in the Doctor and Caretaker
portals for immediate review and acknowledgment.
"""

from __future__ import annotations

import logging
from flask import jsonify, request

from db import get_db_connection
from endpoints.authz import current_user, role_required

log = logging.getLogger(__name__)


def record_alert(cur, patient_id: int, alert_type: str, severity: str, message: str,
                 source: str = "checkin") -> int | None:
    """Insert a clinical alert if a duplicate unacknowledged alert of the same type does not already exist."""
    try:
        cur.execute(
            "SELECT id FROM clinical_alerts "
            "WHERE patient_id = %s AND alert_type = %s AND is_acknowledged = FALSE "
            "AND created_at > CURRENT_TIMESTAMP - INTERVAL '6 hours' LIMIT 1",
            (patient_id, alert_type)
        )
        if cur.fetchone():
            return None

        cur.execute(
            "INSERT INTO clinical_alerts (patient_id, alert_type, severity, message, source) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (patient_id, alert_type, severity, message.strip(), source)
        )
        row = cur.fetchone()
        return row["id"] if row else None
    except Exception:
        log.exception("Failed to record clinical alert for patient %s", patient_id)
        return None


@role_required("doctor", "caretaker")
def list_alerts():
    """List clinical alerts for patients assigned to the authenticated doctor or caretaker."""
    user_id, role = current_user()
    patient_id_filter = request.args.get("patient_id")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if role == "doctor":
            if patient_id_filter:
                cur.execute(
                    "SELECT a.id, a.patient_id, p.name AS patient_name, a.alert_type, a.severity, "
                    "a.message, a.source, a.is_acknowledged, a.acknowledged_at, a.created_at "
                    "FROM clinical_alerts a "
                    "JOIN patients p ON a.patient_id = p.id "
                    "WHERE p.doctor_id = %s AND a.patient_id = %s "
                    "ORDER BY a.is_acknowledged ASC, a.created_at DESC LIMIT 50",
                    (user_id, patient_id_filter)
                )
            else:
                cur.execute(
                    "SELECT a.id, a.patient_id, p.name AS patient_name, a.alert_type, a.severity, "
                    "a.message, a.source, a.is_acknowledged, a.acknowledged_at, a.created_at "
                    "FROM clinical_alerts a "
                    "JOIN patients p ON a.patient_id = p.id "
                    "WHERE p.doctor_id = %s "
                    "ORDER BY a.is_acknowledged ASC, a.created_at DESC LIMIT 50",
                    (user_id,)
                )
        else:
            if patient_id_filter:
                cur.execute(
                    "SELECT a.id, a.patient_id, p.name AS patient_name, a.alert_type, a.severity, "
                    "a.message, a.source, a.is_acknowledged, a.acknowledged_at, a.created_at "
                    "FROM clinical_alerts a "
                    "JOIN patients p ON a.patient_id = p.id "
                    "WHERE p.caretaker_id = %s AND a.patient_id = %s "
                    "ORDER BY a.is_acknowledged ASC, a.created_at DESC LIMIT 50",
                    (user_id, patient_id_filter)
                )
            else:
                cur.execute(
                    "SELECT a.id, a.patient_id, p.name AS patient_name, a.alert_type, a.severity, "
                    "a.message, a.source, a.is_acknowledged, a.acknowledged_at, a.created_at "
                    "FROM clinical_alerts a "
                    "JOIN patients p ON a.patient_id = p.id "
                    "WHERE p.caretaker_id = %s "
                    "ORDER BY a.is_acknowledged ASC, a.created_at DESC LIMIT 50",
                    (user_id,)
                )

        rows = cur.fetchall()
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
            if r.get("acknowledged_at"):
                r["acknowledged_at"] = r["acknowledged_at"].isoformat()
        return jsonify({"alerts": rows}), 200
    except Exception:
        log.exception("list_alerts failed")
        return jsonify({"error": "Could not retrieve alerts"}), 500
    finally:
        conn.close()


@role_required("doctor", "caretaker")
def acknowledge_alert(alert_id: int):
    """Mark a clinical alert as reviewed/acknowledged by doctor or caretaker."""
    user_id, _ = current_user()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE clinical_alerts SET is_acknowledged = TRUE, acknowledged_at = CURRENT_TIMESTAMP, "
            "acknowledged_by = %s WHERE id = %s RETURNING id",
            (user_id, alert_id)
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Alert not found"}), 404
        conn.commit()
        return jsonify({"message": "Alert acknowledged", "id": alert_id}), 200
    except Exception:
        conn.rollback()
        log.exception("acknowledge_alert failed")
        return jsonify({"error": "Could not acknowledge alert"}), 500
    finally:
        conn.close()
