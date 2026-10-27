# MindBridge – Wearable Data Ingestion Pipeline

> The ingestion processes remain independent from Flask routes and frontend
> code. They load configuration from the repository root `.env` (and may use
> an optional feature-local `.env` for missing settings); they do not alter
> either environment file.

---

## Overview

### Simulator behavior

`SIMULATOR_HEART_RATE_SCENARIO` supports `normal` (default), `elevated`, and
`low`. Heart rate follows a mean-reverting noisy series, so consecutive
measurements vary smoothly. These scenarios are synthetic and are not
clinically validated. `BEHAVIORAL_UPDATE_INTERVAL_SECONDS` defaults to
86400 seconds. Sleep is modeled as the last completed nightly session in
minutes and screen time as a synthetic daily aggregate in minutes; each
patient's values are reused in events until the interval changes. Both values
are still included in every event for compatibility. State lives in process
memory, so it is regenerated after a simulator restart. If a consumer needs
to distinguish stale aggregates from new measurements, that freshness is not
currently encoded in the event schema.

Run offline simulator unit checks with:

```bash
python -m unittest test_simulator.py
```

```
Mock Wearable Simulator
        |
        | TCP / redis-py PUBLISH wearable:vitals <JSON>
        v
Redis 7 (Docker – compose.yaml)
        |
        +──────────────────────────+
        |                          |
        v                          v
subscriber_postgres.py    subscriber_redis_cache.py
        |                          |
        v                          v
Supabase PostgreSQL       Redis hash
wearable_data table       patient:<id>:vitals:latest
(persistent history)      (rebuildable cache)
```

The three Python processes run independently. The existing Flask
application is not modified and does not need to be running.

---

## 1. Supabase Setup (New Project)

The previous Supabase project expired. No backup is available.
Follow these steps to create a fresh one.

### 1a – Create a new project

1. Go to <https://supabase.com/dashboard> and sign in.
2. Click **New project**.
3. Choose an organisation, enter a project name (e.g. `mindbridge-dev`),
   set a strong database password, and select a region close to you.
4. Click **Create new project** and wait ~2 minutes for provisioning.

### 1b – Get connection details

1. In the new project, go to **Project Settings → Database**.
2. Under **Connection string**, select **Transaction** mode.
   - Host: `db.<project-ref>.supabase.co`
   - Port: `6543`
   - User: `postgres.<project-ref>`
   - Database: `postgres`
3. Copy the password you set at project creation — it is not shown again.

### 1c – Run the schema

1. In the Supabase dashboard go to **SQL Editor**.
2. Paste the contents of `schema.sql` from this directory.
3. Click **Run**. Alternatively, run `python3 apply_schema.py` from this
   directory after activating the ingestion virtualenv; it reads the root `.env`.
4. Verify in **Table Editor** that all 8 tables exist and
   `wearable_data` has an `event_id` column.

### 1d – Why `event_id` is added

Older `wearable_data` tables may not have a deduplication field. The ingestion
pipeline needs one to safely re-process an in-memory event without creating
duplicate rows. The schema below and `backend/db.py` both add it compatibly.

`schema.sql` adds `event_id UUID` and a unique index with `IF NOT EXISTS`.

This is:
- **Additive** – existing rows get `NULL` and are unaffected.
- **Non-breaking** – the existing application's `INSERT` statements omit
  this column and continue to work; `NULL != NULL` in Postgres unique
  constraints, so those rows are not blocked.
- **Only applied to the new Supabase database**, not to any live instance.

---

## 2. Environment Setup

The processes automatically load the repository-root `.env`, which is the
recommended shared configuration. An optional `backend/wearable_ingestion/.env`
can provide feature-specific overrides. Shell-exported environment variables
take precedence over both. Never commit credentials.

Required variables (the current root `.env` already contains these):

