import os

from flask import Flask, jsonify
from flask_cors import CORS

from db import create_tables
from endpoints.auth import register_caretaker,register_doctor, register_patient, login_caretaker, login_doctor, login_patient
from endpoints.doctor_notes import add_doctor_note, get_doctor_notes,get_wearable_data
from endpoints.chat import staff_chat, patient_chat
app = Flask(__name__)
CORS(app)
app.add_url_rule("/api/auth/register/caretaker", view_func=register_caretaker, methods=["POST"])
app.add_url_rule("/api/auth/register/doctor", view_func=register_doctor, methods=["POST"])
app.add_url_rule("/api/auth/register/patient", view_func=register_patient, methods=["POST"])
app.add_url_rule("/api/auth/login/caretaker", view_func=login_caretaker, methods=["POST"])
app.add_url_rule("/api/auth/login/doctor", view_func=login_doctor, methods=["POST"])
app.add_url_rule("/api/auth/login/patient", view_func=login_patient, methods=["POST"]) 
app.add_url_rule("/api/doctor_notes", view_func=add_doctor_note, methods=["POST"])
app.add_url_rule("/api/doctor_notes/<int:patient_id>", view_func=get_doctor_notes, methods=["GET"])
app.add_url_rule("/api/wearables_data/<int:patient_id>", view_func=get_wearable_data, methods=["GET"])
app.add_url_rule("/api/staff/chat", view_func=staff_chat, methods=["POST"])
app.add_url_rule("/api/patient/chat", view_func=patient_chat, methods=["POST"])

if __name__ == "__main__":
    create_tables()
    app.run(host="0.0.0.0", port=5000, debug=True)
