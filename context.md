# MindBridge Project Context

## 1. Project Overview

MindBridge is a multi-actor mental health monitoring and support system designed to help patients, caregivers, and clinicians monitor wellness patterns, interpret wearable-based signals, and receive AI-assisted guidance without replacing professional care. The project combines a Flutter frontend with a Python Flask backend, relational patient data, and Gemini-based conversational assistance.

The product is positioned as a decision and triage assistant rather than a standalone LLM app. It blends:

- structured patient data (medications, notes, wearable metrics)
- a simple clinical risk engine based on sleep and heart-rate trends
- an LLM layer that produces concise summaries and responses
- role-based views for patient, caretaker, and doctor
- safety-focused prompting that discourages diagnosis or treatment recommendations

## 2. Product and User Roles

### Patient
- Tracks wellness signals and daily context
- Receives supportive conversational guidance
- Chats with a patient-facing wellness coach
- Uses a conversational memory flow rather than a full RAG context

### Caretaker
- Validates patient status and observed behaviors
- Accesses summary information and patient context
- Uses clinical staff prompts with patient-specific RAG grounding

### Doctor
- Reviews patient summary data and clinician notes
- Monitors trends, adherence, and wearable-based health indicators
- Uses supporting summaries that emphasize risk, adherence, and sleep-related stress concerns

## 3. Core Functional Architecture

### Frontend
- Framework: Flutter + Dart
- UI design: Material Design
- App entry point: `frontend/lib/main.dart`
- Main app shell: `frontend/lib/src/app.dart`
- Key screens:
  - patient dashboard
  - caretaker dashboard
  - doctor dashboard
  - architecture/systems overview
  - splash screen

### Backend
- Framework: Flask (Python)
- API entry: `backend/app.py`
- Database: PostgreSQL via `psycopg2`
- Authentication: JWT via `flask_jwt_extended`
- Request handling: JSON API endpoints with Flask CORS enabled

### Database Layer
The system stores data in PostgreSQL tables created by `backend/db.py`.

Primary tables:
- `caretakers`
- `doctors`
- `patients`
- `medications`
- `wearable_data`
- `doctor_notes`
- `patient_contexts`
- `chatbot_logs`

## 4. Tech Stack

### Frontend stack
- Flutter
- Dart
- `http` for REST API calls
- `provider` for app state management patterns
- `flutter_secure_storage` for JWT persistence
- `flutter_dotenv` for environment configuration

### Backend stack
- Python 3
- Flask
- Flask CORS
- `psycopg2-binary` for PostgreSQL access
- `python-dotenv` for environment configuration
- `flask-jwt-extended` for auth
- `werkzeug` for password hashing and auth helpers

### AI / LLM stack
- Google Generative AI SDK (`google.genai`)
- Model: `gemini-2.5-flash`
- API key configured via `GEMINI_API_KEY`
- Prompting style includes:
  - clinical analysis instructions for staff
  - empathetic wellness coaching for patient responses
  - guardrails against diagnosis and prescription by the model

### Data and analytics stack
- PostgreSQL for structured relational data
- patient context generation for retrieval-augmented prompting
- Exponentially Weighted Moving Average (EWMA) for trend analysis
- stress score logic derived from sleep deficit and elevated heart rate

## 5. API and Backend Workflow

### Authentication endpoints
- `POST /api/auth/register/caretaker`
- `POST /api/auth/register/doctor`
- `POST /api/auth/register/patient`
- `POST /api/auth/login/caretaker`
- `POST /api/auth/login/doctor`
- `POST /api/auth/login/patient`

### Clinical data endpoints
- `POST /api/doctor_notes`
- `GET /api/doctor_notes/<int:patient_id>`
- `GET /api/wearables_data/<int:patient_id>`

### Chat endpoints
- `POST /api/staff/chat`
- `POST /api/patient/chat`

## 6. RAG and Context Generation

### Current implemented approach
The project does not yet use a traditional vector-database RAG pipeline such as FAISS or Pinecone in the backend code. Instead, it implements a practical structured-context RAG layer built from relational database records.

The flow is:

1. The backend fetches patient data from PostgreSQL:
   - patient name
   - latest wearable data over a 14-day window
   - prescribed medications
   - recent doctor notes
2. It transforms the data into a natural-language summary string.
3. The summary is stored in `patient_contexts`.
4. The staff chatbot then sends that summary plus the user query to Gemini.
5. The LLM generates a clinical summary or analysis grounded in the patient context.

This is effectively a retrieval-and-grounding workflow, even though it is not a vector-index retrieval system.

### Patient context builder
File: `backend/services/context.py`

The `generate_patient_context(patient_id)` function:
- loads patient metadata
- fetches up to 14 days of wearable metrics
- fetches medications
- fetches the last five doctor notes
- computes EWMA trend values for sleep and heart rate
- computes a stress score
- writes a narrative summary into `patient_contexts`

