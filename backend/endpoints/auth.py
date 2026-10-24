from flask import request, jsonify # type: ignore

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from flask_jwt_extended import (
    create_access_token
)

from db import get_db_connection


# =====================================================
# CARETAKER REGISTER
# =====================================================

def register_caretaker():

    data = request.json

    username = data.get("username")
    name = data.get("name")
    password = data.get("password")

    if not username or not name or not password:

        return jsonify({
            "error": "Missing required fields"
        }), 400

    hashed_password = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO caretakers
            (username, name, password)

            VALUES (%s, %s, %s)

            RETURNING id, username, name
            """,
            (
                username,
                name,
                hashed_password
            )
        )

        caretaker = cursor.fetchone()

        conn.commit()

        return jsonify({
            "message": "Caretaker registered successfully",
            "user": caretaker
        }), 201

    except Exception as e:

        conn.rollback()

        return jsonify({
            "error": str(e)
        }), 400

    finally:

        cursor.close()
        conn.close()


# =====================================================
# CARETAKER LOGIN
# =====================================================

def login_caretaker():

    data = request.json

    username = data.get("username")
    password = data.get("password")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM caretakers
        WHERE username = %s
        """,
        (username,)
    )

    caretaker = cursor.fetchone()

    cursor.close()
    conn.close()

    if not caretaker:

        return jsonify({
            "error": "Invalid username or password"
        }), 401

    if not check_password_hash(
        caretaker["password"],
        password
    ):

        return jsonify({
            "error": "Invalid username or password"
        }), 401

    token = create_access_token(
        identity={
            "id": caretaker["id"],
            "role": "caretaker"
        }
    )

    return jsonify({
        "message": "Login successful",
        "token": token
    })


# =====================================================
# DOCTOR REGISTER
# =====================================================

def register_doctor():

    data = request.json

    username = data.get("username")
    name = data.get("name")
    password = data.get("password")

    if not username or not name or not password:

        return jsonify({
            "error": "Missing required fields"
        }), 400

    hashed_password = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO doctors
            (username, name, password)

            VALUES (%s, %s, %s)

            RETURNING id, username, name
            """,
            (
                username,
                name,
                hashed_password
            )
        )

        doctor = cursor.fetchone()

        conn.commit()

        return jsonify({
            "message": "Doctor registered successfully",
            "user": doctor
        }), 201

    except Exception as e:

        conn.rollback()

        return jsonify({
            "error": str(e)
        }), 400

    finally:

        cursor.close()
        conn.close()


# =====================================================
# DOCTOR LOGIN
# =====================================================

def login_doctor():

    data = request.json

    username = data.get("username")
    password = data.get("password")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM doctors
        WHERE username = %s
        """,
        (username,)
    )

    doctor = cursor.fetchone()

    cursor.close()
    conn.close()

    if not doctor:

        return jsonify({
            "error": "Invalid username or password"
        }), 401

    if not check_password_hash(
        doctor["password"],
        password
    ):

        return jsonify({
            "error": "Invalid username or password"
        }), 401

    token = create_access_token(
        identity={
            "id": doctor["id"],
            "role": "doctor"
        }
    )

    return jsonify({
        "message": "Login successful",
        "token": token
    })


# =====================================================
# PATIENT REGISTER
# =====================================================

def register_patient():

    data = request.json

    username = data.get("username")
    name = data.get("name")
    password = data.get("password")

    caretaker_id = data.get("caretaker_id")
    doctor_id = data.get("doctor_id")

    if not username or not name or not password:

        return jsonify({
            "error": "Missing required fields"
        }), 400

    hashed_password = generate_password_hash(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO patients
            (
                username,
                name,
                password,
                caretaker_id,
                doctor_id
            )

            VALUES (%s, %s, %s, %s, %s)

            RETURNING id, username, name
            """,
            (
                username,
                name,
                hashed_password,
                caretaker_id,
                doctor_id
            )
        )

        patient = cursor.fetchone()

        conn.commit()

        return jsonify({
            "message": "Patient registered successfully",
            "user": patient
        }), 201

    except Exception as e:

        conn.rollback()

        return jsonify({
            "error": str(e)
        }), 400

    finally:

        cursor.close()
        conn.close()


# =====================================================
# PATIENT LOGIN
# =====================================================

def login_patient():

    data = request.json

    username = data.get("username")
    password = data.get("password")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT * FROM patients
        WHERE username = %s
        """,
        (username,)
    )

    patient = cursor.fetchone()

    cursor.close()
    conn.close()

    if not patient:

        return jsonify({
            "error": "Invalid username or password"
        }), 401

    if not check_password_hash(
        patient["password"],
        password
    ):

        return jsonify({
            "error": "Invalid username or password"
        }), 401

    token = create_access_token(
        identity={
            "id": patient["id"],
            "role": "patient"
        }
    )

    return jsonify({
        "message": "Login successful",
        "token": token
    })