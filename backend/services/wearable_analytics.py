"""Daily rollups, daily EWMA and anomaly detection over PostgreSQL history.

Everything reads history in chronological order (newest-N selected with DESC then
reversed - never `ASC LIMIT`). Anomaly baselines use only *prior* days of the same
patient. These are monitoring heuristics, not clinical thresholds.
"""

from __future__ import annotations

import os
import statistics
from datetime import date, datetime, timezone

from services.ewma import daily_ewma, load_config
from services.graph.outbox import enqueue

MIN_HISTORY_DAYS = int(os.getenv("ANOMALY_MIN_HISTORY_DAYS", "7"))
HISTORY_WINDOW_DAYS = int(os.getenv("ANOMALY_HISTORY_WINDOW_DAYS", "30"))
Z_THRESHOLD = float(os.getenv("ANOMALY_Z_THRESHOLD", "2.5"))
MIN_SAMPLES_PER_DAY = int(os.getenv("ANOMALY_MIN_SAMPLES_PER_DAY", "12"))

# signal -> (column in wearable_daily, concerning direction: 'high' | 'low' | 'both', absolute spread floor)
SIGNALS = {
    "heartrate": ("hr_mean", "both", 3.0),
    "sleep": ("sleep_minutes", "low", 20.0),
    "screentime": ("screentime_minutes", "high", 20.0),
    "steps": ("steps_total", "low", 100.0),
}
PARTIAL_DAY_SKIP = {"steps"}      # a day in progress always looks low on cumulative counts


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def rollup_patient(conn, patient_id: int, since_day: date | None = None) -> list[date]:
    """Rebuild wearable_daily rows (aggregates + daily EWMA) from wearable_data. Returns touched days."""
    cfg = load_config()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT timestamp::date AS day, count(*) AS n, sum(pedometer) AS steps_total,
               (array_agg(sleep_minutes ORDER BY timestamp DESC) FILTER (WHERE sleep_minutes IS NOT NULL))[1] AS sleep_minutes,
               (array_agg(screentime_minutes ORDER BY timestamp DESC) FILTER (WHERE screentime_minutes IS NOT NULL))[1] AS screentime_minutes,
               avg(heartrate) FILTER (WHERE NOT ('outlier' = ANY(quality_flags))) AS hr_mean,
               min(heartrate) AS hr_min, max(heartrate) AS hr_max, bool_or(is_simulated) AS sim
        FROM wearable_data
        WHERE patient_id = %s AND (%s::date IS NULL OR timestamp::date >= %s::date)
        GROUP BY 1 ORDER BY 1
        """,
        (patient_id, since_day, since_day),
    )
    rows = cur.fetchall()
    touched = []
    for r in rows:
        cur.execute(
            """
            INSERT INTO wearable_daily (patient_id, day, sample_count, steps_total, sleep_minutes, screentime_minutes,
                hr_mean, hr_min, hr_max, is_simulated, ewma_config_version, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now() AT TIME ZONE 'utc')
            ON CONFLICT (patient_id, day) DO UPDATE SET sample_count = EXCLUDED.sample_count,
                steps_total = EXCLUDED.steps_total, sleep_minutes = EXCLUDED.sleep_minutes,
                screentime_minutes = EXCLUDED.screentime_minutes, hr_mean = EXCLUDED.hr_mean,
                hr_min = EXCLUDED.hr_min, hr_max = EXCLUDED.hr_max, is_simulated = EXCLUDED.is_simulated,
                ewma_config_version = EXCLUDED.ewma_config_version, updated_at = EXCLUDED.updated_at
            """,
            (patient_id, r["day"], r["n"], r["steps_total"], r["sleep_minutes"], r["screentime_minutes"],
             r["hr_mean"], r["hr_min"], r["hr_max"], r["sim"], cfg.version),
        )
        touched.append(r["day"])

    # Daily EWMA over the patient's whole daily history, chronologically.
    cur.execute("SELECT id, day, hr_mean, steps_total, sleep_minutes, screentime_minutes FROM wearable_daily "
                "WHERE patient_id = %s ORDER BY day ASC", (patient_id,))
    hist = cur.fetchall()
    days = [h["day"] for h in hist]
    series = {col: daily_ewma(days, [h[col] for h in hist], cfg.daily_alpha)
              for col in ("hr_mean", "steps_total", "sleep_minutes", "screentime_minutes")}
    for i, h in enumerate(hist):
        cur.execute("UPDATE wearable_daily SET hr_mean_ewma=%s, steps_ewma=%s, sleep_ewma=%s, screentime_ewma=%s "
                    "WHERE id=%s", (series["hr_mean"][i], series["steps_total"][i], series["sleep_minutes"][i],
                                    series["screentime_minutes"][i], h["id"]))
    # Completed days are mirrored to the graph as WearableWindow nodes.
    today = today_utc()
    for h in hist:
        if h["day"] < today and h["day"] in touched:
            enqueue(cur, "window", h["id"], patient_id)
    conn.commit()
    return touched


def _severity(z: float) -> str:
    z = abs(z)
    return "high" if z >= 4 else "moderate" if z >= 3 else "mild"


def evaluate_day(history: list[float], observed: float, direction: str, abs_floor: float, alpha: float,
                 z_threshold: float = Z_THRESHOLD):
    """Score ``observed`` against prior-day ``history`` (chronological). Returns dict or None."""
    values = [v for v in history if v is not None]
    if len(values) < MIN_HISTORY_DAYS:
        return None
    baseline = values[0]
    for v in values[1:]:
        baseline += alpha * (v - baseline)
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values])
    spread = max(1.4826 * mad, abs_floor, 0.05 * abs(baseline))
    score = (observed - baseline) / spread
    concerning = (score >= z_threshold if direction == "high" else
                  score <= -z_threshold if direction == "low" else abs(score) >= z_threshold)
    if not concerning:
        return None
    return {"baseline": baseline, "spread": spread, "score": score, "severity": _severity(score),
            "direction": "high" if score > 0 else "low", "history_days": len(values)}


def detect_anomalies(conn, patient_id: int, days_back: int = 7) -> list[dict]:
    """Evaluate the most recent ``days_back`` days; upserts/clears wearable_anomalies for them."""
    cfg = load_config()
    cur = conn.cursor()
    cur.execute("SELECT * FROM (SELECT * FROM wearable_daily WHERE patient_id = %s ORDER BY day DESC LIMIT %s) t "
                "ORDER BY day ASC", (patient_id, HISTORY_WINDOW_DAYS + days_back))
    rows = cur.fetchall()
    today = today_utc()
    found = []
    for idx in range(max(0, len(rows) - days_back), len(rows)):
        row = rows[idx]
        in_progress = row["day"] >= today
        if row["sample_count"] < MIN_SAMPLES_PER_DAY:
            continue
        prior = rows[max(0, idx - HISTORY_WINDOW_DAYS):idx]
        for signal, (col, direction, floor) in SIGNALS.items():
            if row[col] is None or (in_progress and signal in PARTIAL_DAY_SKIP):
                cur.execute("DELETE FROM wearable_anomalies WHERE patient_id=%s AND day=%s AND signal=%s",
                            (patient_id, row["day"], signal))
                continue
            result = evaluate_day([p[col] for p in prior], float(row[col]), direction, floor, cfg.daily_alpha)
            if result is None:
                cur.execute("DELETE FROM wearable_anomalies WHERE patient_id=%s AND day=%s AND signal=%s",
                            (patient_id, row["day"], signal))
                continue
            cur.execute(
                """INSERT INTO wearable_anomalies (patient_id, day, signal, direction, observed, baseline, spread,
                       score, severity, history_days, is_simulated, ewma_config_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (patient_id, day, signal) DO UPDATE SET direction=EXCLUDED.direction,
                       observed=EXCLUDED.observed, baseline=EXCLUDED.baseline, spread=EXCLUDED.spread,
                       score=EXCLUDED.score, severity=EXCLUDED.severity, history_days=EXCLUDED.history_days,
                       is_simulated=EXCLUDED.is_simulated, ewma_config_version=EXCLUDED.ewma_config_version,
                       detected_at = now() AT TIME ZONE 'utc'
                   RETURNING id""",
                (patient_id, row["day"], signal, result["direction"], float(row[col]), result["baseline"],
                 result["spread"], result["score"], result["severity"], result["history_days"],
                 row["is_simulated"], cfg.version),
            )
            anomaly_id = cur.fetchone()["id"]
            enqueue(cur, "anomaly", anomaly_id, patient_id)
            found.append({"id": anomaly_id, "day": row["day"], "signal": signal, **result})
    conn.commit()
    return found


def recompute_patient_ewma(conn, patient_id: int) -> int:
    """Re-derive per-event heartrate/pedometer EWMA for stored rows (chronological). Returns rows updated."""
    from services.ewma import step
    cfg = load_config()
    cur = conn.cursor()
    cur.execute("SELECT id, timestamp, heartrate, pedometer FROM wearable_data WHERE patient_id = %s "
                "ORDER BY timestamp ASC, id ASC", (patient_id,))
    hr_state = ped_state = None
    updates = []
    for r in cur.fetchall():
        ts = r["timestamp"].replace(tzinfo=timezone.utc).timestamp()
        hr_ewma = ped_ewma = None
        flags: list[str] = []
        if r["heartrate"] is not None:
            hr_state, hr_ewma, f = step(hr_state, r["heartrate"], ts, cfg.heartrate, cfg)
            flags += f
        if r["pedometer"] is not None:
            ped_state, ped_ewma, f = step(ped_state, r["pedometer"], ts, cfg.pedometer, cfg)
            flags += f
        flags = sorted({x for x in flags if x != "warmup"} | ({"warmup"} if "warmup" in flags and
                       hr_state is not None and hr_state.n < cfg.warmup_samples else set()))
        updates.append((hr_ewma, ped_ewma, cfg.version, flags, r["id"]))
    for u in updates:
        cur.execute("UPDATE wearable_data SET heartrate_ewma=%s, pedometer_ewma=%s, ewma_config_version=%s, "
                    "quality_flags=%s WHERE id=%s", u)
    conn.commit()
    return len(updates)
