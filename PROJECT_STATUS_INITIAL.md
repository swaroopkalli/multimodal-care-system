# MindBridge Project Status

Audited 2026-10-31 at commit `efb3a62` (clean working tree). Paths are relative to the repository root. Evidence labels: **Verified** = run or observed during this audit; **Code** = read from source but not run; **Unverified** = could not be established. The audit was non-mutating: database access used read-only sessions, tests that write data were not run, and Flutter tooling ran on a temporary copy.

## 1. Current Project Architecture

MindBridge is a prototype mental-health monitoring system for three roles: patient, caretaker, and doctor. It has four separately started parts.

```text
Flutter app (web only)  --HTTP/JSON-->  Flask API (:5000)  --psycopg2-->  PostgreSQL
                                             |                               ^
                                             +--HTTP--> Ollama (:11434)      |
                                                                             |
simulator.py --PUBLISH wearable:vitals--> Redis --> subscriber_postgres.py --+
                                                +-> subscriber_redis_cache.py --> Redis hash
                                                    patient:<id>:vitals:latest (no reader)
```

| Component | Technology | Evidence | How it connects |
|---|---|---|---|
| Frontend | Flutter/Dart, Material, `http`, `flutter_dotenv`, `flutter_secure_storage` | `frontend/lib/main.dart`, `frontend/pubspec.yaml` | Calls Flask through the `ApiClient` singleton; `BACKEND_URL` comes from `frontend/.env` |
| API | Flask, Flask-CORS, Flask-JWT-Extended, Werkzeug | `backend/app.py:10-22` | 11 JSON routes; handlers open one database connection per request |
| Data access | psycopg2 with raw SQL; no ORM | `backend/db.py` | Reads `DB_*` from the root `.env` |
| Context builder | Python: EWMA and a heuristic stress score | `backend/services/context.py` | Turns relational rows into text stored in `patient_contexts` |
| LLM client | Standard-library HTTP client for Ollama `/api/chat` | `backend/services/llm.py` | Used by both chat handlers; non-streaming with bounded retries |
| Ingestion | redis-py Pub/Sub and psycopg2 in three standalone processes | `backend/wearable_ingestion/` | Shares only the database with Flask; reads `INGESTION_DB_*` |
| Infrastructure | Docker Compose | `compose.yaml` (Ollama), `backend/wearable_ingestion/compose.yaml` (Redis) | No Flask container, frontend container, or Dockerfile exists |

The two chat flows differ:

- **Staff chat:** loads the latest stored patient context, then sends the system prompt, context, and query to Ollama (`backend/endpoints/chat.py:55-70`).
- **Patient chat:** sends logged conversation turns and the query, with no patient data (`backend/endpoints/chat.py:72-87`).

"RAG" in this project means relational retrieval plus a generated text summary. There are no embeddings and no vector store.

The frontend's own descriptions do not match this design. `frontend/lib/src/screens/architecture_screen.dart:13,54` and `frontend/README.md:58-63` describe FAISS and Groq or OpenAI, none of which exist in the code.

## 2. What Has Already Been Implemented

These items are implemented and have evidence that they work. Section 5 lists defects that affect some of them.

