"""Conversation memory: newest turns first, bounded by a token budget (never mid-text truncation)."""

from __future__ import annotations

from db import get_db_connection
from services.budget import estimate_tokens

HISTORY_FETCH_LIMIT = 40


def load_history(patient_id: int, role: str, budget_tokens: int):
    """Return (turns, ids): chat turns in chronological order, taking the NEWEST turns that fit ``budget_tokens``.

    A turn is included whole or not at all. Older turns beyond the budget stay in
    ``chatbot_logs`` and remain reachable through Neo4j retrieval.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, query, response FROM chatbot_logs WHERE patient_id = %s AND role = %s "
            "AND response <> '' ORDER BY id DESC LIMIT %s",
            (patient_id, role, HISTORY_FETCH_LIMIT),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    chosen, used = [], 0
    for row in rows:                                    # newest first
        cost = estimate_tokens(row["query"]) + estimate_tokens(row["response"])
        if used + cost > budget_tokens:
            break                                       # keep recency contiguous; stop at first non-fit
        chosen.append(row)
        used += cost
    history: list[dict] = []
    for row in reversed(chosen):
        history.append({"role": "user", "parts": [row["query"]]})
        history.append({"role": "model", "parts": [row["response"]]})
    return history, {row["id"] for row in chosen}
