# Runbook

All commands run from the repository root unless noted. Configure database,
Redis, Neo4j, and NVIDIA credentials in the ignored root `.env` file.

## Start services

```bash
python -m pip install -r requirements.txt
docker compose up -d redis neo4j
python backend/db.py

cd backend && python app.py
cd backend/wearable_ingestion && python worker.py
cd frontend && flutter run -d chrome
```

NVIDIA NIM handles chat and embeddings over HTTPS; no local model service is
required. See [NVIDIA setup](phase1-nvidia-setup.md) for environment variables
and how to re-embed existing Neo4j records after the embedding-model change.

First-time data: register a doctor and caretaker, then register an assigned
patient. Set `SIMULATOR_PATIENT_IDS` to that patient's id if using the simulator.

Existing data: run `python backend/wearable_ingestion/backfill.py`, then
`cd backend && python -m services.graph.sync backfill`.

## Verify

```bash
python -m backend_tests
python -m backend_tests --only guard
python -m backend_tests --strict
```

PASS/FAIL/SKIP is printed per check. The end-to-end check calls the configured
NVIDIA models. Fixtures use usernames starting `__bt_` and are removed
afterwards.

## Diagnose

| Symptom | Check |
|---|---|
| Login returns 500 / tokens rejected | Is `JWT_SECRET_KEY` set to at least 32 characters? Restarting without it invalidates tokens. |
| Chat returns 503 | Check `NVIDIA_API_KEY`, `NVIDIA_MODEL`, model access, and NVIDIA API connectivity. |
| Graph sync cannot embed rows | Check `NVIDIA_API_KEY`, `NVIDIA_EMBED_MODEL`, and `NVIDIA_EMBED_DIMENSIONS`. |
| Neo4j sync pending | Check `docker compose ps`; run `cd backend && python -m services.graph.sync reconcile` / `drain`. |
| Retrieval unavailable | Chat fails closed with 503; check Neo4j connectivity, vector index state, and NVIDIA embedding access. |
| Worker idle | Is the simulator publishing to the same `WEARABLE_STREAM`? `redis-cli -p 6380 XLEN wearable:events`. |
| Rejected events | `redis-cli -p 6380 XRANGE wearable:dead - +` (reason is stored per entry). |
