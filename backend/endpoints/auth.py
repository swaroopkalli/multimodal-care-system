import logging

import psycopg2.errors
from flask import jsonify, request
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db_connection

log = logging.getLogger(__name__)

_TABLES = {"caretaker": "caretakers", "doctor": "doctors", "patient": "patients"}
# Used to keep login timing similar whether or not the username exists.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _text(data, key):
    value = data.get(key)
    return value.strip() if isinstance(value, str) else None


def _lookup_id(cursor, table, username):
    cursor.execute(f"SELECT id FROM {table} WHERE username = %s", (username,))
    row = cursor.fetchone()
    return row["id"] if row else None


def _register(role):
    data = _json_body()
    username, name, password = _text(data, "username"), _text(data, "name"), data.get("password")
    if not username or not name or not isinstance(password, str) or not password:
        return jsonify({"error": "Missing required fields"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        extra_cols, extra_vals = "", ()
        if role == "patient":
            # A patient is linked to staff by id or by username.
            links = {}
            for kind, table in (("caretaker", "caretakers"), ("doctor", "doctors")):
                linked = data.get(f"{kind}_id")
                uname = _text(data, f"{kind}_username")
                if uname:
                    linked = _lookup_id(cursor, table, uname)
                    if linked is None:
                        return jsonify({"error": f"Unknown {kind} username"}), 400
                links[kind] = linked
            extra_cols, extra_vals = ", caretaker_id, doctor_id", (links["caretaker"], links["doctor"])
        placeholders = "%s, %s, %s" + (", %s, %s" if role == "patient" else "")
        cursor.execute(
            f"INSERT INTO {_TABLES[role]} (username, name, password{extra_cols}) "
            f"VALUES ({placeholders}) RETURNING id, username, name",
            (username, name, generate_password_hash(password)) + extra_vals,
        )
        user = cursor.fetchone()
        conn.commit()
        return jsonify({"message": f"{role.capitalize()} registered successfully", "user": user}), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({"error": "Username already exists"}), 409
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        return jsonify({"error": "Referenced doctor or caretaker does not exist"}), 400
    except Exception:
        conn.rollback()
        log.exception("registration failed (%s)", role)
        return jsonify({"error": "Registration failed"}), 500
    finally:
        conn.close()


def _login(role):
    data = _json_body()
    username, password = _text(data, "username"), data.get("password")
    if not username or not isinstance(password, str) or not password:
        return jsonify({"error": "Username and password are required"}), 400

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT id, username, name, password FROM {_TABLES[role]} WHERE username = %s", (username,))
        user = cursor.fetchone()
    finally:
        conn.close()

    stored_hash = user["password"] if user else _DUMMY_HASH
    if not check_password_hash(stored_hash, password) or not user:
        return jsonify({"error": "Invalid username or password"}), 401

    token = create_access_token(identity=str(user["id"]), additional_claims={"role": role})
    return jsonify({
        "message": "Login successful",
        "token": token,
        "user": {"id": user["id"], "role": role, "username": user["username"], "name": user["name"]},
    })


def register_caretaker(): return _register("caretaker")
def register_doctor(): return _register("doctor")
def register_patient(): return _register("patient")
def login_caretaker(): return _login("caretaker")
def login_doctor(): return _login("doctor")
def login_patient(): return _login("patient")
