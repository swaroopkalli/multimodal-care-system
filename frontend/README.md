# MindBridge Frontend

Flutter frontend for a modular, multi-actor mental health monitoring system.

## Product Shape

MindBridge is positioned as a decision and triage system with AI assistance, not just an LLM app.

- Patient: daily check-ins, medication adherence, side effects, journal, calm guidance, progress.
- Caretaker: validates medication, adds observations, improves data reliability, receives alerts.
- Doctor: reviews only filtered summaries, high-risk flags, and key issues such as insomnia-driven dropout risk.

## Frontend Structure

```text
lib/
  main.dart
  src/
    app.dart
    data/
      demo_data.dart
    models/
      care_event.dart
    screens/
      architecture_screen.dart
      caretaker_dashboard.dart
      dashboard_shell.dart
      doctor_dashboard.dart
      patient_dashboard.dart
    services/
      decision_service.dart
    state/
      care_state.dart
    theme/
      app_theme.dart
    widgets/
      metric_tile.dart
      mini_bar_chart.dart
      portal_header.dart
      section_card.dart
      status_chip.dart
```

## Current Demo Features

- Animated portal selection screen for Patient, Caretaker, Doctor, and System architecture.
- Patient portal with bottom navigation for daily check-in, compulsory journaling, RAG side-effect chat, and progress.
- Patient check-in includes mood, stress, sleep, energy, medication, meal status, multiselect side effects, and notes.
- Shared mocked care state so patient medication logging and caretaker medication validation reflect across both portals.
- Caretaker portal with dashboard, patient status, adherence validation, observations, alerts, and daily/weekly summaries.
- Doctor portal with a minimal patient list and patient detail screens for trends, adherence, and summary.
- Local stress scoring and decision layer: Normal, Monitor, Escalate.
- RAG guidance copy with guardrails: no diagnosis, no prescription, escalate risky cases.
- Simulated wearable signals that feed the same stress-engine concept planned for future real wearable integrations.

## Backend Alignment

Planned backend stack:

- Flask API layer.
- Supabase for structured data.
- FAISS for local hackathon RAG retrieval.
- Groq or OpenAI API for grounded response formatting and summaries.

Suggested API surfaces:

- `POST /logs/patient`
- `POST /logs/caretaker-validation`
- `GET /decision/current`
- `GET /guidance/rag`
- `GET /summaries/doctor-weekly`

## Running

If platform files are not present yet, initialize them with Flutter:

```powershell
flutter create .
flutter run
```

For a web demo:

```powershell
flutter run -d web-server --web-hostname 127.0.0.1 --web-port 8081
```
