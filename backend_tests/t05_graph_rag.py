"""5. Embeddings + Neo4j storage + vector retrieval.  6. Patient-specific RAG / isolation."""

from datetime import datetime, timezone

from .framework import check, world


def _add_note(client, token, patient_id, text):
    r = client.post("/api/doctor_notes", json={"patient_id": patient_id, "note": text}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["note_id"]


@check("5. Embeddings / vector retrieval", needs=("nvidia",))
def embeddings_have_the_expected_size_and_capture_meaning():
    import math
    from services.graph.embeddings import embed_document, embed_query
    a = embed_query("I can't fall asleep at night")
    b = embed_document("Patient reports severe insomnia and wakes repeatedly during the night.")
    c = embed_document("The football match ended with a two-one score.")
    cos = lambda x, y: sum(p * q for p, q in zip(x, y)) / (math.sqrt(sum(p * p for p in x)) * math.sqrt(sum(q * q for q in y)))
    from services.graph.client import EMBED_DIMENSIONS
    assert len(a) == EMBED_DIMENSIONS and cos(a, b) > cos(a, c) + 0.1, (cos(a, b), cos(a, c))


@check("5. Embeddings / vector retrieval", needs=("postgres", "neo4j", "nvidia"))
def notes_sync_to_neo4j_and_are_found_by_meaning_via_the_vector_index():
    from services.graph import client as gclient, retrieval, sync
    with world() as (w, client):
        n1 = _add_note(client, w.tokens["doctor"], w.patient_a, "Patient describes severe insomnia, lying awake most of the night.")
        _add_note(client, w.tokens["doctor"], w.patient_a, "Patient enjoys weekend hiking and reports stable appetite.")
        assert sync.drain_all()["done"] >= 2
        rows = gclient.run("MATCH (p:Patient {pg_id:$p})-[:HAS_NOTE]->(n:ClinicalNote) RETURN count(n) AS c, "
                           "count(n.embedding) AS e", p=w.patient_a)
        assert rows[0]["c"] == 2 and rows[0]["e"] == 2, "both notes mirrored with embeddings"
        # vector INDEX path (db.index.vector.queryNodes) returns the semantically closest note first
        top = retrieval.retrieve(w.patient_a, "trouble sleeping at night", kinds=("note",), k=2)
        assert top and top[0]["id"] == n1 and top[0]["kind"] == "note", [t["text"][:40] for t in top]
        # idempotent re-sync (replays must not duplicate)
        from services.graph.outbox import enqueue
        from db import get_db_connection
        conn = get_db_connection(); cur = conn.cursor(); enqueue(cur, "note", n1, w.patient_a); conn.commit(); conn.close()
        sync.drain_all()
        rows = gclient.run("MATCH (n:ClinicalNote {pg_id:$id}) RETURN count(n) AS c", id=n1)
        assert rows[0]["c"] == 1
        rec = sync.reconcile(w.patient_a)["note"]
        assert rec["in_sync"], rec


@check("6. Patient-specific RAG", needs=("postgres", "neo4j", "nvidia"))
def retrieval_never_returns_another_patients_information():
    from services.graph import retrieval, sync
    secret_b = "Zebra-Quartz confidential detail about patient B only"
    with world() as (w, client):
        _add_note(client, w.tokens["doctor"], w.patient_a, "Patient A reports trouble sleeping and racing thoughts.")
        _add_note(client, w.tokens["other_doctor"], w.patient_b, f"Patient B trouble sleeping; {secret_b}.")
        sync.drain_all()
        for pid, other in ((w.patient_a, "Zebra-Quartz"), (w.patient_b, "racing thoughts")):
            for q in ("trouble sleeping", "confidential detail", "racing thoughts", other):
                items = retrieval.retrieve(pid, q, kinds=("note", "turn", "journal", "window"), k=5)
                blob = " ".join(i["text"] for i in items)
                if pid == w.patient_a:
                    assert "Zebra-Quartz" not in blob, f"patient A retrieval leaked B's note for query {q!r}"
                else:
                    assert "racing thoughts" not in blob, f"patient B retrieval leaked A's note for query {q!r}"
        # PostgreSQL hydration is an independent second barrier
        a_items = retrieval.retrieve(w.patient_a, "trouble sleeping", kinds=("note",), k=3)
        assert a_items
        assert retrieval._hydrate(w.patient_b, a_items) == [], "hydrating A's ids under B's id must return nothing"


@check("6. Patient-specific RAG", needs=("postgres", "neo4j", "nvidia"))
def patients_do_not_see_clinician_notes_but_staff_do():
    from services.graph import retrieval, sync
    with world() as (w, client):
        _add_note(client, w.tokens["doctor"], w.patient_a, "Clinician-only observation about low mood and poor sleep.")
        r = client.post("/api/patient/journal", json={"entry": "My sleep has been terrible and my mood is low."},
                        headers={"Authorization": f"Bearer {w.tokens['patient_a']}"})
        assert r.status_code == 201
        sync.drain_all()
        patient_items = retrieval.retrieve(w.patient_a, "poor sleep low mood", kinds=retrieval.KINDS_PATIENT, k=5)
        staff_items = retrieval.retrieve(w.patient_a, "poor sleep low mood", kinds=retrieval.KINDS_STAFF, k=5)
        assert not any(i["kind"] == "note" for i in patient_items) and any(i["kind"] == "journal" for i in patient_items)
        assert any(i["kind"] == "note" for i in staff_items)


@check("6. Patient-specific RAG", needs=("postgres", "neo4j", "nvidia"))
def deleted_source_rows_disappear_from_the_graph():
    from db import get_db_connection
    from services.graph import client as gclient, sync
    from services.graph.outbox import enqueue
    with world() as (w, client):
        nid = _add_note(client, w.tokens["doctor"], w.patient_a, "Temporary note to be removed.")
        sync.drain_all()
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("DELETE FROM doctor_notes WHERE id=%s", (nid,)); enqueue(cur, "note", nid, w.patient_a); conn.commit(); conn.close()
        sync.drain_all()
        assert gclient.run("MATCH (n:ClinicalNote {pg_id:$id}) RETURN count(n) AS c", id=nid)[0]["c"] == 0
