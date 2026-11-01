"""9. Authentication, authorization and patient-data isolation."""

from .framework import MARK, PASSWORD, auth, check, world


@check("9. Auth / isolation", needs=("postgres",))
def login_succeeds_with_a_valid_token_and_fails_cleanly_otherwise():
    with world() as (w, client):
        r = client.post("/api/auth/login/patient", json={"username": w.names["patient_a"], "password": PASSWORD})
        body = r.get_json()
        assert r.status_code == 200 and body["user"]["role"] == "patient" and body["user"]["id"] == w.patient_a
        assert client.post("/api/auth/login/patient", json={"username": w.names["patient_a"], "password": "wrong-password"}).status_code == 401
        assert client.post("/api/auth/login/patient", json={"username": "no-such-user", "password": PASSWORD}).status_code == 401
        assert client.post("/api/auth/login/patient", json={"username": w.names["patient_a"]}).status_code == 400, "missing password"
        assert client.post("/api/auth/login/doctor", json={"username": w.names["patient_a"], "password": PASSWORD}).status_code == 401, \
            "a patient's credentials must not work on the doctor login"
        dup = client.post("/api/auth/register/patient", json={"username": w.names["patient_a"], "name": "x", "password": PASSWORD})
        assert dup.status_code == 409
        weak = client.post("/api/auth/register/patient", json={"username": MARK + "weak", "name": "x", "password": "short"})
        assert weak.status_code == 400


