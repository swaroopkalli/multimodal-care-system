#!/usr/bin/env bash
set -euo pipefail

# Creates an isolated synthetic doctor, caretaker, and patient, then populates
# context only through the application's authenticated HTTP API.

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:5001}"
PATIENT_NAME="${PATIENT_NAME:-Demo Patient}"
DOCTOR_NAME="${DOCTOR_NAME:-Demo Doctor}"
CARETAKER_NAME="${CARETAKER_NAME:-Demo Caretaker}"
SEED_MOOD="${SEED_MOOD:-3}"
SEED_STRESS="${SEED_STRESS:-6}"
SEED_SLEEP_HOURS="${SEED_SLEEP_HOURS:-5.5}"
SEED_ENERGY="${SEED_ENERGY:-4}"
SEED_MEDICATION_NAME="${SEED_MEDICATION_NAME:-sertraline}"
SEED_MEDICATION_TYPE="${SEED_MEDICATION_TYPE:-synthetic demo record}"
SEED_MEDICATION_DURATION="${SEED_MEDICATION_DURATION:-14}"
SEED_SUFFIX="$(date +%s)-$(openssl rand -hex 3)"

for command in curl jq openssl; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$command" >&2
    exit 1
  }
done

api_post() {
  local path="$1" payload="$2" token="${3:-}"
  local args=(--silent --show-error --fail-with-body -H 'Content-Type: application/json'
              -X POST --data-binary @-)
  if [[ -n "$token" ]]; then
    args+=(-H "Authorization: Bearer $token")
  fi
  curl "${args[@]}" "${API_BASE_URL%/}${path}" <<<"$payload"
}

api_get() {
  local path="$1" token="$2"
  curl --silent --show-error --fail-with-body \
    -H "Authorization: Bearer $token" "${API_BASE_URL%/}${path}"
}

login() {
  local role="$1" username="$2" password="$3"
  local payload
  payload="$(jq -n --arg username "$username" --arg password "$password" \
    '{username:$username,password:$password}')"
  api_post "/api/auth/login/${role}" "$payload" | jq -er '.token'
}

DOCTOR_USERNAME="demo-doctor-${SEED_SUFFIX}"
CARETAKER_USERNAME="demo-caretaker-${SEED_SUFFIX}"
PATIENT_USERNAME="demo-patient-${SEED_SUFFIX}"
DOCTOR_PASSWORD="$(openssl rand -hex 16)"
CARETAKER_PASSWORD="$(openssl rand -hex 16)"
PATIENT_PASSWORD="$(openssl rand -hex 16)"

printf 'Registering synthetic demo accounts at %s ...\n' "$API_BASE_URL"

DOCTOR_JSON="$(jq -n --arg username "$DOCTOR_USERNAME" --arg name "$DOCTOR_NAME" \
  --arg password "$DOCTOR_PASSWORD" '{username:$username,name:$name,password:$password}')"
DOCTOR_ID="$(api_post /api/auth/register/doctor "$DOCTOR_JSON" | jq -er '.user.id')"

CARETAKER_JSON="$(jq -n --arg username "$CARETAKER_USERNAME" --arg name "$CARETAKER_NAME" \
  --arg password "$CARETAKER_PASSWORD" '{username:$username,name:$name,password:$password}')"
CARETAKER_ID="$(api_post /api/auth/register/caretaker "$CARETAKER_JSON" | jq -er '.user.id')"

PATIENT_JSON="$(jq -n --arg username "$PATIENT_USERNAME" --arg name "$PATIENT_NAME" \
  --arg password "$PATIENT_PASSWORD" --arg doctor "$DOCTOR_USERNAME" \
  --arg caretaker "$CARETAKER_USERNAME" \
  '{username:$username,name:$name,password:$password,doctor_username:$doctor,caretaker_username:$caretaker}')"
PATIENT_ID="$(api_post /api/auth/register/patient "$PATIENT_JSON" | jq -er '.user.id')"

