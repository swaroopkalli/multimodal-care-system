"""Recompute smoothed values, daily rollups and anomalies for already-stored wearable rows.

    python backfill.py            # every patient that has wearable data

Raw readings are never modified; only derived columns/tables are rebuilt.
"""

from env_config import load_ingestion_environment

load_ingestion_environment(__file__)

from db import get_db_connection  # noqa: E402
from services import wearable_analytics  # noqa: E402


def main() -> None:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT patient_id FROM wearable_data ORDER BY 1")
        for row in cur.fetchall():
            pid = row["patient_id"]
            rows = wearable_analytics.recompute_patient_ewma(conn, pid)
            days = wearable_analytics.rollup_patient(conn, pid)
            anomalies = wearable_analytics.detect_anomalies(conn, pid, days_back=30)
            print(f"patient {pid}: smoothed {rows} rows, {len(days)} daily rollups, {len(anomalies)} anomalies")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
