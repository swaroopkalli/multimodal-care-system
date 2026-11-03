import logging
import os
import secrets
from datetime import timedelta

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from db import create_tables
from endpoints.auth import (login_caretaker, login_doctor, login_patient, register_caretaker,
                            register_doctor, register_patient)
from endpoints.chat import patient_chat, staff_chat
from endpoints.doctor_notes import add_doctor_note, get_doctor_notes, get_wearable_data
from endpoints.patients import (add_medication, list_patients, live_vitals_route, patient_summary,
                                submit_checkin, submit_journal, submit_observation)

log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

_secret = os.getenv("JWT_SECRET_KEY", "").strip()
if len(_secret) < 32:
    # Never run with a weak/missing secret: tokens simply stop validating after a restart.
    _secret = secrets.token_urlsafe(48)
    log.warning("JWT_SECRET_KEY missing or shorter than 32 chars; using an ephemeral key (set it in .env)")
app.config["JWT_SECRET_KEY"] = _secret
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=int(os.getenv("JWT_ACCESS_TTL_HOURS", "12")))
jwt = JWTManager(app)


@jwt.unauthorized_loader
def _missing_token(reason):
    return jsonify({"error": "Authentication required"}), 401


@jwt.invalid_token_loader
def _invalid_token(reason):
    return jsonify({"error": "Invalid token"}), 401


@jwt.expired_token_loader
def _expired_token(header, payload):
    return jsonify({"error": "Token expired"}), 401


ROUTES = [
    ("/api/auth/register/caretaker", register_caretaker, ["POST"]),
    ("/api/auth/register/doctor", register_doctor, ["POST"]),
    ("/api/auth/register/patient", register_patient, ["POST"]),
    ("/api/auth/login/caretaker", login_caretaker, ["POST"]),
    ("/api/auth/login/doctor", login_doctor, ["POST"]),
    ("/api/auth/login/patient", login_patient, ["POST"]),
    ("/api/doctor_notes", add_doctor_note, ["POST"]),
    ("/api/doctor_notes/<int:patient_id>", get_doctor_notes, ["GET"]),
    ("/api/wearables_data/<int:patient_id>", get_wearable_data, ["GET"]),
    ("/api/staff/chat", staff_chat, ["POST"]),
    ("/api/patient/chat", patient_chat, ["POST"]),
    ("/api/patient/checkin", submit_checkin, ["POST"]),
    ("/api/patient/journal", submit_journal, ["POST"]),
    ("/api/caretaker/observations", submit_observation, ["POST"]),
    ("/api/medications", add_medication, ["POST"]),
    ("/api/patients", list_patients, ["GET"]),
    ("/api/patients/<int:patient_id>/summary", patient_summary, ["GET"]),
    ("/api/patients/<int:patient_id>/vitals/live", live_vitals_route, ["GET"]),
]
for rule, view, methods in ROUTES:
    app.add_url_rule(rule, view_func=view, methods=methods)


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


def start_background_services() -> None:
    """Mirror PostgreSQL rows into Neo4j in the background (no-op when Neo4j is not configured)."""
    if os.getenv("NEO4J_PASSWORD"):
        from services.graph.sync import start_background_worker
        start_background_worker(float(os.getenv("GRAPH_SYNC_INTERVAL_SECONDS", "5")))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_tables()
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background_services()
    app.run(host=os.getenv("FLASK_HOST", "127.0.0.1"), port=int(os.getenv("FLASK_PORT", "5001")), debug=debug)
