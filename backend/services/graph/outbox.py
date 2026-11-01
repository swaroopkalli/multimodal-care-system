"""Transactional outbox: record 'this row needs mirroring into Neo4j' in the same transaction as the write."""

ENTITY_TYPES = {"note", "turn", "journal", "window", "anomaly", "medication"}


def enqueue(cursor, entity_type: str, entity_id: int, patient_id: int, op: str = "upsert") -> None:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown entity_type {entity_type!r}")
    cursor.execute(
        "INSERT INTO graph_sync_outbox (entity_type, entity_id, patient_id, op) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (entity_type, entity_id, op) WHERE status = 'pending' DO NOTHING",
        (entity_type, entity_id, patient_id, op),
    )
