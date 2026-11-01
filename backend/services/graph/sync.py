"""PostgreSQL -> Neo4j mirroring driven by the graph_sync_outbox table.

PostgreSQL stays authoritative. Neo4j nodes hold ids, patient scope, timestamps and
embeddings; clinical text is re-read from PostgreSQL when retrieved (no duplicate PHI).

    python -m services.graph.sync backfill   # enqueue everything that exists
    python -m services.graph.sync drain      # process the outbox now
    python -m services.graph.sync reconcile  # compare PostgreSQL vs Neo4j counts
"""

from __future__ import annotations

import hashlib
import logging
import sys
import threading
import time

from db import get_db_connection
from services.graph import client
from services.graph.client import ENTITIES, GraphUnavailable
from services.graph.embeddings import embed_document, model_name
from services.graph.outbox import enqueue

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def window_text(row: dict) -> str:
    """Deterministic narrative of one daily rollup (also used when hydrating retrieved windows)."""
    sleep = row["sleep_minutes"]
    sleep_txt = "unknown" if sleep is None else f"{sleep // 60}h {sleep % 60}m"
    tag = " (simulated data)" if row["is_simulated"] else ""
    hr = "n/a" if row["hr_mean"] is None else f"{row['hr_mean']:.0f} bpm"
    return (f"Wearable summary for {row['day']}{tag}: sleep {sleep_txt}, mean heart rate {hr}, "
            f"activity count {row['steps_total']}, screen time {row['screentime_minutes']} min.")


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- loaders
# Each returns (props, text_to_embed_or_None) or None when the source row no longer exists.

def _load(cur, entity_type: str, entity_id: int):
    if entity_type == "note":
        cur.execute("SELECT id, patient_id, note, created_at FROM doctor_notes WHERE id = %s", (entity_id,))
        r = cur.fetchone()
        return r and ({"patient_id": r["patient_id"], "created_at": r["created_at"].isoformat(), "importance": 1.0}, r["note"])
    if entity_type == "turn":
        cur.execute("SELECT id, patient_id, role, query, created_at FROM chatbot_logs WHERE id = %s", (entity_id,))
        r = cur.fetchone()
        return r and ({"patient_id": r["patient_id"], "role": r["role"], "created_at": r["created_at"].isoformat(),
                       "importance": 0.3}, r["query"])
    if entity_type == "journal":
        cur.execute("SELECT id, patient_id, entry, created_at FROM journal_entries WHERE id = %s", (entity_id,))
        r = cur.fetchone()
        return r and ({"patient_id": r["patient_id"], "created_at": r["created_at"].isoformat(), "importance": 0.8}, r["entry"])
    if entity_type == "window":
        cur.execute("SELECT * FROM wearable_daily WHERE id = %s", (entity_id,))
        r = cur.fetchone()
        return r and ({"patient_id": r["patient_id"], "day": r["day"].isoformat(), "created_at": r["day"].isoformat(),
                       "is_simulated": bool(r["is_simulated"]), "importance": 0.5}, window_text(r))
    if entity_type == "anomaly":
        cur.execute("SELECT * FROM wearable_anomalies WHERE id = %s", (entity_id,))
        r = cur.fetchone()
        return r and ({"patient_id": r["patient_id"], "day": r["day"].isoformat(), "signal": r["signal"],
                       "severity": r["severity"], "is_simulated": bool(r["is_simulated"]),
                       "created_at": r["day"].isoformat(), "importance": 0.9}, None)
    if entity_type == "medication":
        cur.execute("SELECT id, patient_id, name FROM medications WHERE id = %s", (entity_id,))
        r = cur.fetchone()
        return r and ({"patient_id": r["patient_id"], "name": r["name"], "importance": 1.0}, None)
    raise ValueError(entity_type)


def _upsert(cur, item: dict) -> None:
    spec = ENTITIES[item["entity_type"]]
    label, rel = spec["label"], spec["rel"]
    pid, eid = item["patient_id"], item["entity_id"]

    if item["op"] == "delete":
        client.run(f"MATCH (n:{label} {{pg_id: $id, patient_id: $pid}}) DETACH DELETE n", id=eid, pid=pid)
        return

    loaded = _load(cur, item["entity_type"], eid)
    if loaded is None:                                   # source row is gone: remove the mirror
        client.run(f"MATCH (n:{label} {{pg_id: $id, patient_id: $pid}}) DETACH DELETE n", id=eid, pid=pid)
        return
    props, text = loaded
    if props["patient_id"] != pid:
        raise ValueError("outbox patient_id does not match source row")

    if text is not None:
        digest, model = _text_hash(text), model_name()
        existing = client.run(f"MATCH (n:{label} {{pg_id: $id}}) RETURN n.text_hash AS h, n.embedding_model AS m",
                              id=eid)
        if existing and existing[0]["h"] == digest and existing[0]["m"] == model:
            vector = None                                # unchanged: keep the stored embedding
        else:
            vector = embed_document(text)
        props = {**props, "text_hash": digest, "embedding_model": model}
        if vector is not None:
            props["embedding"] = vector

    client.run(
        f"MERGE (p:Patient {{pg_id: $pid}}) "
        f"MERGE (n:{label} {{pg_id: $id}}) SET n += $props "
        f"MERGE (p)-[:{rel}]->(n)", pid=pid, id=eid, props=props)

    if item["entity_type"] == "turn":
        client.run("MATCH (t:ConversationTurn {pg_id: $id}) "
                   "OPTIONAL MATCH (prev:ConversationTurn {patient_id: $pid, role: t.role}) WHERE prev.pg_id < $id "
                   "WITH t, prev ORDER BY prev.pg_id DESC LIMIT 1 "
                   "FOREACH (_ IN CASE WHEN prev IS NULL THEN [] ELSE [1] END | MERGE (prev)-[:NEXT]->(t))",
                   id=eid, pid=pid)
        cur.execute("SELECT id, name FROM medications WHERE patient_id = %s", (pid,))
        lowered = text.lower()
        for med in cur.fetchall():
            if med["name"].lower() in lowered:
                client.run("MATCH (t:ConversationTurn {pg_id: $id}), (m:Medication {pg_id: $mid, patient_id: $pid}) "
                           "MERGE (t)-[:MENTIONS]->(m)", id=eid, mid=med["id"], pid=pid)
    elif item["entity_type"] == "anomaly":
        client.run("MATCH (a:Anomaly {pg_id: $id}), (w:WearableWindow {patient_id: $pid, day: $day}) "
                   "MERGE (a)-[:DETECTED_IN]->(w)", id=eid, pid=pid, day=props["day"])
    elif item["entity_type"] == "window":
        client.run("MATCH (w:WearableWindow {pg_id: $id}), (a:Anomaly {patient_id: $pid, day: $day}) "
                   "MERGE (a)-[:DETECTED_IN]->(w)", id=eid, pid=pid, day=props["day"])


