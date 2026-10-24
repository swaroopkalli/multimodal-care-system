from db import get_db_connection

def calculate_ewma(data_series, alpha=0.2):
    if not data_series:
        return []
    ewma_series = [data_series[0]]
    for y in data_series[1:]:
        ewma_t = alpha * y + (1 - alpha) * ewma_series[-1]
        ewma_series.append(ewma_t)
    return ewma_series

def generate_patient_context(patient_id):
    """
    Fetches relational patient data and generates a narrative summary.
    Saves it to the patient_contexts table.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Fetch Patient Info
        cursor.execute("SELECT name FROM patients WHERE id = %s", (patient_id,))
        patient = cursor.fetchone()
        if not patient:
            raise ValueError(f"Patient with id {patient_id} not found")
        
        patient_name = patient['name']
        
        # Fetch Wearable Data (latest 14 days for EWMA trend analysis)
        cursor.execute("""
            SELECT timestamp, pedometer, sleep_minutes, screentime_minutes, heartrate 
            FROM wearable_data 
            WHERE patient_id = %s 
            ORDER BY timestamp ASC LIMIT 14
        """, (patient_id,))
        wearables = cursor.fetchall()
        
        # Fetch Medications
        cursor.execute("SELECT name, type, duration FROM medications WHERE patient_id = %s", (patient_id,))
        medications = cursor.fetchall()
        
        # Fetch Doctor Notes
        cursor.execute("SELECT note, created_at FROM doctor_notes WHERE patient_id = %s ORDER BY created_at DESC LIMIT 5", (patient_id,))
        notes = cursor.fetchall()
        
        # Construct the context summary
        context_parts = []
        context_parts.append(f"Patient Overview:\nPatient Name: {patient_name}\n")
        
        # Medications
        if medications:
            meds_str = ", ".join([f"{m['name']} ({m['type']}, {m['duration']} days)" for m in medications])
            context_parts.append(f"Medications:\nThe patient is prescribed: {meds_str}\n")
        else:
            context_parts.append("Medications:\nNo medications prescribed currently.\n")
            
        # Wearable data and EWMA
        if wearables:
            sleep_series = [w['sleep_minutes'] for w in wearables]
            hr_series = [w['heartrate'] for w in wearables]
            
            sleep_ewma = calculate_ewma(sleep_series)
            hr_ewma = calculate_ewma(hr_series)
            
            latest_sleep_ewma = sleep_ewma[-1] if sleep_ewma else 0
            latest_hr_ewma = hr_ewma[-1] if hr_ewma else 0
            
            # Simple stress score logic based on EWMA: 
            # Lower sleep + higher HR = higher stress.
            # Baseline: sleep=420 mins, HR=75 bpm
            sleep_deficit = max(0, 420 - latest_sleep_ewma)
            hr_excess = max(0, latest_hr_ewma - 75)
            stress_score = min(10, max(0, (sleep_deficit / 30) + (hr_excess / 5)))
            
            context_parts.append("Wearable Data Trends (EWMA Analysis over 14 days):")
            context_parts.append(f"- EWMA Sleep: {int(latest_sleep_ewma / 60)} hours {int(latest_sleep_ewma % 60)} mins (Recent trend)")
            context_parts.append(f"- EWMA Resting Heart Rate: {int(latest_hr_ewma)} bpm")
            context_parts.append(f"- Calculated Stress Score (0-10): {stress_score:.1f}/10\n")
        else:
            context_parts.append("Wearable Data:\nNo recent wearable data available.\n")
            
        # Doctor Notes
        if notes:
            context_parts.append("Recent Doctor Notes:")
            for n in notes:
                date_str = n['created_at'].strftime("%Y-%m-%d %H:%M") if n['created_at'] else "Unknown Date"
                context_parts.append(f"- [{date_str}] {n['note']}")
            context_parts.append("")
        else:
            context_parts.append("Doctor Notes:\nNo recent doctor notes.\n")
            
        final_context = "\n".join(context_parts)
        
        # Save to DB
        cursor.execute(
            "INSERT INTO patient_contexts (patient_id, context) VALUES (%s, %s)",
            (patient_id, final_context)
        )
        conn.commit()
        return final_context
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

def get_latest_patient_context(patient_id):
    """
    Retrieves the latest patient context. Generates one if none exists.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT context FROM patient_contexts WHERE patient_id = %s ORDER BY created_at DESC LIMIT 1",
            (patient_id,)
        )
        row = cursor.fetchone()
        if row:
            return row['context']
        else:
            return generate_patient_context(patient_id)
    finally:
        cursor.close()
        conn.close()
