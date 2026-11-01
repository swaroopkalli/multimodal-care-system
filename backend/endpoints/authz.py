"""JWT identity helpers and patient-ownership authorization.

Tokens carry ``sub`` = user id (string) and a ``role`` claim. Patient identity is
always taken from the token, never from the request body.
"""

from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from db import get_db_connection

STAFF_ROLES = ("doctor", "caretaker")


def current_user():
    """Return (user_id:int, role:str) for the verified token."""
    return int(get_jwt_identity()), get_jwt().get("role")


def role_required(*roles):
    """Require a valid JWT whose role is one of ``roles``."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            if get_jwt().get("role") not in roles:
                return jsonify({"error": "Forbidden for this role"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def can_access_patient(user_id: int, role: str, patient_id: int) -> bool:
    """Patients: themselves. Doctors/caretakers: only patients assigned to them."""
    if role == "patient":
        return user_id == patient_id
    column = {"doctor": "doctor_id", "caretaker": "caretaker_id"}.get(role)
    if column is None:
        return False
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM patients WHERE id = %s AND {column} = %s", (patient_id, user_id))
        return cur.fetchone() is not None
    finally:
        conn.close()


def resolve_patient_id(requested, strict=False):
    """Return (patient_id, error_response).

    Patients are always resolved to themselves. With ``strict`` (used for ids in the URL) a patient
    naming someone else's id gets 403; for body fields the id is simply ignored.
    """
    user_id, role = current_user()
    if role == "patient":
        if strict and str(requested) != str(user_id):
            return None, (jsonify({"error": "Patient not found or not assigned to you"}), 403)
        return user_id, None
    try:
        patient_id = int(requested)
    except (TypeError, ValueError):
        return None, (jsonify({"error": "patient_id is required"}), 400)
    if not can_access_patient(user_id, role, patient_id):
        return None, (jsonify({"error": "Patient not found or not assigned to you"}), 403)
    return patient_id, None