def drain(limit: int = 50) -> dict:
    """Process pending outbox rows. Safe to call concurrently (rows are claimed with SKIP LOCKED)."""
    stats = {"done": 0, "failed": 0, "retry": 0}
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, entity_type, entity_id, patient_id, op, attempts FROM graph_sync_outbox "
                    "WHERE status = 'pending' ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED", (limit,))
        items = cur.fetchall()
        for item in items:
            try:
                _upsert(cur, item)
                cur.execute("UPDATE graph_sync_outbox SET status='done', processed_at=now() AT TIME ZONE 'utc', "
                            "attempts=attempts+1, last_error=NULL WHERE id=%s", (item["id"],))
                stats["done"] += 1
            except GraphUnavailable as exc:
                conn.rollback()                           # infrastructure down: leave pending, stop this pass
                log.warning("graph sync paused: %s", exc)
                stats["retry"] += 1
                return stats
            except Exception as exc:
                attempts = item["attempts"] + 1
                status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
                cur.execute("UPDATE graph_sync_outbox SET attempts=%s, status=%s, last_error=%s WHERE id=%s",
                            (attempts, status, f"{type(exc).__name__}: {str(exc)[:200]}", item["id"]))
                stats["failed" if status == "failed" else "retry"] += 1
            conn.commit()
        conn.commit()
    finally:
        conn.close()
    return stats


def drain_all(max_rounds: int = 20) -> dict:
    total = {"done": 0, "failed": 0, "retry": 0}
    for _ in range(max_rounds):
        s = drain()
        for k in total:
            total[k] += s[k]
        if not s["done"] and not s["failed"]:
            break
    return total


def start_background_worker(interval: float = 5.0) -> threading.Thread:
    def loop():
        while True:
            try:
                drain()
            except Exception as exc:
                log.warning("background graph sync error: %s", type(exc).__name__)
            time.sleep(interval)
    t = threading.Thread(target=loop, name="graph-sync", daemon=True)
    t.start()
    return t


# --------------------------------------------------------------- backfill / reconcile

_BACKFILL = {
    "note": "SELECT id, patient_id FROM doctor_notes",
    "turn": "SELECT id, patient_id FROM chatbot_logs WHERE response <> ''",
    "journal": "SELECT id, patient_id FROM journal_entries",
    "window": "SELECT id, patient_id FROM wearable_daily WHERE day < (now() AT TIME ZONE 'utc')::date",
    "anomaly": "SELECT id, patient_id FROM wearable_anomalies",
    "medication": "SELECT id, patient_id FROM medications",
}


def backfill_enqueue() -> int:
    conn = get_db_connection()
    n = 0
    try:
        cur = conn.cursor()
        for etype, sql in _BACKFILL.items():
            cur.execute(sql)
            for row in cur.fetchall():
                enqueue(cur, etype, row["id"], row["patient_id"])
                n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def reconcile(patient_id: int | None = None) -> dict:
    """Per-entity row counts in PostgreSQL vs Neo4j (completed-day windows only for windows)."""
    conn = get_db_connection()
    out = {}
    try:
        cur = conn.cursor()
        for etype, sql in _BACKFILL.items():
            cur.execute(sql + (" AND" if " WHERE " in sql else " WHERE") + " patient_id = %s" if patient_id else sql,
                        (patient_id,) if patient_id else None)
            pg = len(cur.fetchall())
            label = ENTITIES[etype]["label"]
            rec = client.run(f"MATCH (n:{label}) " + ("WHERE n.patient_id = $pid " if patient_id else "") +
                             "RETURN count(n) AS c", pid=patient_id)
            out[etype] = {"postgres": pg, "neo4j": rec[0]["c"], "in_sync": pg == rec[0]["c"]}
    finally:
        conn.close()
    return out


def purge_patient(patient_id: int) -> None:
    """Remove every mirrored node of a patient (used when a patient is deleted)."""
    client.run("MATCH (n {patient_id: $pid}) DETACH DELETE n", pid=patient_id)
    client.run("MATCH (p:Patient {pg_id: $pid}) DETACH DELETE p", pid=patient_id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "drain"
    if cmd == "backfill":
        print("enqueued", backfill_enqueue(), "->", drain_all())
    elif cmd == "drain":
        print(drain_all())
    elif cmd == "reconcile":
        for k, v in reconcile().items():
            print(k, v)
    else:
        raise SystemExit("usage: python -m services.graph.sync [backfill|drain|reconcile]")
