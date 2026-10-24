import random
import datetime
import sys
from pathlib import Path
sys.path.append(
    str(Path(__file__).resolve().parent.parent)
)

from db import get_db_connection


def generate_mock_wearable_data(patient_id, days=30):
    """
    Generates mock wearable data for a patient over a number of days.
    Metrics: pedometer (steps), sleep (minutes), screentime (minutes), heartrate (bpm).
    
    In the future, this data will be analyzed using Exponentially Weighted Moving Average (EWMA)
    to identify trends in these metrics for stress analysis. For example, a downward trend in 
    sleep and an upward trend in resting heart rate and screentime might indicate rising stress levels.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Start date 'days' ago
    start_date = datetime.datetime.now() - datetime.timedelta(days=days)
    
    records = []
    for day in range(days):
        current_date = start_date + datetime.timedelta(days=day)
        
        # Base values with some daily random variance
        steps = random.randint(3000, 12000)
        sleep_minutes = random.randint(240, 540) # 4 to 9 hours
        screentime_minutes = random.randint(60, 480) # 1 to 8 hours
        heartrate = random.randint(60, 100) # Resting HR
        
        records.append((patient_id, current_date, steps, sleep_minutes, screentime_minutes, heartrate))
    
    cursor.executemany("""
        INSERT INTO wearable_data (patient_id, timestamp, pedometer, sleep_minutes, screentime_minutes, heartrate)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, records)
    
    conn.commit()
    cursor.close()
    conn.close()
    print(f"Inserted {days} days of mock wearable data for patient {patient_id}.")

def calculate_ewma(data_series, alpha=0.2):
    """
    Utility function for future use: Calculates Exponentially Weighted Moving Average.
    Formula: EWMA_t = alpha * Y_t + (1 - alpha) * EWMA_{t-1}
    This will be used to smooth the wearable metrics and detect stress trends.
    """
    if not data_series:
        return []
    
    ewma_series = [data_series[0]]
    for y in data_series[1:]:
        ewma_t = alpha * y + (1 - alpha) * ewma_series[-1]
        ewma_series.append(ewma_t)
        
    return ewma_series

if __name__ == "__main__":
    # Example usage: Generate data for patient_id = 1
    # Note: Make sure patient_id 1 exists in the 'patients' table.
    try:
        generate_mock_wearable_data(patient_id=1, days=30)
    except Exception as e:
        print("Error generating mock data:", e)