| Feature | Evidence | Status |
|---|---|---|
| Flask app imports and registers all 11 API routes | `backend/app.py:12-22` | **Verified** |
| Ollama client: request format, role mapping, missing-model, timeout, and malformed-response handling | `backend/services/test_llm.py`, 5/5 tests pass (HTTP mocked) | **Verified** |
| Simulator: per-patient state, heart-rate scenarios, stable daily sleep and screen-time values | `backend/wearable_ingestion/test_simulator.py`, 3/3 tests pass | **Verified** |
| PostgreSQL connection and all 8 application tables | Live read-only inspection | **Verified** |
| Wearable persistence with `event_id` | 574 rows, all with `event_id`, dated 2026-10-25 to 2026-10-27 | **Verified** (past run) |
| Patient chat has completed against the database at least once | 3 `patient` rows in `chatbot_logs`, dated 2026-10-29 | **Verified** (past run; the model used is unknown) |
| Account registration with hashed passwords for all three roles | `backend/endpoints/auth.py:19-76,138-195,257-325`; live tables hold 2 caretakers, 1 doctor, 1 patient | **Code** (rows do not prove how they were created) |
| Doctor note create and list endpoints | `backend/endpoints/doctor_notes.py:4-52` | **Code** (zero live notes) |
| Wearable read endpoint | `backend/endpoints/doctor_notes.py:54-71` | **Code** |
| Redis cache subscriber with staleness guard and TTL | `backend/wearable_ingestion/subscriber_redis_cache.py:175-238` | **Code** (its tests need live writes and were not run) |
| Frontend flow from splash to portal selection to the three dashboards | `splash_screen.dart`, `dashboard_shell.dart` | **Code** (analyzer reports 0 errors; UI not exercised) |
| Stress slider updates the patient-status text on the caretaker screen | `care_state.dart:39-47`, `patient_dashboard.dart:127-130` | **Code** (in memory only) |

## 3. What Is Partially Implemented

| Feature | What exists | What is incomplete |
|---|---|---|
| Authentication | Register and login endpoints, `AuthScreen`, token storage in `ApiClient` | Login fails (Section 5, item 1); `AuthScreen` is never opened; no route verifies a token |
| Staff AI summary | Context builder, prompt, and frontend buttons | Context is never refreshed and reads the wrong rows (Section 5, items 6-7); no live staff chat has been logged |
| Patient chat | Endpoint, logging, and chat UI | Hard-coded `patient_id` of 1; history is not loaded into the UI; backend memory stops advancing after 5 turns |
| Doctor portal | Notes and AI summary call the API | Patient list, metrics, and trends are hard-coded; every patient detail page uses patient 1 |
| Caretaker portal | Live summary button and medication toggle | Alerts are static; observations are not saved; medication state stays in memory |
| Patient portal | Sliders, side-effect chips, journal box, progress tab | Only chat reaches the backend; streak and progress values are constants (`patient_dashboard.dart:72,354-388`) |
| Risk engine | `DecisionService` scoring (`frontend/lib/src/services/decision_service.dart`) | Only ever evaluates fixed demo data, so it always returns Monitor; its text does not vary with the score |
| Wearable pipeline | Simulator, both subscribers, schema, tests | Flask reads the stored rows but no frontend screen does; nothing reads the Redis cache; the data is synthetic only |
| Medications | Table and context-builder query | No endpoint or screen creates or reads medications; live table has 0 rows |
| Medication adherence | Caretaker toggle, staff prompt mentions adherence | No adherence data is stored; `setPatientMedicationTaken` is never called and the patient portal has no medication control |
| Containerization | Compose services for Ollama and Redis | Flask and the frontend have no container definitions |
| Automated tests | Python unit tests and a live integration script | No tests for Flask routes or `context.py`; the only Flutter test fails |

## 4. What Is Missing

Confirmed absent from the codebase:

- **Authorization:** no `JWTManager`, `jwt_required`, or role or patient-ownership checks.
- **Session features:** logout flow (`clearToken` and `hasToken` have no callers) and any login response field identifying the user (`auth.py:128-131` returns only a message and token).
- **Persistence for user input:** no tables or endpoints for check-ins, journal entries, side effects, or caretaker observations.
- **Directory and relationship APIs:** no endpoint lists patients or a clinician's assigned patients, and the registration screen cannot set `caretaker_id` or `doctor_id`.
- **Medication APIs:** no create, read, update, or delete operations.
- **Backend decision features:** no Normal/Monitor/Escalate engine, alerting, escalation workflow, self-harm language detection, or weekly summaries. The frontend's "No self-harm language detected" alert is static text (`frontend/lib/src/data/demo_data.dart:50`).
- **Planned API surface:** `POST /logs/patient`, `POST /logs/caretaker-validation`, `GET /decision/current`, `GET /guidance/rag`, and `GET /summaries/doctor-weekly` from `frontend/README.md:67-71`.
- **Retrieval infrastructure:** embeddings and a vector store such as FAISS.
- **Real device integration:** only the simulator produces wearable data.
- **Live vitals access:** no API reads the Redis latest-vitals cache.
- **Operations:** health endpoint, centralized logging or monitoring, rate limiting, connection pooling, production WSGI configuration, and CI.
- **Schema management:** a migration framework and seed data.
- **Mobile and desktop targets:** `frontend/` contains only `web/`; there are no `android/`, `ios/`, `windows/`, `macos/`, or `linux/` folders.
- **Referenced files:** `backend/wearable_ingestion/.env.example` and `backend/wearables/mock_data.py`, both named in `backend/wearable_ingestion/README.md:341,356`.