@check("9. Auth / isolation", needs=("postgres",))
def protected_routes_reject_missing_invalid_and_forged_tokens():
    import jwt as pyjwt
    with world() as (w, client):
        paths = [("get", f"/api/doctor_notes/{w.patient_a}"), ("get", f"/api/wearables_data/{w.patient_a}"),
                 ("get", "/api/patients"), ("post", "/api/patient/chat"), ("post", "/api/staff/chat"),
                 ("post", "/api/doctor_notes"), ("post", "/api/patient/checkin"), ("get", f"/api/patients/{w.patient_a}/summary")]
        for method, path in paths:
            assert getattr(client, method)(path).status_code == 401, f"{path} reachable without a token"
        bad = {"Authorization": "Bearer not.a.token"}
        assert client.get("/api/patients", headers=bad).status_code == 401
        forged = pyjwt.encode({"sub": str(w.patient_a), "role": "doctor", "type": "access", "fresh": False,
                               "jti": "x", "iat": 0, "nbf": 0, "exp": 9999999999}, "guessed-secret-guessed-secret-123456", algorithm="HS256")
        assert client.get("/api/patients", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


@check("9. Auth / isolation", needs=("postgres",))
def roles_are_enforced():
    with world() as (w, client):
        pa, doc, ct = auth(w.tokens["patient_a"]), auth(w.tokens["doctor"]), auth(w.tokens["caretaker"])
        assert client.post("/api/doctor_notes", json={"patient_id": w.patient_a, "note": "x"}, headers=pa).status_code == 403
        assert client.post("/api/doctor_notes", json={"patient_id": w.patient_a, "note": "x"}, headers=ct).status_code == 403
        assert client.post("/api/patient/chat", json={"query": "hello"}, headers=doc).status_code == 403
        assert client.post("/api/staff/chat", json={"patient_id": w.patient_a, "query": "hello"}, headers=pa).status_code == 403
        assert client.post("/api/medications", json={"patient_id": w.patient_a, "name": "x", "type": "t", "duration": 5}, headers=ct).status_code == 403
        assert client.post("/api/caretaker/observations", json={"patient_id": w.patient_a}, headers=doc).status_code == 403
        assert client.get(f"/api/doctor_notes/{w.patient_a}", headers=pa).status_code == 403, "patients cannot read clinician notes"


@check("9. Auth / isolation", needs=("postgres",))
def staff_access_is_limited_to_assigned_patients():
    with world() as (w, client):
        doc, other = auth(w.tokens["doctor"]), auth(w.tokens["other_doctor"])
        ct = auth(w.tokens["caretaker"])
        assert client.get(f"/api/doctor_notes/{w.patient_a}", headers=doc).status_code == 200
        assert client.get(f"/api/doctor_notes/{w.patient_b}", headers=doc).status_code == 403, "doctor A must not read patient B"
        assert client.get(f"/api/doctor_notes/{w.patient_a}", headers=other).status_code == 403
        assert client.post("/api/doctor_notes", json={"patient_id": w.patient_b, "note": "sneaky"}, headers=doc).status_code == 403
        assert client.post("/api/staff/chat", json={"patient_id": w.patient_b, "query": "summary"}, headers=doc).status_code == 403
        assert client.get(f"/api/patients/{w.patient_b}/summary", headers=ct).status_code == 403, "caretaker is only assigned to A"
        assert client.get(f"/api/patients/{w.patient_a}/summary", headers=ct).status_code == 200
        assert client.get(f"/api/wearables_data/{w.patient_b}", headers=doc).status_code == 403
        listed = client.get("/api/patients", headers=doc).get_json()["patients"]
        assert [p["id"] for p in listed] == [w.patient_a], listed
        assert [p["id"] for p in client.get("/api/patients", headers=auth(w.tokens["patient_b"])).get_json()["patients"]] == [w.patient_b]


@check("9. Auth / isolation", needs=("postgres",))
def patients_only_ever_touch_their_own_data_even_if_they_name_another_id():
    from db import get_db_connection
    with world() as (w, client):
        pa = auth(w.tokens["patient_a"])
        assert client.get(f"/api/wearables_data/{w.patient_b}", headers=pa).status_code == 403
        assert client.get(f"/api/patients/{w.patient_b}/summary", headers=pa).status_code == 403
        r = client.post("/api/patient/journal", json={"entry": "mine only", "patient_id": w.patient_b}, headers=pa)
        assert r.status_code == 201
        r = client.post("/api/patient/checkin", json={"mood": 3, "stress": 4, "sleep_hours": 6, "energy": 5,
                                                      "side_effects": ["Nausea"], "patient_id": w.patient_b}, headers=pa)
        assert r.status_code == 201
        conn = get_db_connection(); cur = conn.cursor()
        for table in ("journal_entries", "patient_checkins"):
            cur.execute(f"SELECT patient_id FROM {table} WHERE patient_id IN (%s,%s)", (w.patient_a, w.patient_b))
            assert {x["patient_id"] for x in cur.fetchall()} == {w.patient_a}, f"{table} row attributed to the wrong patient"
        conn.close()


@check("9. Auth / isolation", needs=("postgres",))
def note_author_comes_from_the_token_not_the_request_body():
    from db import get_db_connection
    with world() as (w, client):
        r = client.post("/api/doctor_notes", json={"patient_id": w.patient_a, "note": "authored", "doctor_id": w.other_doctor_id},
                        headers=auth(w.tokens["doctor"]))
        assert r.status_code == 201
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT doctor_id FROM doctor_notes WHERE id=%s", (r.get_json()["note_id"],))
        assert cur.fetchone()["doctor_id"] == w.doctor_id
        conn.close()


@check("9. Auth / isolation", needs=("postgres",))
def input_validation_rejects_bad_payloads_without_leaking_internals():
    with world() as (w, client):
        pa = auth(w.tokens["patient_a"])
        for path, body in (("/api/patient/checkin", {"mood": 99}), ("/api/patient/checkin", {"side_effects": "x"}),
                           ("/api/patient/journal", {"entry": "   "}), ("/api/patient/chat", {"query": ""}),
                           ("/api/patient/chat", {"query": 123}), ("/api/patient/chat", None)):
            r = client.post(path, json=body, headers=pa) if body is not None else client.post(path, data="not json", headers=pa)
            assert r.status_code == 400, (path, body, r.status_code)
            assert "Traceback" not in r.get_data(as_text=True) and "psycopg" not in r.get_data(as_text=True)
