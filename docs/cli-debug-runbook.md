# CLI pipeline and debugging runbook

This runs the wearable simulator and subscribers without the Flutter UI. Use synthetic data only. Redis Pub/Sub is transient, so start both subscribers before the simulator.

## 1. Prepare Python

```bash
cd backend/wearable_ingestion
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The simulator and subscribers automatically load the repository-root `.env`.
Your existing root `.env` already contains the required `INGESTION_DB_*`, Redis,
and simulator variables. Keep passwords out of shell commands and logs. Shell
variables override `.env`; an optional `backend/wearable_ingestion/.env` can
provide settings if needed.

> **Schema setup:** the ingestion subscriber requires `wearable_data.event_id`
> to be a unique UUID. The included schema creates the tables or adds that
> column/index to an existing table. Apply it once to the same PostgreSQL DB
> configured by root `.env` before starting the subscriber:
>
> ```bash
> cd backend/wearable_ingestion
> source .venv/bin/activate
> python3 apply_schema.py
> ```
>
> Alternatively, when using the application DB variables (`DB_*`), run
> `python3 backend/db.py` from the repository root; `create_tables()` now adds
> the compatible column and unique index. Existing tables and rows are kept.

## 2. Start Redis

```bash
cd backend/wearable_ingestion
docker compose -f compose.yaml up -d redis
docker compose -f compose.yaml ps
docker exec mindbridge_ingestion_redis redis-cli ping
```

Expected: Redis is `healthy` and prints `PONG`.

## 3. Start subscribers in separate terminals

In each terminal, run `cd backend/wearable_ingestion` and `source .venv/bin/activate`.

**Terminal A — Redis cache:**

```bash
python -u subscriber_redis_cache.py
```

Expect `Connected to Redis` and `Subscribed to channel 'wearable:vitals'`.

**Terminal B — PostgreSQL (after DB/schema configuration):**

```bash
python -u subscriber_postgres.py
```

Expect `Connected to PostgreSQL` and `Subscribed to Redis channel 'wearable:vitals'`. Missing-variable errors mean root `.env` is missing DB settings. Repeated connection errors indicate host, port, credentials, network, or SSL problems; passwords are not printed.

## 4. Start simulator (Terminal C)

```bash
cd backend/wearable_ingestion
source .venv/bin/activate
SIMULATOR_HEART_RATE_SCENARIO=normal python -u simulator.py
```

The simulator should log `Simulator starting`, then `Published event_id=... patient=... seq=... hr=... subscribers=...`. With both subscribers listening, subscriber count should usually be 2; cache-only mode should show 1. Match the event ID across logs:

```text
[SIMULATOR] Published event_id=ab12... patient=1 seq=1 hr=...
[REDIS-SUB] Cache updated — patient=1 ... event_id=ab12...
[PG-SUB] Persisted event_id=ab12... patient=1 ...
```

Stop foreground processes with `Ctrl-C`. For synthetic scenarios, restart with `SIMULATOR_HEART_RATE_SCENARIO=elevated` or `low`. These are not clinical readings.

## 5. Inspect live Redis state

```bash
docker exec mindbridge_ingestion_redis redis-cli HGETALL patient:1:vitals:latest
docker exec mindbridge_ingestion_redis redis-cli PUBSUB NUMSUB wearable:vitals
```

The hash should contain `heartrate`, `sleep_minutes`, `screentime_minutes`, `pedometer`, `measured_at`, and `event_id`. Sleep and screen time stay constant until the configured behavioral interval expires. `PUBSUB NUMSUB` shows current listeners, not historical messages.

If PostgreSQL is configured with a compatible schema, inspect rows with `psql` or the Supabase SQL editor:

```bash
psql "$DATABASE_URL" -c "SELECT id, patient_id, timestamp, heartrate, sleep_minutes, screentime_minutes, event_id FROM wearable_data ORDER BY timestamp DESC LIMIT 10;"
```

Set `DATABASE_URL` from a secure credential source first; do not put credentials directly in shell history.

## 6. CLI model-backed chat (optional)

From the repository root:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull <model-tag>
docker compose exec ollama ollama list
curl -fsS http://127.0.0.1:11434/api/tags
```

Then start Flask in another terminal:

```bash
cd backend
export OLLAMA_MODEL='<model-tag>'
export OLLAMA_BASE_URL='http://localhost:11434'
python3 app.py
```

This repository has no health endpoint, so `GET /` returning 404 still confirms Flask is listening:

```bash
curl -i http://127.0.0.1:5000/
```

Chat endpoints also require the application PostgreSQL database and a valid patient row; the server alone is not an end-to-end chat smoke test.

## 7. Offline tests

```bash
cd backend/wearable_ingestion
source .venv/bin/activate
python -m unittest test_simulator.py
cd ../..
PYTHONPATH=backend python3 -m unittest services.test_llm
```

`test_pipeline.py` requires live Redis and PostgreSQL. It writes synthetic rows if DB credentials and schema are available.

## Quick diagnosis

| Observation | Likely cause / check |
|---|---|
| Simulator says `subscribers=0` | Start subscribers first; check Redis host, port, and channel. Pub/Sub does not replay missed events. |
| Cache subscriber has no `Cache updated` | Check simulator channel and subscriber count; inspect validation warnings. |
| Cache key is absent | Check patient ID and cache logs; run `redis-cli KEYS 'patient:*:vitals:latest'`. |
| DB subscriber exits immediately | Missing `INGESTION_DB_HOST`, `INGESTION_DB_USER`, or `INGESTION_DB_PASSWORD`. |
| DB subscriber retries connection | Check host, port, credentials, network access, and SSL mode. |
| `UndefinedColumn event_id` | Database does not have the ingestion subscriber's required column. |
| Unknown patient / rejected event | `SIMULATOR_PATIENT_IDS` must exist in the ingestion database. |
| Ollama model unavailable | Pull the exact `OLLAMA_MODEL` tag and verify with `ollama list`. |
| Flask chat returns 500/unavailable | Check Ollama status, `OLLAMA_BASE_URL`, model tag, and Flask logs. |