## 5. What's Broken

### Currently blocking

1. **Every successful login returns HTTP 500. Verified.** `backend/app.py` never creates a `JWTManager`, so `create_access_token` raises `RuntimeError: You must initialize a JWTManager with this flask application` (`backend/endpoints/auth.py:121,240,370`). This was reproduced with correct credentials and a mocked database. `JWT_SECRET_KEY` is also not set in the environment.
2. **Both chat endpoints currently fail at the model call. Verified.** The configured `OLLAMA_MODEL` is `llama3.2`, while Ollama has only `phi3:latest` installed. The project client returns `Ollama model 'llama3.2' is unavailable; pull it first`, which the handlers return as HTTP 500 (`backend/endpoints/chat.py:69-70,86-87`).
3. **The PostgreSQL ingestion subscriber exits on startup. Verified.** The root `.env` has no `INGESTION_DB_*` variables, so `subscriber_postgres.py:100-105` exits with code 1. `apply_schema.py:14-17` has the same requirement (**Code**), and the database tests in `test_pipeline.py` would report failures (**Code**). The docs wrongly say these variables are present (`docs/cli-debug-runbook.md:15`, `backend/wearable_ingestion/README.md:111`).
4. **The login screen is unreachable. Verified.** `AuthScreen` is never constructed, and the analyzer reports its import as unused (`dashboard_shell.dart:8`). Portal cards open dashboards directly (`dashboard_shell.dart:83-109`).

### Incorrect behavior and data errors

5. **The doctor portal attaches data to the wrong patient. Code.** All three demo patients share `patient_id` 1 and `doctor_id` 1 (`doctor_dashboard.dart:117,147-148,175`). A note written on any patient's page is stored against patient 1, and every page shows patient 1's notes and AI summary under that patient's displayed name.
6. **Staff context goes stale permanently after first generation. Code.** `get_latest_patient_context` returns any stored context, and `generate_patient_context` has no other caller (`backend/services/context.py:121-124`). Later notes, medications, and vitals never reach staff chat.
7. **The stress analysis reads the oldest rows over minutes, not recent days. Verified.** The query uses `ORDER BY timestamp ASC LIMIT 14` (`context.py:30-35`). On live data those rows span 3 minutes 51 seconds on 2026-10-25, yet the output is labelled "EWMA Analysis over 14 days" (`context.py:75`). They also carry a single daily sleep value because the simulator repeats it.
8. **Patient chat memory stops advancing. Code.** `ORDER BY created_at ASC LIMIT 5` always returns the first five exchanges (`backend/endpoints/chat.py:41`).
9. **A NULL vital crashes context generation. Verified.** `calculate_ewma` raises `TypeError` on `None` (`context.py:7-8`), and these columns are nullable. Current live rows contain no such NULLs.
10. **Synthetic data is not identifiable once stored. Verified.** `wearable_data` has no `simulation` column, so simulated vitals reach staff summaries as "Resting Heart Rate" with no synthetic marker (`context.py:77`).
11. **Dashboard submit buttons report false success. Code.** Check-in, journal, and observation buttons show confirmation messages without saving anything (`patient_dashboard.dart:166-170,227-231`, `caretaker_dashboard.dart:170-174`).
12. **The risk chip ignores user input. Code.** Sliders do not feed `DecisionService`, which always evaluates `DemoData.currentLog` (`patient_dashboard.dart:113`, `caretaker_dashboard.dart:102`).
13. **Doctor list ordering is not what it claims. Code.** The screen says "ordered by clinical review value", but the static order is Monitor, Normal, Escalate (`doctor_dashboard.dart:13-41,55`).

