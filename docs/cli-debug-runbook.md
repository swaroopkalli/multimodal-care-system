# Runbook

All commands run from the repository root unless noted. Configuration: copy `.env.example` to `.env`.

## Start everything

```bash
python -m pip install -r requirements.txt
docker compose up -d redis neo4j            # waits for health checks: docker compose ps
ollama pull llama3.2:3b && ollama pull nomic-embed-text    # once; Ollama runs on the host (port 11434)
python backend/db.py                        # create/upgrade the schema (idempotent)

cd backend && python app.py                 # Flask API on http://127.0.0.1:5000, also mirrors rows to Neo4j
cd backend/wearable_ingestion && python worker.py      # wearable consumer
cd backend/wearable_ingestion && python simulator.py   # synthetic events (optional)

cd frontend && flutter run -d chrome        # or: flutter run -d web-server --web-port 8081
```

First-time data: register a doctor and a caretaker in their portals, then register a patient with their
usernames in the optional fields so they are assigned. Set `SIMULATOR_PATIENT_IDS` to that patient's id.

Existing data: `python backend/wearable_ingestion/backfill.py` (smoothing, rollups, anomalies) and
`cd backend && python -m services.graph.sync backfill` (mirror existing notes/chats/windows to Neo4j).

## Verify

```bash
python -m backend_tests                  # everything (about 10-15 min; the end-to-end check calls the real model)
python -m backend_tests --only guard     # one area, e.g. 7 / Guardrails
python -m backend_tests --strict         # unavailable optional services become FAIL
```

PASS/FAIL/SKIP per check; SKIP means an optional service (Redis, Neo4j, Ollama) was not reachable, FAIL
includes PostgreSQL being unreachable. Fixtures use usernames starting `__bt_` and are removed afterwards.

## Diagnose

| Symptom | Check |
|---|---|
| Login returns 500 / tokens rejected | `JWT_SECRET_KEY` set (>= 32 chars)? Restarting without it invalidates tokens |
| Chat returns 503 | `ollama list` shows `OLLAMA_MODEL`? `curl http://localhost:11434/api/tags` |
| Ollama "cudaMalloc failed" | another model is loaded: `ollama ps`; lower `OLLAMA_NUM_CTX` (e.g. 4096) |
| Redis connection closed immediately (Docker Desktop) | `docker compose restart redis` re-creates the port mapping |
| Neo4j sync pending | `docker compose ps`; `cd backend && python -m services.graph.sync reconcile` / `drain` |
| Worker idle | is the simulator publishing to the same `WEARABLE_STREAM`? `redis-cli -p 6380 XLEN wearable:events` |
| Rejected events | `redis-cli -p 6380 XRANGE wearable:dead - +` (reason is stored per entry) |
| Retrieval status `unavailable` in chat replies | Neo4j or the embedding model is down; chat still works with pinned facts only |
