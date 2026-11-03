"""1. Service and dependency connectivity."""

import os

from .framework import check, probe, Skip


@check("1. Connectivity", needs=("postgres",))
def postgresql_reachable_and_schema_current():
    from db import get_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        tables = {r["table_name"] for r in cur.fetchall()}
        needed = {"caretakers", "doctors", "patients", "medications", "wearable_data", "wearable_daily",
                  "wearable_anomalies", "doctor_notes", "patient_contexts", "chatbot_logs", "patient_checkins",
                  "journal_entries", "caretaker_observations", "guardrail_events", "graph_sync_outbox"}
        assert needed <= tables, f"missing tables: {sorted(needed - tables)} (run: python backend/db.py)"
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='wearable_data'")
        cols = {r["column_name"] for r in cur.fetchall()}
        assert {"is_simulated", "heartrate_ewma", "quality_flags", "event_id"} <= cols, "wearable_data not migrated"
    finally:
        conn.close()


@check("1. Connectivity", needs=("redis",))
def redis_reachable_with_streams():
    import redis
    r = redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"), port=int(os.getenv("REDIS_PORT", "6379")),
                    decode_responses=True)
    assert r.ping() is True
    assert tuple(int(x) for x in r.info("server")["redis_version"].split(".")[:2]) >= (5, 0), "Streams need Redis >= 5"


@check("1. Connectivity", needs=("neo4j",))
def neo4j_reachable_with_vector_indexes():
    from services.graph import client
    client.ensure_schema()
    rows = client.run("SHOW VECTOR INDEXES YIELD name, state RETURN name, state")
    states = {r["name"]: r["state"] for r in rows}
    for name in ("note_embedding", "turn_embedding", "journal_embedding", "window_embedding"):
        assert states.get(name) == "ONLINE", f"vector index {name} is {states.get(name)}"


@check("1. Connectivity", needs=("ollama",))
def ollama_chat_and_embedding_models_respond():
    from services import llm
    out = llm.chat_ex([{"role": "user", "content": "Reply with one word: ok"}], 0.0)
    assert out.content.strip(), "empty chat response"
    embed_model = os.getenv("NVIDIA_EMBED_MODEL") or os.getenv("LLM_EMBED_MODEL") or os.getenv("OLLAMA_EMBED_MODEL")
    if embed_model:
        vectors = llm.embed_texts(["connectivity probe"])
        if vectors:
            vec = vectors[0]
            expected = int(os.getenv("EMBED_DIMENSIONS", "768"))
            assert len(vec) == expected, f"embedding has {len(vec)} dims, expected {expected}"


@check("1. Connectivity")
def llm_configuration_is_consistent():
    from services import llm
    s = llm.context_settings()
    assert s["prompt_budget"] + s["response_reserve"] == s["num_ctx"]
    ratio = float(os.getenv("NVIDIA_PROMPT_BUDGET_RATIO") or os.getenv("LLM_PROMPT_BUDGET_RATIO") or os.getenv("OLLAMA_PROMPT_BUDGET_RATIO", "0.8"))
    assert abs(s["prompt_budget"] / s["num_ctx"] - ratio) < 0.01
    assert os.getenv("NVIDIA_MODEL") or os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL"), "LLM model not set"
    assert os.getenv("JWT_SECRET_KEY") and len(os.getenv("JWT_SECRET_KEY")) >= 32, "JWT_SECRET_KEY missing or short"