| Variable | Example | Notes |
|---|---|---|
| `INGESTION_DB_HOST` | `db.abc123.supabase.co` | From Supabase dashboard |
| `INGESTION_DB_PORT` | `6543` | Transaction pooler |
| `INGESTION_DB_NAME` | `postgres` | Always `postgres` on Supabase |
| `INGESTION_DB_USER` | `postgres.abc123` | From Supabase dashboard |
| `INGESTION_DB_PASSWORD` | `…` | **Never commit this** |
| `INGESTION_DB_SSLMODE` | `require` | Supabase requires SSL |
| `REDIS_HOST` | `127.0.0.1` | Loopback – Redis runs in Docker |
| `REDIS_PORT` | `6379` | Matches compose.yaml |
| `REDIS_CHANNEL` | `wearable:vitals` | Pub/Sub channel name |
| `REDIS_CACHE_TTL_SECONDS` | `3600` | 0 = no expiry |
| `SIMULATOR_PATIENT_IDS` | `1` | Comma-separated; must exist in DB |
| `SIMULATOR_INTERVAL_SECONDS` | `5` | Seconds between published events |
| `SIMULATOR_DEVICE_ID` | `sim-device-001` | Label only |

---

## 3. Install Python Dependencies

Use an **isolated virtualenv** to avoid conflicts with the main app:

```bash
cd backend/wearable_ingestion
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 4. Start Redis

```bash
cd backend/wearable_ingestion

# Start (detached)
docker compose -f compose.yaml up -d

# Verify health
docker compose -f compose.yaml ps
# redis should show "healthy"

# View logs
docker compose -f compose.yaml logs -f redis

# Stop
docker compose -f compose.yaml down

# Restart
docker compose -f compose.yaml restart redis

# Check Redis directly
docker exec mindbridge_ingestion_redis redis-cli ping
# Expected: PONG
```

Redis is exposed only on `127.0.0.1:6379` — not accessible from the
network. Persistence is disabled intentionally (Pub/Sub is transient).

---

## 5. Run the Pipeline

Open **three separate terminals** (all with the virtualenv active).

**Terminal 1 – PostgreSQL subscriber**
```bash
cd backend/wearable_ingestion
source .venv/bin/activate
python subscriber_postgres.py
```

**Terminal 2 – Redis cache subscriber**
```bash
cd backend/wearable_ingestion
source .venv/bin/activate
python subscriber_redis_cache.py
```

**Terminal 3 – Simulator**
```bash
cd backend/wearable_ingestion
source .venv/bin/activate
python simulator.py
```

You should see log lines like:
```
[SIMULATOR]  Published event_id=a1b2c3d4  patient=1  hr=78 bpm  sleep=410 min
[PG-SUB]     Persisted event_id=a1b2c3d4  patient=1  hr=78 bpm
[REDIS-SUB]  Cache updated — patient=1  hr=78 bpm  sleep=410 min
```

---

## 6. Run Integration Tests

With Redis running and `.env` configured:

```bash
cd backend/wearable_ingestion
source .venv/bin/activate
python test_pipeline.py
```

Expected output (with Supabase connected):
```
✅ PASS  T1 – Redis connectivity
✅ PASS  T2a – required fields present
✅ PASS  T2b – simulation flag is True
✅ PASS  T2c – validation passes
✅ PASS  T3 – publish/subscribe round-trip
✅ PASS  T4a – all required tables exist
✅ PASS  T4b – wearable_data has event_id column
✅ PASS  T5 – valid event persisted
✅ PASS  T6 – duplicate silently ignored
✅ PASS  T7 – cache written
✅ PASS  T8 – stale event rejected
✅ PASS  T9 – TTL set on cache key
✅ PASS  T10 – missing patient_id
✅ PASS  T10 – negative heartrate
✅ PASS  T10 – bad measured_at
✅ PASS  T10 – non-int pedometer
```

If ingestion DB credentials are not set, T4–T6 will report `FAIL` with a
clear message. T1–T3 and T7–T10 run without a database.

---

## 7. Verify Cache Manually

```bash
# In a terminal with Docker running
docker exec mindbridge_ingestion_redis redis-cli HGETALL patient:1:vitals:latest
```

Expected output:
```
 1) "heartrate"
 2) "78"
 3) "sleep_minutes"
 4) "410"
 5) "pedometer"
 6) "543"
 7) "screentime_minutes"
 8) "145"
 9) "measured_at"