### Security defects

14. **Clinical and chat routes have no authentication. Verified for reads, Code for the rest.** `GET /api/doctor_notes/<id>` and `GET /api/wearables_data/<id>` returned 200 with no token (database mocked). Note creation trusts `doctor_id` from the request body, and anyone can call either chat route or register as a doctor.
15. **Debug mode is enabled on all network interfaces. Code.** `app.run(host="0.0.0.0", port=5000, debug=True)` (`backend/app.py:26`), combined with unrestricted CORS (`backend/app.py:11`).
16. **Raw exception text is returned to clients. Code.** `str(e)` is returned in `auth.py:69-71,188-190,318-320`, `doctor_notes.py:26,49,68`, and `chat.py:70,87`.
17. **JWTs would not validate as currently built. Verified.** Tokens use a dict identity. On a throwaway app with a `JWTManager`, creation succeeded but decoding failed with `InvalidSubjectError: Subject must be a string`. This does not surface today because login fails first and no route decodes tokens.

### Robustness

18. **Login without a password returns 500. Verified.** `check_password_hash` raises `AttributeError` on `None` (`auth.py:361`; the same code is at lines 112 and 231).
19. **The simulator crashes when publishing fails. Verified.** `redis` is imported only inside `_connect_redis` (`simulator.py:162`), so the handler at `simulator.py:226` raises `NameError` instead of reconnecting.
20. **Valid non-object JSON can crash the subscribers.** `_validate_event` raises `AttributeError` on a JSON array (**Verified** in the Redis subscriber) and runs outside the loop's `try` block (`subscriber_redis_cache.py:283`). The PostgreSQL subscriber has the same code (`subscriber_postgres.py:122,308`; **Code**).
21. **The in-flight event is lost when PostgreSQL disconnects. Code.** The subscriber reconnects without retrying that event (`subscriber_postgres.py:327-334`), although its header implies retries for in-memory events (line 33).
22. **Smaller ingestion defects. Code.** The unknown-patient path leaves a transaction open without rollback (`subscriber_postgres.py:336-338`). `_parse_utc` overwrites non-UTC offsets instead of converting them (`subscriber_redis_cache.py:144`). The simulator always emits UTC, so that second defect is not currently triggered.
23. **Database failures in several routes bypass JSON error handling. Code.** `get_db_connection()` runs outside `try` blocks, for example at `auth.py:90` and `doctor_notes.py:13`.
24. **Frontend error and lifecycle defects. Code.** Note-loading errors are swallowed and appear as "No notes saved yet." (`doctor_dashboard.dart:121-122`). "Failed to save note." renders in green (`doctor_dashboard.dart:289`). `setState` runs after async work without `mounted` checks (`doctor_dashboard.dart:118-126`, `patient_dashboard.dart:278-291`). HTTP requests have no client timeout (`api_client.dart:44,57`).
25. **The architecture screen has no navigation chrome. Code.** It returns a bare `ListView` with no `Scaffold` or app bar when pushed as a route (`architecture_screen.dart:19`, `dashboard_shell.dart:48`). Its appearance was not checked at runtime.
26. **The default side-effect selection is inconsistent. Code.** `Mild nausea` is preselected but is not an available chip (`patient_dashboard.dart:29,38-46`), and `None` can stay selected alongside other options.

### Failing tests and misleading documentation

27. **The only Flutter test fails. Verified.** `frontend/test/widget_test.dart:9` expects the text "Patient Portal" on the first frame, but the app starts on the splash screen, so no such widget is found. Its other expected strings describe an older UI; for example, "Hybrid intelligence, three human views." no longer exists in `frontend/lib`. Result: 0 passed, 1 failed.
28. **Documentation contradicts the code. Verified.**
    - `.env` comments say `schema.sql` seeds patient 1, but it contains no seed data.
    - `context.md:278` lists role-based authentication as implemented.
    - `context.md:73` lists `provider`, which is declared but never imported.
    - `docs/backend.env.example` defines `LLM_PROVIDER`, which no code reads.
    - The root `.env` defines both `OLLAMA_*` variables twice, with identical values.

