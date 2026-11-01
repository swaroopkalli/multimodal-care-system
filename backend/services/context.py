"""Patient context for the AI: pinned facts built from PostgreSQL, ordered by priority.

Sections are whole units so the budgeter can drop lower-priority ones without cutting text.
Wearable data is shown from daily rollups in chronological order (newest 7 days) with EWMA
values, and anything synthetic is labelled as such.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from db import get_db_connection
from services import live_vitals
from services.budget import LRUCache
from services.ewma import ewma_series

_cache = LRUCache(maxsize=128)          # (patient_id, role, source_hash) -> static sections


def calculate_ewma(data_series, alpha=0.2):
    """EWMA over an ordered series; None values are skipped (not imputed) and returned as None."""
    return ewma_series(data_series, alpha)


@dataclass
class ContextBundle:
    sections: list           # [{"name", "text", "priority"}] priority 0 = most important
    source_hash: str

    def text(self, max_priority: int | None = None) -> str:
        parts = [s["text"] for s in sorted(self.sections, key=lambda s: s["priority"])
                 if max_priority is None or s["priority"] <= max_priority]
        return "\n\n".join(parts)


def _hm(minutes):
    return "unknown" if minutes is None else f"{int(minutes // 60)}h {int(minutes % 60)}m ({int(minutes)} min)"


def _fmt(v, nd=0, unit=""):
    return "n/a" if v is None else f"{v:.{nd}f}{unit}"


def _stress_heuristic(sleep_ewma, hr_ewma):
    """Monitoring heuristic (NOT a clinical score): short sleep + raised heart rate => higher."""
    if sleep_ewma is None and hr_ewma is None:
        return None
    base_sleep = float(os.getenv("STRESS_BASE_SLEEP_MIN", "420"))
    base_hr = float(os.getenv("STRESS_BASE_HR", "75"))
    deficit = max(0.0, base_sleep - sleep_ewma) if sleep_ewma is not None else 0.0
    excess = max(0.0, hr_ewma - base_hr) if hr_ewma is not None else 0.0
    return min(10.0, deficit / 30 + excess / 5)


def _source_hash(cur, patient_id: int) -> str:
    cur.execute(
        "SELECT (SELECT coalesce(max(id),0)||'/'||count(*) FROM doctor_notes WHERE patient_id=%(p)s) n,"
        " (SELECT coalesce(max(id),0)||'/'||count(*) FROM medications WHERE patient_id=%(p)s) m,"
        " (SELECT coalesce(max(updated_at)::text,'') FROM wearable_daily WHERE patient_id=%(p)s) w,"
        " (SELECT coalesce(max(id),0) FROM wearable_anomalies WHERE patient_id=%(p)s) a,"
        " (SELECT coalesce(max(id),0) FROM patient_checkins WHERE patient_id=%(p)s) c,"
        " (SELECT coalesce(max(id),0) FROM caretaker_observations WHERE patient_id=%(p)s) o", {"p": patient_id})
    return hashlib.sha256(repr(sorted(cur.fetchone().items())).encode()).hexdigest()


def _build_static_sections(cur, patient_id: int, staff: bool) -> list:
    cur.execute("SELECT name FROM patients WHERE id = %s", (patient_id,))
    patient = cur.fetchone()
    if not patient:
        raise ValueError(f"Patient with id {patient_id} not found")
    sections = [{"name": "overview", "priority": 0, "text": f"Patient Overview:\nPatient Name: {patient['name']}"}]

    cur.execute("SELECT name, type, duration FROM medications WHERE patient_id = %s ORDER BY id", (patient_id,))
    meds = cur.fetchall()
    sections.append({"name": "medications", "priority": 0, "text": "Medications (recorded):\n" + (
        ", ".join(f"{m['name']} ({m['type']}, {m['duration']} days)" for m in meds) if meds
        else "No medications recorded.")})

    # newest 7 days, shown oldest -> newest
    cur.execute("SELECT * FROM (SELECT * FROM wearable_daily WHERE patient_id = %s ORDER BY day DESC LIMIT 7) t "
                "ORDER BY day ASC", (patient_id,))
    days = cur.fetchall()
    if days:
        lines = ["Wearable daily summaries (UTC days, oldest to newest; EWMA = exponentially smoothed):"]
        for d in days:
            tag = " [SIMULATED]" if d["is_simulated"] else ""
            lines.append(f"- {d['day']}{tag}: sleep {_hm(d['sleep_minutes'])}, mean heart rate {_fmt(d['hr_mean'], 0, ' bpm')} "
                         f"(range {d['hr_min']}-{d['hr_max']}), activity count {d['steps_total']}, samples {d['sample_count']}")
        last = days[-1]
        lines.append(f"- Smoothed trend: sleep EWMA {_hm(last['sleep_ewma'])}; heart-rate EWMA {_fmt(last['hr_mean_ewma'], 0, ' bpm')}")
        score = _stress_heuristic(last["sleep_ewma"], last["hr_mean_ewma"])
        if score is not None:
            lines.append(f"- Monitoring heuristic (not a clinical score): {score:.1f}/10 based on shorter sleep and higher heart rate")
        if any(d["is_simulated"] for d in days):
            lines.append("NOTE: values marked [SIMULATED] are synthetic test data, not real measurements.")
        sections.append({"name": "wearables", "priority": 1, "text": "\n".join(lines)})
    else:
        sections.append({"name": "wearables", "priority": 1, "text": "Wearable data: none recorded yet."})

    cur.execute("SELECT day, signal, direction, observed, baseline, score, severity, history_days, is_simulated "
                "FROM wearable_anomalies WHERE patient_id = %s ORDER BY day DESC, id DESC LIMIT 8", (patient_id,))
    anomalies = list(reversed(cur.fetchall()))
    if anomalies:
        sections.append({"name": "anomalies", "priority": 1, "text": "Detected changes vs the patient's own history:\n" + "\n".join(
            f"- {a['day']}{' [SIMULATED]' if a['is_simulated'] else ''}: {a['signal']} {a['direction']} "
            f"(observed {a['observed']:.0f}, usual {a['baseline']:.0f}, severity {a['severity']}, based on {a['history_days']} prior days)"
            for a in anomalies)})

    cur.execute("SELECT mood, stress, sleep_hours, energy, side_effects, created_at FROM patient_checkins "
                "WHERE patient_id = %s ORDER BY id DESC LIMIT 3", (patient_id,))
    checkins = list(reversed(cur.fetchall()))
    if checkins:
        sections.append({"name": "checkins", "priority": 2, "text": "Recent patient self-reports:\n" + "\n".join(
            f"- {c['created_at']:%Y-%m-%d %H:%M}: mood {_fmt(c['mood'],0)}/5, stress {_fmt(c['stress'],0)}/10, "
            f"sleep {_fmt(c['sleep_hours'],1,' h')}, energy {_fmt(c['energy'],0)}/10, side effects: "
            f"{', '.join(c['side_effects']) or 'none reported'}" for c in checkins)})

    if staff:
        cur.execute("SELECT note, created_at FROM doctor_notes WHERE patient_id = %s ORDER BY id DESC LIMIT 5", (patient_id,))
        notes = list(reversed(cur.fetchall()))
        sections.append({"name": "notes", "priority": 1, "text": "Recent doctor notes:\n" + (
            "\n".join(f"- [{n['created_at']:%Y-%m-%d %H:%M}] {n['note']}" for n in notes) if notes else "None.")})
        cur.execute("SELECT did_not_sleep, restless, seems_better, medication_confirmed, created_at FROM caretaker_observations "
                    "WHERE patient_id = %s ORDER BY id DESC LIMIT 3", (patient_id,))
        obs = list(reversed(cur.fetchall()))
        if obs:
            sections.append({"name": "observations", "priority": 2, "text": "Recent caretaker observations:\n" + "\n".join(
                f"- {o['created_at']:%Y-%m-%d %H:%M}: " + ", ".join(
                    x for x, on in (("did not sleep", o["did_not_sleep"]), ("restless", o["restless"]),
                                    ("seems better", o["seems_better"]),
                                    ("medication confirmed", o["medication_confirmed"])) if on) for o in obs)})
    return sections


def _live_section(patient_id: int):
    try:
        v = live_vitals.get_latest(patient_id)
    except Exception:
        return None
    if not v:
        return None
    tag = " [SIMULATED]" if v["is_simulated"] else ""
    return {"name": "live", "priority": 1, "text": (
        f"Latest wearable reading{tag} at {v['measured_at']}: heart rate {_fmt(v['heartrate'])} bpm "
        f"(smoothed {_fmt(v['heartrate_ewma'], 0)} bpm)")}


def build_context(patient_id: int, role: str = "staff") -> ContextBundle:
    """Fresh, versioned context. Static sections are cached per source-data hash; the live reading never is."""
    staff = role != "patient"
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        digest = _source_hash(cur, patient_id)
        key = (patient_id, staff, digest)
        sections = _cache.get(key)
        if sections is None:
            sections = _build_static_sections(cur, patient_id, staff)
            _cache.put(key, sections)
    finally:
        conn.close()
    sections = list(sections)
    live = _live_section(patient_id)
    if live:
        sections.append(live)
    return ContextBundle(sections, digest)


def generate_patient_context(patient_id: int) -> str:
    """Build the staff context and store it in patient_contexts with its source hash."""
    bundle = build_context(patient_id, "staff")
    text = bundle.text()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO patient_contexts (patient_id, context, source_hash) VALUES (%s, %s, %s)",
                    (patient_id, text, bundle.source_hash))
        conn.commit()
    finally:
        conn.close()
    return text


def get_latest_patient_context(patient_id: int) -> str:
    """Stored staff context when its source data is unchanged; otherwise regenerate."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        current = _source_hash(cur, patient_id)
        cur.execute("SELECT context, source_hash FROM patient_contexts WHERE patient_id = %s ORDER BY id DESC LIMIT 1",
                    (patient_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    if row and row["source_hash"] == current:
        return row["context"]
    return generate_patient_context(patient_id)
