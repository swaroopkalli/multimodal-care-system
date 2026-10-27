# Phase 1 Codebase Analysis

## Current architecture

- The frontend is Flutter/Dart (`frontend/lib/main.dart`, `frontend/lib/src/app.dart`) with patient, caretaker, and doctor dashboards. Its `DecisionService` is a local demo heuristic; it is not called by the Python chat backend.
- The backend is a Flask JSON API (`backend/app.py`) with PostgreSQL access through psycopg2 (`backend/db.py`). Authentication routes create role-specific JWTs, though the chat handlers themselves do not enforce JWT authorization in their current code.
- Wearable ingestion is a separate Python process in `backend/wearable_ingestion`: simulator publishes JSON over Redis Pub/Sub, and independent subscribers persist measurements to PostgreSQL and refresh Redis latest-vitals cache. Its Compose file runs only Redis.
- No backend Dockerfile or application Compose service exists. The root Compose file provides Ollama as a separate local model service, bound to loopback for the host-run Flask backend.

## LLM request flow

`POST /api/staff/chat` and `POST /api/patient/chat` in `backend/endpoints/chat.py` call `services.llm`. Staff chat obtains a stored/generated patient narrative from `services/context.py`; that builder retrieves relational records, computes EWMA sleep and heart-rate summaries plus a simple stress heuristic, and stores the narrative in `patient_contexts`. Patient chat uses recent logged conversation turns. Both paths pass role-specific system prompts. The prior implementation used `google.genai`, Gemini 2.5 Flash, and `GEMINI_API_KEY`; the provider client was isolated to `backend/services/llm.py`.

The RAG implementation is relational retrieval plus generated narrative context, not a vector store. No embedding model or vector database is present. Rules and escalation: backend context contains a non-clinical stress heuristic; the Flutter demo `DecisionService` computes a separate daily risk level. No backend escalation workflow was found.

## Wearable simulation flow and event schema

`backend/wearable_ingestion/simulator.py` cycles configured patient IDs and emits a JSON object with `event_id`, `device_id`, `patient_id`, `sequence`, `measured_at`, `simulation`, `pedometer`, `sleep_minutes`, `screentime_minutes`, and `heartrate`. Subscribers validate these required fields; Postgres stores them in `wearable_data` and Redis stores a latest-vitals hash. Pub/Sub is transient and events can be missed while subscribers are disconnected. Existing tests are in `test_pipeline.py` and require live Redis and optionally configured PostgreSQL; Flutter has a widget test. No Python unit test harness/configuration existed.

Heart rate was an independent uniform integer 58–105 BPM. Sleep (200–540 minutes) and screen time (20–480 minutes) were redrawn for every event, despite representing daily/nightly aggregates. They are not rules or clinical thresholds.

## Dependencies and configuration

- Root Python dependencies: Flask, Flask-CORS, psycopg2-binary, python-dotenv, Flask-JWT-Extended, Werkzeug, and Redis (the latter also used by the separate ingestion feature).
- Ingestion dependencies add redis-py, psycopg2-binary, and python-dotenv.
- App DB configuration uses `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` via `backend/db.py`; ingestion uses separate `INGESTION_DB_*` variables and Redis host/port/channel settings. Ingestion processes load the root `.env` plus optional local overrides.
- Existing root `.env` is ignored by git and contains environment-specific ingestion credentials. It is read by ingestion processes and the schema applier, but is not copied into documentation.
- Flutter config includes its own pubspec and dotenv dependencies. No Dockerfile, lint configuration, or Python test runner configuration was found.

## Security, operations, and backward compatibility

JWT login exists, password hashing uses Werkzeug, and CORS is enabled globally. Chat route authorization is not applied in the inspected handlers; this phase leaves that behavior unchanged. Chat data and patient context are persisted in PostgreSQL. Logs in chat handlers are plain console error messages; there is no centralized monitoring. The current LLM call is synchronous and not streamed.

The Ollama integration preserves `generate_response` and `generate_chat_response`, prompts, and chat API response JSON. It sends non-streaming `/api/chat` messages, uses configurable model/URL/timeouts, and bounds retries. In Docker, backend callers should configure `OLLAMA_BASE_URL=http://ollama:11434`; local host callers default to localhost. This repository has no backend container to attach to Compose yet. Model tags must be pulled explicitly and Ollama readiness does not imply the model is present.

Simulator event keys, integer units, and publication cadence remain unchanged. Per-patient state makes behavior metrics independent; the 24-hour default preserves nightly sleep-session and daily screen-time aggregate semantics. State is in memory and resets on simulator restart. Heart-rate scenarios are configurable as `normal`, `elevated`, or `low`, generated as mean-reverting synthetic series, not validated medical observations. The ingestion schema adds a unique `event_id` UUID column/index idempotently; `backend/db.py` applies the same additive migration when creating app tables.

## Minimal implementation plan

1. Replace the isolated Gemini SDK implementation with an Ollama HTTP client while preserving the two public functions and callers.
2. Add local Compose model persistence/health behavior, safe environment examples, and explicit model pull instructions.
3. Add per-patient simulator state, configurable heart-rate scenario, and daily behavioral aggregate persistence without changing event schema.
4. Add offline unit coverage for simulator and mocked HTTP coverage for Ollama; document that no clinical validity is implied.
