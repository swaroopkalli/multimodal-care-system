from flask import request, jsonify
from db import get_db_connection
from services.context import get_latest_patient_context
from services.llm import generate_response, generate_chat_response

STAFF_SYSTEM_PROMPT = """You are a clinical and analytical AI assistant for the medical and caretaking staff.
Your goal is to provide concise clinical summaries, patient history analysis, medication adherence insights, and stress trend analysis (via EWMA score) based on the provided RAG context.
IMPORTANT: You are an assistant, not a doctor. Do not provide medical diagnoses or prescribe medications. Provide practical observations for caretaking. Keep your responses concise, structured, and highly analytical."""

PATIENT_SYSTEM_PROMPT = """You are an empathetic wellness coach AI for a patient.
Your goal is to be a supportive conversational agent. Provide wellness coaching, stress reduction techniques, sleep improvement tips, and emotional support.
IMPORTANT RULES:
- You are NOT a therapist.
- You CANNOT diagnose or treat medical conditions.
- Always encourage seeking professional help when appropriate.
- Maintain an empathetic, encouraging, and supportive tone.
- Reply directly to the user based on the conversation flow."""

def log_chat(role, patient_id, query, response):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO chatbot_logs (role, patient_id, query, response) VALUES (%s, %s, %s, %s)",
            (role, patient_id, query, response)
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Failed to log chat:", e)
    finally:
        cursor.close()
        conn.close()

def get_chat_history(patient_id, role="patient", limit=5):
    conn = get_db_connection()
    cursor = conn.cursor()
    history = []
    try:
        cursor.execute(
            "SELECT query, response FROM chatbot_logs WHERE patient_id = %s AND role = %s ORDER BY created_at ASC LIMIT %s",
            (patient_id, role, limit)
        )
        logs = cursor.fetchall()
        for log in logs:
            history.append({"role": "user", "parts": [log["query"]]})
            history.append({"role": "model", "parts": [log["response"]]})
    except Exception as e:
        print("Failed to fetch history:", e)
    finally:
        cursor.close()
        conn.close()
    return history

def staff_chat():
    data = request.get_json()
    patient_id = data.get("patient_id")
    query = data.get("query")
    
    if not patient_id or not query:
        return jsonify({"error": "patient_id and query are required"}), 400
        
    try:
        # Staff uses RAG context with EWMA
        context = get_latest_patient_context(patient_id)
        response_text = generate_response(STAFF_SYSTEM_PROMPT, context, query)
        log_chat("staff", patient_id, query, response_text)
        return jsonify({"response": response_text}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def patient_chat():
    data = request.get_json()
    patient_id = data.get("patient_id")
    query = data.get("query")
    
    if not patient_id or not query:
        return jsonify({"error": "patient_id and query are required"}), 400
        
    try:
        # Patient uses conversational history, no RAG
        history = get_chat_history(patient_id, role="patient")
        response_text = generate_chat_response(PATIENT_SYSTEM_PROMPT, history, query)
        log_chat("patient", patient_id, query, response_text)
        return jsonify({"response": response_text}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
