"""Patient-scoped retrieval from Neo4j, hydrated from PostgreSQL.

Isolation is enforced three times: (1) every Cypher statement filters on the verified
patient_id, (2) the vector search over-fetches and post-filters, with an exact
per-patient fallback so small patients are never starved, (3) texts are re-read from
PostgreSQL with `patient_id = %s`, so a mismatched id cannot surface foreign content.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from db import get_db_connection
from services.budget import estimate_tokens
from services.graph import client
from services.graph.client import ENTITIES, GraphUnavailable
from services.graph.embeddings import embed_query, model_name
from services.graph.sync import window_text

OVERFETCH = 10
HALF_LIFE_DAYS = {"note": 90.0, "journal": 30.0, "turn": 14.0, "window": 30.0}
W_SIM, W_REC, W_IMP = 0.7, 0.2, 0.1
KINDS_STAFF = ("note", "journal", "turn", "window")
KINDS_PATIENT = ("journal", "turn", "window")          # patients are not shown clinician notes


def _recency(kind: str, created_iso: str | None, now: datetime) -> float:
    if not created_iso:
        return 0.5
    try:
        created = datetime.fromisoformat(created_iso)
    except ValueError:
        return 0.5
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created).total_seconds() / 86400)
    return 0.5 ** (age_days / HALF_LIFE_DAYS[kind])


def _search_kind(kind: str, patient_id: int, vector: list[float], k: int) -> list[dict]:
    spec = ENTITIES[kind]
    label, rel, index = spec["label"], spec["rel"], spec["index"]
    embedding_model = model_name()
    rows = client.run(
        "CALL db.index.vector.queryNodes($index, $k, $vec) YIELD node, score "
        "WHERE node.patient_id = $pid AND node.embedding_model = $model "
        "RETURN node.pg_id AS id, node.created_at AS created, node.importance AS importance, score "
        "ORDER BY score DESC LIMIT $limit", index=index, k=k * OVERFETCH, vec=vector, pid=patient_id,
        model=embedding_model, limit=k)
    found = {r["id"]: r for r in rows}
    if len(found) < k:           # exact scan inside this patient's own subgraph
        exact = client.run(
            f"MATCH (:Patient {{pg_id: $pid}})-[:{rel}]->(n:{label}) "
            "WHERE n.embedding IS NOT NULL AND n.embedding_model = $model "
            "WITH n, vector.similarity.cosine(n.embedding, $vec) AS score ORDER BY score DESC LIMIT $limit "
            "RETURN n.pg_id AS id, n.created_at AS created, n.importance AS importance, score",
            pid=patient_id, vec=vector, model=embedding_model, limit=k)
        for r in exact:
            found.setdefault(r["id"], r)
    return [{"kind": kind, "id": r["id"], "similarity": float(r["score"]), "created": r["created"],
             "importance": float(r["importance"] or 0.5)} for r in found.values()]


def _hydrate(patient_id: int, items: list[dict]) -> list[dict]:
    """Attach text from PostgreSQL, always constrained to the patient."""
    by_kind: dict[str, list[int]] = {}
    for it in items:
        by_kind.setdefault(it["kind"], []).append(it["id"])
    texts: dict[tuple[str, int], str] = {}
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if "note" in by_kind:
            cur.execute("SELECT id, note, created_at FROM doctor_notes WHERE patient_id=%s AND id = ANY(%s)",
                        (patient_id, by_kind["note"]))
            texts.update({("note", r["id"]): f"[doctor note {r['created_at']:%Y-%m-%d}] {r['note']}" for r in cur.fetchall()})
        if "journal" in by_kind:
            cur.execute("SELECT id, entry, created_at FROM journal_entries WHERE patient_id=%s AND id = ANY(%s)",
                        (patient_id, by_kind["journal"]))
            texts.update({("journal", r["id"]): f"[patient journal {r['created_at']:%Y-%m-%d}] {r['entry']}" for r in cur.fetchall()})
        if "turn" in by_kind:
            cur.execute("SELECT id, role, query, response, created_at FROM chatbot_logs WHERE patient_id=%s AND id = ANY(%s)",
                        (patient_id, by_kind["turn"]))
            texts.update({("turn", r["id"]): f"[earlier conversation {r['created_at']:%Y-%m-%d}] patient said: {r['query']}"
                          for r in cur.fetchall()})
        if "window" in by_kind:
            cur.execute("SELECT * FROM wearable_daily WHERE patient_id=%s AND id = ANY(%s)", (patient_id, by_kind["window"]))
            texts.update({("window", r["id"]): f"[{window_text(r)}]" for r in cur.fetchall()})
    finally:
        conn.close()
    out = []
    for it in items:
        text = texts.get((it["kind"], it["id"]))
        if text:                                      # drops anything PostgreSQL does not confirm for this patient
            out.append({**it, "text": text})
    return out


def retrieve(patient_id: int, query: str, kinds=KINDS_STAFF, k: int = 4, now: datetime | None = None) -> list[dict]:
    """Return ranked, hydrated items (best first) for ONE verified patient. Raises GraphUnavailable."""
    if not isinstance(patient_id, int) or isinstance(patient_id, bool) or patient_id <= 0:
        raise ValueError("patient_id must be a positive integer")
    if not query or not query.strip():
        return []
    now = now or datetime.now(timezone.utc)
    vector = embed_query(query, patient_id)
    candidates: list[dict] = []
    for kind in kinds:
        candidates += _search_kind(kind, patient_id, vector, k)
    for c in candidates:
        c["score"] = W_SIM * c["similarity"] + W_REC * _recency(c["kind"], c["created"], now) + W_IMP * c["importance"]
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return _hydrate(patient_id, candidates[: k * 2])


def select_within_budget(items: list[dict], token_budget: int) -> list[dict]:
    """Take best-scoring items whole until the budget is spent (no mid-text cuts)."""
    chosen, used = [], 0
    for it in items:
        cost = estimate_tokens(it["text"])
        if used + cost <= token_budget:
            chosen.append(it)
            used += cost
    return chosen