10) "2024-01-01T12:00:00+00:00"
11) "event_id"
12) "a1b2c3d4-..."
13) "cached_at"
14) "2024-01-01T12:00:01+00:00"
```

---

## 8. Verify PostgreSQL Manually

In the Supabase SQL Editor:
```sql
SELECT id, patient_id, timestamp, heartrate, sleep_minutes, event_id
FROM wearable_data
ORDER BY timestamp DESC
LIMIT 10;
```

---

## 9. Connecting the Existing Application to the New Database

> ⚠️ **This step requires explicit approval before execution.**

The existing `backend/app.py` and `backend/db.py` read connection
details from the root `.env` (variables: `DB_HOST`, `DB_PORT`,
`DB_NAME`, `DB_USER`, `DB_PASSWORD`).

To point the existing Flask application at the new Supabase database,
you would update those variables in the application's `.env` to match
the new Supabase connection details.

**This file is not touched by this feature.** A separate PR / approval
step is required before making that change.

---

## 10. Architecture Notes and Limitations

### Redis Pub/Sub message loss
Redis Pub/Sub does not persist messages. If a subscriber is not
connected when a message is published, that message is lost permanently.
There is no replay, no consumer group, no offset tracking.

**This is by design for this prototype.** The trade-off:
- Simple, low-latency distribution
- No durable message guarantee

For production, consider Redis Streams or a proper message broker.

### Dual-write is not atomic
A PostgreSQL commit and a Redis cache update are two separate
operations. If PostgreSQL succeeds and the Redis update fails:
- The measurement is safely persisted in PostgreSQL.
- The cache will be stale until the next event for that patient arrives.
- The cache can be rebuilt from PostgreSQL at any time.

Redis is explicitly not the source of truth.

### Exactly-once delivery
Not provided. The ingestion pipeline provides **at-least-once**
semantics within a single session (dedup via `ON CONFLICT DO NOTHING`)
but makes no guarantees across reconnects for missed Pub/Sub events.

### Simulation flag
Every event published by `simulator.py` includes `"simulation": true`.
These readings are never real patient data.

---

## 11. File Inventory

### New files created (this feature only)

| File | Purpose |
|---|---|
| `compose.yaml` | Isolated Redis Docker service |
| `schema.sql` | Idempotent app schema and wearable `event_id` migration |
| `.env.example` | Placeholder config — no secrets |
| `requirements.txt` | Feature-only Python deps |
| `simulator.py` | Mock wearable publisher |
| `subscriber_postgres.py` | PostgreSQL persistence subscriber |
| `subscriber_redis_cache.py` | Redis cache subscriber |
| `test_pipeline.py` | Integration test suite |
| `README.md` | This file |

### Existing files modified

**None.** The following were explicitly left unchanged:
- `backend/app.py`
- `backend/db.py`
- `backend/endpoints/*`
- `backend/services/*`
- `backend/wearables/mock_data.py`
- `requirements.txt` (root)
- `frontend/**`
- `context.md`
- `.gitignore`

---

## 12. Unresolved Integration Steps

| Step | Status | Action needed |
|---|---|---|
| Point existing Flask app at new Supabase DB | ❌ Not done | Explicit approval required; update `DB_*` vars in app `.env` |
| Register ingestion read API in Flask | ❌ Not done | Out of scope for this task |
| Real wearable device auth | ❌ Not done | College prototype — not required |
| Supervisor / systemd process management | ❌ Not done | Manual terminal launch for now |
| Production Redis ACL / auth | ❌ Not done | Not required for local dev |
