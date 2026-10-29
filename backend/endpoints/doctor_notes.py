from flask import request, jsonify
from db import get_db_connection

def add_doctor_note():
    data = request.get_json()
    doctor_id = data.get("doctor_id")
    patient_id = data.get("patient_id")
    note = data.get("note")
    
    if not doctor_id or not patient_id or not note:
        return jsonify({"error": "doctor_id, patient_id, and note are required"}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO doctor_notes (doctor_id, patient_id, note) VALUES (%s, %s, %s) RETURNING id",
            (doctor_id, patient_id, note)
        )
        note_id = cursor.fetchone()['id']
        conn.commit()
        return jsonify({"message": "Doctor note added successfully", "note_id": note_id}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

def get_doctor_notes(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT id, doctor_id, patient_id, note, created_at FROM doctor_notes WHERE patient_id = %s ORDER BY created_at DESC",
            (patient_id,)
        )
        notes = cursor.fetchall()
        
        # Convert datetime objects to strings for JSON serialization
        for note in notes:
            if 'created_at' in note and note['created_at']:
                note['created_at'] = note['created_at'].isoformat()
                
        return jsonify({"notes": notes}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

def get_wearable_data(patient_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, patient_id, timestamp, pedometer, sleep_minutes, screentime_minutes, heartrate FROM wearable_data WHERE patient_id = %s ORDER BY timestamp DESC",
            (patient_id,)
        )
        data = cursor.fetchall()
        for entry in data:
            if 'timestamp' in entry and entry['timestamp']:
                entry['timestamp'] = entry['timestamp'].isoformat()
        return jsonify({"wearable_data": data}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
