"""10. End-to-end patient workflow across API, PostgreSQL, Redis, Neo4j and Ollama (real model)."""

import json
import uuid
from datetime import datetime, timedelta, timezone

from .framework import auth, check, world
from .t02_ingestion import make_event, redis_client
from .t04_history_anomaly import seed_history


@check("10. End to end", needs=("postgres", "redis", "neo4j", "ollama"))
def full_patient_workflow_register_ingest_retrieve_chat_guard_and_remember():
    from db import get_db_connection
    from services import wearable_analytics as wa
    from services import wearables
    from services.graph import client as gclient, sync

    r = redis_client()
    stream, group = f"wearable:test:{uuid.uuid4().hex[:8]}", "e2e"
    with world() as (w, client):
        doc, pat, ct = auth(w.tokens["doctor"]), auth(w.tokens["patient_a"]), auth(w.tokens["caretaker"])

        # 1. clinician context + patient self-reports
        assert client.post("/api/medications", json={"patient_id": w.patient_a, "name": "sertraline", "type": "SSRI", "duration": 90},
                           headers=doc).status_code == 201
        assert client.post("/api/doctor_notes", json={"patient_id": w.patient_a,
                           "note": "Patient reports persistent insomnia and low mood over recent weeks."}, headers=doc).status_code == 201
        assert client.post("/api/patient/journal", json={"entry": "I wake at 3am most nights and cannot get back to sleep."},
                           headers=pat).status_code == 201
        assert client.post("/api/patient/checkin", json={"mood": 2, "stress": 8, "sleep_hours": 4, "energy": 3,
                           "side_effects": ["Nausea"]}, headers=pat).status_code == 201
        assert client.post("/api/caretaker/observations", json={"patient_id": w.patient_a, "restless": True,
                           "medication_confirmed": True}, headers=ct).status_code == 201

        # 2. wearable history (synthetic) with a sleep drop, plus live events through the Redis Stream
        conn = get_db_connection()
        seed_history(conn, w.patient_a, days=20, anomaly_sleep=150)
        wearables.ensure_group(r, stream, group)
        base = datetime.now(timezone.utc) - timedelta(minutes=5)
        for i in range(10):
            r.xadd(stream, {"data": json.dumps(make_event(w.patient_a, i, 74 + i % 3, base=base, sleep_minutes=150))})
        stats = wearables.consume_batch(r, conn, stream, group, "e2e", count=50, block_ms=200)
        assert stats["stored"] == 10, stats
        wa.rollup_patient(conn, w.patient_a)
        anomalies = wa.detect_anomalies(conn, w.patient_a, days_back=3)
        conn.close()
        assert any(a["signal"] == "sleep" for a in anomalies), anomalies

        # 3. live vitals via the API (Redis-backed)
        live = client.get(f"/api/patients/{w.patient_a}/vitals/live", headers=pat).get_json()
        assert live["latest"]["source"] == "redis" and live["latest"]["is_simulated"] is True and len(live["recent"]) == 10

        # 4. graph sync, then a retrieval-grounded staff summary
        assert sync.drain_all()["done"] >= 4
        staff = client.post("/api/staff/chat", json={"patient_id": w.patient_a, "query": "Give me a concise summary of this patient's sleep and mood."}, headers=doc)
        body = staff.get_json()
        assert staff.status_code == 200 and body["response"].strip(), body
        assert body["guardrail"]["action"] in ("allowed", "fallback") and body["retrieval"]["status"] == "ok", body
        assert body["usage"]["truncated"] is False

        # 5. patient chat: allowed message with a medication + side effect is NOT blocked at the input stage
        ok = client.post("/api/patient/chat", json={"query": "I take sertraline and I feel nauseous in the mornings. I also sleep badly."}, headers=pat)
        ok_body = ok.get_json()
        assert ok.status_code == 200 and ok_body["guardrail"].get("stage") == "output", ok_body      # passed input validation
        assert ok_body["response"].strip()

        # 6. medication request is refused before reaching the model, and crisis language is routed to support
        refused = client.post("/api/patient/chat", json={"query": "What dose of sertraline should I take?"}, headers=pat).get_json()
        assert refused["guardrail"]["action"] == "refused" and refused["guardrail"]["category"] == "medication_request"
        crisis = client.post("/api/patient/chat", json={"query": "I want to end my life"}, headers=pat).get_json()
        assert crisis["guardrail"]["action"] == "crisis"

        # 7. the vetted exchange became memory; refused/crisis turns did not
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT role, query FROM chatbot_logs WHERE patient_id=%s ORDER BY id", (w.patient_a,))
        logged = [x["query"] for x in cur.fetchall()]
        assert any("sertraline and I feel nauseous" in q for q in logged)
        assert not any("What dose" in q or "end my life" in q for q in logged), "refused/crisis turns must not enter memory"
        cur.execute("SELECT action, stage FROM guardrail_events WHERE patient_id=%s", (w.patient_a,))
        events = {(x["action"], x["stage"]) for x in cur.fetchall()}
        assert ("refused", "input") in events and ("crisis", "input") in events
        conn.close()

        # 8. the conversation turn is mirrored to the graph for future retrieval
        sync.drain_all()
        turns = gclient.run("MATCH (:Patient {pg_id:$p})-[:HAD_TURN]->(t:ConversationTurn) RETURN count(t) AS c", p=w.patient_a)[0]["c"]
        assert turns >= 1
        r.delete(stream)
