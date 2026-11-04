"""Tiny check runner: PASS / FAIL / SKIP with timing, service probes and synthetic-data fixtures.

All fixture data is marked with the ``__bt_`` username prefix and removed in ``finally``.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
for p in (str(BACKEND), str(BACKEND / "wearable_ingestion")):
    if p not in sys.path:
        sys.path.insert(0, p)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
MARK = "__bt_"
PASSWORD = "synthetic-pass-1"          # synthetic accounts only


class Skip(Exception):
    """Raised by a check to report SKIP (e.g. optional service unavailable)."""


@dataclass
class Check:
    area: str
    name: str
    fn: object
    needs: tuple = ()


REGISTRY: list[Check] = []


def check(area: str, needs: tuple = ()):
    def deco(fn):
        REGISTRY.append(Check(area, fn.__name__.replace("_", " "), fn, needs))
        return fn
    return deco


# ------------------------------------------------------------------- service probes
_probe_cache: dict[str, tuple[bool, str]] = {}
REQUIRED_SERVICES = {"postgres"}      # unavailable => FAIL; every other service is optional => SKIP (unless --strict)


def probe(service: str) -> tuple[bool, str]:
    """Check a service, retrying transient failures (the hosted PostgreSQL pooler occasionally drops a connection)."""
    if service in _probe_cache and _probe_cache[service][0]:
        return _probe_cache[service]
    result = (False, "")
    for attempt in range(3):
        result = _probe_once(service)
        if result[0]:
            break
        time.sleep(2 * (attempt + 1))
    _probe_cache[service] = result
    return result


def _probe_once(service: str) -> tuple[bool, str]:
    try:
        if service == "postgres":
            from db import get_db_connection
            c = get_db_connection(); c.cursor().execute("SELECT 1"); c.close()
        elif service == "redis":
            import redis
            redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"), port=int(os.getenv("REDIS_PORT", "6379")),
                        socket_connect_timeout=3).ping()
        elif service == "neo4j":
            from services.graph import client
            if not client.ping():
                raise RuntimeError("bolt connection failed")
        elif service in ("llm", "nvidia"):
            from services.llm import is_nvidia_configured
            if not is_nvidia_configured():
                raise RuntimeError("NVIDIA_API_KEY is not configured")
            from services.llm import chat, embed_texts
            if not chat([{"role": "user", "content": "ping"}]):
                raise RuntimeError("NVIDIA chat model returned empty response")
            vectors = embed_texts(["connectivity probe"], input_type="query")
            from services.graph.client import EMBED_DIMENSIONS
            if not vectors or len(vectors[0]) != EMBED_DIMENSIONS:
                raise RuntimeError("NVIDIA embedding model returned an invalid vector")
        return (True, "")
    except Exception as exc:
        return (False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:120] if str(exc) else ''}")


# ------------------------------------------------------------------------- fixtures
@dataclass
class World:
    """Synthetic doctor / caretaker / two patients, created in PostgreSQL and removed afterwards."""
    doctor_id: int = 0
    caretaker_id: int = 0
    other_doctor_id: int = 0
    patient_a: int = 0
    patient_b: int = 0
    names: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def cleanup_marked() -> None:
    """Remove synthetic rows (username starting with the marker) from PostgreSQL, Neo4j and Redis."""
    from db import get_db_connection
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM patients WHERE username LIKE %s", (MARK.replace("_", "\\_") + "%",))
        pids = [r["id"] for r in cur.fetchall()]
        if pids:
            cur.execute("DELETE FROM graph_sync_outbox WHERE patient_id = ANY(%s)", (pids,))
            cur.execute("DELETE FROM patients WHERE id = ANY(%s)", (pids,))
        cur.execute("DELETE FROM doctors WHERE username LIKE %s", (MARK.replace("_", "\\_") + "%",))
        cur.execute("DELETE FROM caretakers WHERE username LIKE %s", (MARK.replace("_", "\\_") + "%",))
        conn.commit()
    finally:
        conn.close()
    if pids:
        if probe("neo4j")[0]:
            from services.graph import sync
            for pid in pids:
                sync.purge_patient(pid)
        if probe("redis")[0]:
            import redis
            r = redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"), port=int(os.getenv("REDIS_PORT", "6379")))
            for pid in pids:
                for k in r.scan_iter(f"patient:{pid}:*"):
                    r.delete(k)


@contextmanager
def world():
    """Create the synthetic world through the real registration/login API, yield it, then clean up."""
    import app as backend
    client = backend.app.test_client()
    w = World()
    t = _tag()
    try:
        def reg(role, name, extra=None):
            body = {"username": f"{MARK}{role}_{name}_{t}", "name": f"BT {role} {name}", "password": PASSWORD, **(extra or {})}
            r = client.post(f"/api/auth/register/{role}", json=body)
            assert r.status_code == 201, f"register {role} failed: {r.status_code} {r.get_json()}"
            return r.get_json()["user"]["id"], body["username"]

        w.doctor_id, dname = reg("doctor", "a")
        w.other_doctor_id, odname = reg("doctor", "b")
        w.caretaker_id, cname = reg("caretaker", "a")
        w.patient_a, aname = reg("patient", "a", {"doctor_username": dname, "caretaker_username": cname})
        w.patient_b, bname = reg("patient", "b", {"doctor_username": odname})
        w.names = {"doctor": dname, "other_doctor": odname, "caretaker": cname, "patient_a": aname, "patient_b": bname}
        for key, role in (("doctor", "doctor"), ("other_doctor", "doctor"), ("caretaker", "caretaker"),
                          ("patient_a", "patient"), ("patient_b", "patient")):
            r = client.post(f"/api/auth/login/{role}", json={"username": w.names[key], "password": PASSWORD})
            assert r.status_code == 200, f"login {key} failed: {r.status_code}"
            w.tokens[key] = r.get_json()["token"]
        yield w, client
    finally:
        try:
            cleanup_marked()
        except Exception as exc:                                  # never hide the original failure
            print(f"  ! cleanup error: {type(exc).__name__}: {exc}", file=sys.stderr)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------------- running
def run_checks(selected: list[Check], strict: bool = False) -> int:
    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    failures = []
    area = None
    for c in selected:
        if c.area != area:
            area = c.area
            print(f"\n== {area}")
        started = time.time()
        status, detail = "PASS", ""
        missing = [(s, probe(s)[1]) for s in c.needs if not probe(s)[0]]
        if missing:
            required_down = any(s in REQUIRED_SERVICES for s, _ in missing)
            status = "FAIL" if (strict or required_down) else "SKIP"
            detail = "; ".join(f"{s} unavailable ({why})" for s, why in missing)
            if status == "FAIL":
                failures.append((c, "required service unavailable: " + detail))
        else:
            try:
                c.fn()
            except Skip as exc:
                status, detail = "SKIP", str(exc)
            except AssertionError as exc:
                status, detail = "FAIL", f"{exc}"
                failures.append((c, traceback.format_exc()))
            except Exception as exc:
                status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
                failures.append((c, traceback.format_exc()))
        counts[status] += 1
        print(f"  {status:<4} {c.name}  ({time.time() - started:.1f}s)" + (f"\n         {detail}" if detail else ""))
    if failures:
        print("\n" + "=" * 70 + "\nFAILURE DETAILS")
        for c, tb in failures:
            print(f"\n[{c.area}] {c.name}\n{tb}")
    print("\n" + "=" * 70)
    print(f"SUMMARY: {counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped "
          f"({sum(counts.values())} checks)")
    return 1 if counts["FAIL"] else 0