### RAG-style prompt construction
File: `backend/services/llm.py`

The system sends:
- a role-specific system prompt
- a patient context summary
- the actual user query

This means the response is grounded in patient-specific context rather than relying on a generic LLM answer alone.

### Important distinction
The frontend README and architecture screen mention:
- FAISS retrieval
- Supabase storage
- Groq/OpenAI orchestration

Those are described as planned architecture or product framing, but the code currently implemented in this workspace uses:
- PostgreSQL storage
- Flask API retrieval
- Gemini API generation
- contextual summarization instead of a vector store

## 7. Wearable and Stress Signal Logic

The patient context builder uses a simple health-risk model based on wearable trends.

### EWMA formula
`EWMA_t = alpha * Y_t + (1 - alpha) * EWMA_{t-1}`

with
- `alpha = 0.2`
- applied to wearable time series for sleep and heart rate

### Stress formula currently used
- `sleep_deficit = max(0, 420 - latest_sleep_ewma)`
- `hr_excess = max(0, latest_hr_ewma - 75)`
- `stress_score = min(10, max(0, (sleep_deficit / 30) + (hr_excess / 5)))`

This creates a 0-10 stress score emphasizing:
- insufficient sleep
- elevated resting heart rate

This is a lightweight heuristic intended for monitoring and summarization support, not clinical risk scoring.

## 8. Prompting Strategy

### Staff prompt
The staff prompt explicitly instructs the model to:
- provide concise clinical summaries
- analyze patient history
- assess medication adherence
- perform stress trend analysis
- stay grounded in the provided patient context
- avoid diagnosis or prescribing

### Patient prompt
The patient prompt emphasizes:
- empathetic wellness support
- coaching and stress reduction suggestions
- sleep improvement tips
- non-diagnostic guidance
- encouraging professional support when appropriate

### Chat log design
User queries and model responses are stored in `chatbot_logs` with `role`, `patient_id`, `query`, `response`, and `created_at` metadata. This supports memory and retrievable conversation history for patient interactions.

## 9. Evaluation Metrics and Success Criteria

This project does not yet contain a formal benchmark harness, automated evaluation pipeline, or metrics dashboard. The current evaluation model is qualitative and heuristic.

### Metrics currently present in the codebase

1. Stress scoring heuristic
   - derived from sleep deficit and elevated heart rate
   - used as a proxy signal for patient stress risk

2. Context quality by construction
   - generated summary includes:
     - patient name
     - medications
     - recent wearable patterns
     - recent doctor notes
     - stress score
   - this improves the groundedness of LLM outputs

3. Safety-oriented response quality
   - response generation is constrained by system prompts
   - outputs are designed to avoid diagnosis and medication recommendations

### Recommended evaluation metrics for future production use

For a more rigorous system, the following should be tracked:

- clinical response safety compliance
  - % of outputs without diagnosis or treatment advice
- groundedness / factual consistency
  - match between generated answer and patient context
- retrieval relevance
  - whether the selected patient context is the correct data source
- hallucination rate
  - unsupported claims in generated summaries
- latency
  - response generation time per query
- task completion rate
  - % of queries answered with a usable summary or guidance
- user satisfaction
  - patient and clinician feedback scores

If this project is formalized into a research or startup evaluation framework, a strong set of metrics would be:

- Precision@k for relevant context retrieval
- Recall for clinically relevant notes and signals
- F1 for risk classification or triage labeling
- AUC or balanced accuracy for stress-risk classification if a supervised model is later added
- human review score for response appropriateness

### Current stance
At present, the codebase is best described as a grounded clinical assistant prototype, not a production-grade clinical AI system. The evaluation emphasis is on:
- human-in-the-loop safety
- context-grounded summarization
- pragmatic workflow utility
- rule-based risk signals

## 10. Project Status and Limitations

### What is implemented
- role-based authentication
- patient, caretaker, and doctor data models
- doctor note ingestion
- wearable trend ingestion
- patient-context summarization
- Gemini-powered chat responses
- stateful patient conversation history
- Flutter UI for demo flows

### What is still conceptual or planned
- full FAISS vector search pipeline
- explicit retrieval-ranking evaluation
- production-grade clinical safety validation
- real wearable integration
- larger enterprise or EHR integration
- in-depth automated metrics collection and model monitoring

## 11. Summary

MindBridge is a prototype for a mental-health monitoring and support platform that combines:

- relational patient tracking
- wearable and behavioral signals
- RAG-style contextual grounding from patient records
- role-specific AI assistance via Gemini
- safety-focused prompts and risk heuristics

The most important system design pattern in the current code is: structured context generation + grounded response synthesis. This is a useful and practical hybrid pattern for early-stage clinical AI tooling, even without a full vector database and formal metrics pipeline.
