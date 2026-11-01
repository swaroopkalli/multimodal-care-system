"""Neo4j connection and schema (constraints + vector indexes)."""

from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)

EMBED_DIMENSIONS = int(os.getenv("EMBED_DIMENSIONS", "768"))   # nomic-embed-text

# entity type -> graph label, relationship from Patient, vector index name (None = not embedded)
ENTITIES = {
    "note": {"label": "ClinicalNote", "rel": "HAS_NOTE", "index": "note_embedding"},
    "turn": {"label": "ConversationTurn", "rel": "HAD_TURN", "index": "turn_embedding"},
    "journal": {"label": "JournalEntry", "rel": "HAS_JOURNAL", "index": "journal_embedding"},
    "window": {"label": "WearableWindow", "rel": "HAS_WINDOW", "index": "window_embedding"},
    "anomaly": {"label": "Anomaly", "rel": "HAS_ANOMALY", "index": None},
    "medication": {"label": "Medication", "rel": "TAKES", "index": None},
}

_driver = None
_lock = threading.RLock()
_schema_ready = False


class GraphUnavailable(RuntimeError):
    """Neo4j (or the embedding model feeding it) cannot be used right now."""


def get_driver():
    global _driver
    with _lock:
        if _driver is None:
            from neo4j import GraphDatabase
            uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
            user, password = os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")
            if not password:
                raise GraphUnavailable("NEO4J_PASSWORD is not set")
            _driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=5,
                                           max_connection_lifetime=1800, notifications_min_severity="OFF")
        return _driver


def close_driver() -> None:
    global _driver, _schema_ready
    with _lock:
        if _driver is not None:
            _driver.close()
        _driver, _schema_ready = None, False


def run(query: str, **params):
    """Run a Cypher statement and return its records. Maps driver failures to GraphUnavailable."""
    try:
        driver = get_driver()
        ensure_schema()
        records, _, _ = driver.execute_query(query, parameters_=params, database_="neo4j")
        return records
    except GraphUnavailable:
        raise
    except Exception as exc:
        raise GraphUnavailable(f"Neo4j error: {type(exc).__name__}: {str(exc)[:200]}") from exc


def ping() -> bool:
    try:
        get_driver().verify_connectivity()
        return True
    except Exception:
        return False


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _lock:
        if _schema_ready:
            return
        driver = get_driver()
        for spec in ENTITIES.values():
            label = spec["label"]
            driver.execute_query(
                f"CREATE CONSTRAINT {label.lower()}_pg_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.pg_id IS UNIQUE",
                database_="neo4j")
            if spec["index"]:
                driver.execute_query(
                    f"CREATE VECTOR INDEX {spec['index']} IF NOT EXISTS FOR (n:{label}) ON (n.embedding) "
                    f"OPTIONS {{indexConfig: {{`vector.dimensions`: {EMBED_DIMENSIONS}, "
                    f"`vector.similarity_function`: 'cosine'}}}}", database_="neo4j")
        driver.execute_query("CREATE CONSTRAINT patient_pg_id IF NOT EXISTS FOR (p:Patient) REQUIRE p.pg_id IS UNIQUE",
                             database_="neo4j")
        for spec in ENTITIES.values():                    # per-patient lookups
            driver.execute_query(
                f"CREATE INDEX {spec['label'].lower()}_patient IF NOT EXISTS FOR (n:{spec['label']}) ON (n.patient_id)",
                database_="neo4j")
        driver.execute_query("CALL db.awaitIndexes(60)", database_="neo4j")
        records, _, _ = driver.execute_query(
            "SHOW VECTOR INDEXES YIELD name, options RETURN name, options", database_="neo4j")
        for rec in records:
            dims = rec["options"].get("indexConfig", {}).get("vector.dimensions")
            if dims is not None and int(dims) != EMBED_DIMENSIONS:
                raise GraphUnavailable(
                    f"Vector index {rec['name']} has {dims} dimensions but EMBED_DIMENSIONS={EMBED_DIMENSIONS}; "
                    "drop the index or re-embed with the matching model")
        _schema_ready = True