### Unverified

- Complete Flutter-to-Flask-to-database flows, because Flask was not running and starting chat or note flows would write data.
- `test_pipeline.py` (it writes synthetic rows), and the running behavior of the Redis cache subscriber.
- `create_tables()` against the live database, because it issues DDL.
- UI rendering and layout, because no screens were opened.

## 6. Current Backend and Frontend Status

### Backend: partially functional, not running at audit time

Nothing was listening on port 5000. The app imports successfully under the installed packages (Flask 3.1.3, Flask-JWT-Extended 4.7.3, PyJWT 2.12.1).

| Route | Method | Auth enforced | Frontend caller | Status |
|---|---|---|---|---|
| `/api/auth/register/{caretaker,doctor,patient}` | POST | No | `AuthScreen` (unreachable) | **Code**: appears functional |
| `/api/auth/login/{caretaker,doctor,patient}` | POST | No | `AuthScreen` (unreachable) | **Verified broken**: 500 on valid credentials; invalid-credential path not run |
| `/api/doctor_notes` | POST | No | Doctor detail | **Code**: implemented; caller hard-codes IDs |
| `/api/doctor_notes/<patient_id>` | GET | No | Doctor detail | **Verified** 200 with mocked database |
| `/api/wearables_data/<patient_id>` | GET | No | None | **Verified** 200 with mocked database; unused by the UI |
| `/api/staff/chat` | POST | No | Doctor detail, caretaker summary | **Verified blocked** at the model call; context logic defective |
| `/api/patient/chat` | POST | No | Patient chat | **Verified blocked** at the model call; worked previously |

Backend tests: 8 of 8 offline unit tests pass (5 LLM, 3 simulator). No tests cover Flask routes, authentication, or context generation.

Ingestion processes: none were running (`wearable:vitals` has 0 subscribers). The PostgreSQL subscriber cannot start with the current environment.

### Frontend: demo UI with limited API integration

`flutter analyze` reports 0 errors, 7 warnings, and 19 informational issues. `flutter test` fails (Section 5, item 27). Only web is configured as a platform.

| Screen | File | Backend integration | Status |
|---|---|---|---|
| Splash | `screens/splash_screen.dart` | None | Implemented |
| Portal selection | `screens/dashboard_shell.dart` | None | Implemented; bypasses login |
| Login and register | `screens/auth_screen.dart` | Register and login APIs | Built but unreachable |
| Patient: Check-in | `screens/patient_dashboard.dart:112` | None | Local UI only; submission not saved |
| Patient: Journal | `screens/patient_dashboard.dart:181` | None | Local UI only; text not captured or saved |
| Patient: Issues & Chat | `screens/patient_dashboard.dart:295` | `POST /patient/chat` | Integrated with hard-coded patient 1; currently blocked by the model error |
| Patient: Progress | `screens/patient_dashboard.dart:345` | None | Static values |
| Caretaker: Dashboard | `screens/caretaker_dashboard.dart:101` | None | In-memory state and demo data |
| Caretaker: Alerts | `screens/caretaker_dashboard.dart:185` | None | Static demo data |
| Caretaker: RAG Summarize | `screens/caretaker_dashboard.dart:214` | `POST /staff/chat` | Integrated with hard-coded patient 1; currently blocked |
| Doctor: Patient list | `screens/doctor_dashboard.dart:43` | None | Three hard-coded demo patients |
| Doctor: Patient detail | `screens/doctor_dashboard.dart:193` | Notes GET and POST, `POST /staff/chat` | Partly integrated; always patient 1; metrics and trends static |
| Architecture | `screens/architecture_screen.dart` | None | Static and inaccurate about the stack |

Integration summary:

- The frontend's default base URL and `frontend/.env` both target `http://127.0.0.1:5000`, and `ApiClient` appends `/api`.
- 4 of the 11 backend routes are reachable from the UI: patient chat, staff chat, and the doctor notes GET and POST routes. The 6 auth routes are called only from the unreachable `AuthScreen`, and the wearable read route has no caller.
- No authenticated session is ever created, so requests never carry a token, and the backend would not check one.
- `PortalHeader`, `DemoData.wearableSignals`, `DemoData.weeklySummary`, and `ActorRole` are defined but unused.