DOCTOR_TOKEN="$(login doctor "$DOCTOR_USERNAME" "$DOCTOR_PASSWORD")"
CARETAKER_TOKEN="$(login caretaker "$CARETAKER_USERNAME" "$CARETAKER_PASSWORD")"
PATIENT_TOKEN="$(login patient "$PATIENT_USERNAME" "$PATIENT_PASSWORD")"

# All clinical-looking values below are synthetic demo inputs, never real records.
CHECKIN_JSON="$(jq -n --argjson mood "$SEED_MOOD" --argjson stress "$SEED_STRESS" \
  --argjson sleep "$SEED_SLEEP_HOURS" --argjson energy "$SEED_ENERGY" \
  '{mood:$mood,stress:$stress,sleep_hours:$sleep,energy:$energy,side_effects:["none reported"]}')"
api_post /api/patient/checkin "$CHECKIN_JSON" "$PATIENT_TOKEN" >/dev/null

JOURNAL_TEXT="[SIMULATED DEMO DATA] I had a stressful day and slept less than usual. I would like help noticing patterns in my sleep and mood."
JOURNAL_JSON="$(jq -n --arg entry "$JOURNAL_TEXT" '{entry:$entry}')"
JOURNAL_ID="$(api_post /api/patient/journal "$JOURNAL_JSON" "$PATIENT_TOKEN" | jq -er '.id')"

NOTE_TEXT="[SIMULATED DEMO DATA] Patient reports a stressful week and shorter sleep. This is fictional test context, not a clinical assessment or treatment instruction."
NOTE_JSON="$(jq -n --arg note "$NOTE_TEXT" --argjson patient_id "$PATIENT_ID" \
  '{note:$note,patient_id:$patient_id}')"
NOTE_ID="$(api_post /api/doctor_notes "$NOTE_JSON" "$DOCTOR_TOKEN" | jq -er '.note_id')"

MEDICATION_JSON="$(jq -n --arg name "$SEED_MEDICATION_NAME" --arg type "$SEED_MEDICATION_TYPE" \
  --argjson duration "$SEED_MEDICATION_DURATION" --argjson patient_id "$PATIENT_ID" \
  '{name:$name,type:$type,duration:$duration,patient_id:$patient_id}')"
MEDICATION_ID="$(api_post /api/medications "$MEDICATION_JSON" "$DOCTOR_TOKEN" | jq -er '.id')"

OBSERVATION_JSON='{"patient_id":'"$PATIENT_ID"',"did_not_sleep":true,"restless":true,"seems_better":false,"medication_confirmed":null}'
OBSERVATION_ID="$(api_post /api/caretaker/observations "$OBSERVATION_JSON" "$CARETAKER_TOKEN" | jq -er '.id')"

SUMMARY="$(api_get "/api/patients/${PATIENT_ID}/summary" "$PATIENT_TOKEN")"

printf '\nCreated synthetic demo patient and populated API context.\n'
printf 'patient_id: %s\npatient_username: %s\npatient_password: %s\n' \
  "$PATIENT_ID" "$PATIENT_USERNAME" "$PATIENT_PASSWORD"
printf 'doctor_username: %s\ndoctor_password: %s\n' "$DOCTOR_USERNAME" "$DOCTOR_PASSWORD"
printf 'caretaker_username: %s\ncaretaker_password: %s\n' "$CARETAKER_USERNAME" "$CARETAKER_PASSWORD"
printf 'doctor_id: %s\ncaretaker_id: %s\njournal_id: %s\nnote_id: %s\nmedication_id: %s\nobservation_id: %s\n' \
  "$DOCTOR_ID" "$CARETAKER_ID" "$JOURNAL_ID" "$NOTE_ID" "$MEDICATION_ID" "$OBSERVATION_ID"
printf '\nPatient summary returned by API:\n%s\n' "$(jq . <<<"$SUMMARY")"
printf '\nJournal and doctor note are queued for Neo4j sync. For existing installations, re-embed with:\n'
printf '  cd backend && python -m services.graph.sync backfill\n'