## 7. Database and External Service Status

### PostgreSQL: connected

| Item | Status |
|---|---|
| Connectivity | **Verified**: connected over SSL (`DB_SSLMODE=require`) using root `.env` `DB_*`; server version 17.11; port 6543, consistent with the Supabase transaction pooler described in `.env` comments |
| Ingestion credentials | **Verified missing**: `INGESTION_DB_*` not set |
| Secrets in git | **Verified**: root and frontend `.env` are ignored and untracked |
| Migrations | No framework. `create_tables()` (`backend/db.py:24-102`) and `schema.sql` are the only mechanisms; the only migration is the additive `event_id` column and index |
| Table creation | `create_tables()` runs only under `python app.py` or `python db.py`, not when the app is imported by another server (`backend/app.py:24-26`) |

| Table | Live rows | Notes |
|---|---|---|
| `caretakers` | 2 | Hashed-password column; unique username |
| `doctors` | 1 | ID 1 exists |
| `patients` | 1 | ID 1 exists; has optional caretaker and doctor foreign keys |
| `medications` | 0 | No application code writes here |
| `wearable_data` | 574 | All from 1 patient; latest row is dated 2026-10-27 |
| `doctor_notes` | 0 | No note exists in the live database |
| `patient_contexts` | 0 | First successful context call will generate one |
| `chatbot_logs` | 3 | All `patient`; no `staff` rows |

Schema defects and drift:

- **Conflicting medication rule. Verified.** `medications.prescribed_by` is `NOT NULL` but also `ON DELETE SET NULL` in `backend/db.py:57` and the live database, so deleting a doctor who has prescriptions would fail. `schema.sql:32` makes the column nullable, so the two schema sources disagree.
- **Medication primary key. Verified.** `medications.name` is the sole primary key, so only one row can exist per medication name across all patients.
- **Indexes missing from the repository. Verified.** The live database has `idx_chatbot_logs_patient_created`, `idx_doctor_notes_patient_created`, `idx_wearable_data_event_id`, and `idx_wearable_data_patient_ts`, none of which is defined in repository code.
- **Redundant `event_id` indexes. Verified.** `wearable_data_event_id_key`, `wearable_data_event_id_unique`, and `idx_wearable_data_event_id` all cover `event_id`.
- **Row-level security not in the repository. Verified.** All 8 public tables have RLS enabled with 0 policies. The configured role owns the tables and has `BYPASSRLS`, so the app is unaffected, but this configuration exists only in the live database.
- **Stored timestamps have no time zone. Code.** All timestamp columns use `TIMESTAMP` without a time zone.

### External services

| Service | Configuration | Status at audit |
|---|---|---|
| **Ollama** | `OLLAMA_BASE_URL`, `OLLAMA_MODEL=llama3.2`; optional timeout and retries | **Verified**: API reachable on port 11434, but the configured model is not installed; only `phi3:latest` is. It is not the Compose container, because the Docker daemon was unreachable |
| **Redis** | `127.0.0.1:6379`, channel `wearable:vitals` | **Verified**: reachable, version 7.4.9, running as a Windows host process rather than the Compose `redis:7.4.1-alpine` container. 0 subscribers and 0 latest-vitals keys |
| **Docker** | `compose.yaml`, `backend/wearable_ingestion/compose.yaml` | **Verified**: CLI installed, daemon not running; neither Compose stack could be running |
| **Supabase** | Described by `.env` comments and the ingestion README; used only as PostgreSQL | No Supabase SDK, Auth, Storage, or REST use in code. **Unverified**: the audit did not separately confirm the hosting provider |
| **Real wearable devices** | None | Not integrated; simulator only |
| **Gemini** | Removed; replaced by Ollama (`docs/phase1-codebase-analysis.md:12`) | No remaining references in backend code |
| **FAISS, Groq, OpenAI** | Mentioned only in frontend text and README | Not integrated |
