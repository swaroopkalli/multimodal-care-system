"""Automated test suite for the Clinician-in-the-Loop system.

Verifies:
1. Clinical alert recording and deduplication.
2. Severe distress and side-effect check-ins triggering clinical alerts.
3. Chat crisis guardrail triggering clinical alert with patient safety response.
4. Active patient care directives creation, retrieval, and priority 0 context injection.
5. Doctor journal replies and patient journal retrieval with reply + timestamp.
6. Doctor/caretaker alert listing and acknowledgment.
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from endpoints.alerts import record_alert
from services.context import _build_static_sections


class ClinicianLoopUnitTests(unittest.TestCase):
    def test_record_alert_deduplication(self):
        """Alerts of the same type within 6 hours are deduplicated."""
        mock_cur = MagicMock()
        # First call: existing unacknowledged alert found -> should return None
        mock_cur.fetchone.return_value = {"id": 101}
        alert_id = record_alert(mock_cur, 1, "severe_distress", "critical", "Stress 9/10")
        self.assertIsNone(alert_id)

        # Second call: no existing alert found -> inserts new row
        mock_cur.fetchone.side_effect = [None, {"id": 102}]
        alert_id2 = record_alert(mock_cur, 1, "severe_distress", "critical", "Stress 9/10")
        self.assertEqual(alert_id2, 102)

    def test_directives_injected_at_priority_zero(self):
        """Active doctor care directives are injected into context at priority 0."""
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [
            {"name": "Alice Patient"},  # patient lookup
        ]
        mock_cur.fetchall.side_effect = [
            [{"directive": "Maintain strict bedtime before 10:30 PM"}],  # directives
            [],  # medications
            [],  # wearable daily
            [],  # anomalies
            [],  # checkins
        ]

        sections = _build_static_sections(mock_cur, patient_id=1, staff=False)
        directive_sec = next((s for s in sections if s["name"] == "directives"), None)
        self.assertIsNotNone(directive_sec, "Directives section must be present")
        self.assertEqual(directive_sec["priority"], 0, "Directives must be priority 0")
        self.assertIn("Maintain strict bedtime before 10:30 PM", directive_sec["text"])

    def test_chat_crisis_alert_trigger(self):
        """A crisis query triggers check_input crisis action without jailbreak."""
        from services.guardrails.input_guard import check_input
        decision = check_input("I cannot take this anymore, I want to end my life tonight", "patient", [])
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.action, "crisis")
        self.assertIn("crisis line", decision.message)
        # Verify patient does not see any scary alert jargon or error codes
        self.assertNotIn("clinical_alert", decision.message)
        self.assertNotIn("severity: critical", decision.message)

    @patch("endpoints.authz.verify_jwt_in_request")
    @patch("endpoints.authz.get_jwt", return_value={"role": "doctor"})
    @patch("endpoints.doctor_notes.get_db_connection")
    @patch("endpoints.doctor_notes.current_user")
    @patch("endpoints.doctor_notes.resolve_patient_id")
    def test_add_patient_directive(self, mock_resolve, mock_user, mock_conn, mock_jwt, mock_verify):
        """Doctor can create a patient care directive."""
        from endpoints.doctor_notes import add_patient_directive
        from app import app
        mock_user.return_value = (5, "doctor")
        mock_resolve.return_value = (1, None)

        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"id": 42, "created_at": datetime.now(timezone.utc)}
        mock_conn.return_value.cursor.return_value = mock_cur

        with app.test_request_context(
            "/api/doctor/directives",
            method="POST",
            json={"patient_id": 1, "directive": "Limit caffeine after 2 PM"}
        ):
            resp, code = add_patient_directive()
            self.assertEqual(code, 201)
            data = resp.get_json()
            self.assertEqual(data["id"], 42)
            self.assertEqual(data["directive"], "Limit caffeine after 2 PM")
            self.assertTrue(data["is_active"])

    @patch("endpoints.authz.verify_jwt_in_request")
    @patch("endpoints.authz.get_jwt", return_value={"role": "doctor"})
    @patch("endpoints.doctor_notes.get_db_connection")
    @patch("endpoints.doctor_notes.current_user")
    def test_add_journal_reply(self, mock_user, mock_conn, mock_jwt, mock_verify):
        """Doctor can reply to a patient journal entry."""
        from endpoints.doctor_notes import add_journal_reply
        from app import app
        mock_user.return_value = (5, "doctor")

        mock_cur = MagicMock()
        # Row 1: journal entry exists and is assigned to this doctor
        mock_cur.fetchone.side_effect = [
            {"id": 10, "patient_id": 1},
            {"doctor_reply_at": datetime.now(timezone.utc)},
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        with app.test_request_context(
            "/api/doctor/journal_reply",
            method="POST",
            json={"journal_id": 10, "reply": "Thank you for sharing, take rest today."}
        ):
            resp, code = add_journal_reply()
            self.assertEqual(code, 200)
            data = resp.get_json()
            self.assertEqual(data["journal_id"], 10)
            self.assertEqual(data["doctor_reply"], "Thank you for sharing, take rest today.")
            self.assertIsNotNone(data["doctor_reply_at"])

    @patch("endpoints.authz.verify_jwt_in_request")
    @patch("endpoints.authz.get_jwt", return_value={"role": "doctor"})
    @patch("endpoints.alerts.get_db_connection")
    @patch("endpoints.alerts.current_user")
    def test_list_and_acknowledge_alerts(self, mock_user, mock_conn, mock_jwt, mock_verify):
        """Doctor or caretaker can view and acknowledge clinical alerts."""
        from endpoints.alerts import list_alerts, acknowledge_alert
        from app import app
        mock_user.return_value = (5, "doctor")

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            {
                "id": 1,
                "patient_id": 1,
                "patient_name": "Alice",
                "alert_type": "severe_distress",
                "severity": "critical",
                "message": "Severe distress check-in: Stress 9/10, Mood 1/5",
                "source": "checkin",
                "is_acknowledged": False,
                "acknowledged_at": None,
                "created_at": datetime.now(timezone.utc),
            }
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        with app.test_request_context("/api/alerts", method="GET"):
            resp, code = list_alerts()
            self.assertEqual(code, 200)
            data = resp.get_json()
            self.assertEqual(len(data["alerts"]), 1)
            self.assertEqual(data["alerts"][0]["severity"], "critical")

        # Now test acknowledge
        mock_cur.fetchone.return_value = {"id": 1}
        with app.test_request_context("/api/alerts/1/acknowledge", method="POST"):
            resp, code = acknowledge_alert(1)
            self.assertEqual(code, 200)
            data = resp.get_json()
            self.assertEqual(data["id"], 1)

    @patch("endpoints.authz.verify_jwt_in_request")
    @patch("endpoints.authz.get_jwt", return_value={"role": "doctor"})
    @patch("endpoints.doctor_notes.get_db_connection")
    @patch("endpoints.doctor_notes.resolve_patient_id")
    def test_get_patient_chat_history(self, mock_resolve, mock_conn, mock_jwt, mock_verify):
        """Doctor can retrieve patient chatbot history using created_at column."""
        from endpoints.doctor_notes import get_patient_chat_history
        from app import app
        mock_resolve.return_value = (202, None)

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            {
                "id": 1,
                "patient_id": 202,
                "role": "patient",
                "query": "How can I improve my sleep?",
                "response": "Try relaxing without screens.",
                "input_handling": "direct",
                "created_at": datetime.now(timezone.utc),
            }
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        with app.test_request_context("/api/patients/202/chat_history", method="GET"):
            resp, code = get_patient_chat_history(202)
            self.assertEqual(code, 200)
            data = resp.get_json()
            self.assertIn("chat_history", data)
            self.assertEqual(len(data["chat_history"]), 1)
            self.assertIn("timestamp", data["chat_history"][0])
            self.assertIn("created_at", data["chat_history"][0])
            self.assertEqual(data["chat_history"][0]["query"], "How can I improve my sleep?")

    @patch("endpoints.authz.verify_jwt_in_request")
    @patch("endpoints.authz.get_jwt", return_value={"role": "doctor"})
    @patch("endpoints.doctor_notes.get_db_connection")
    @patch("endpoints.doctor_notes.resolve_patient_id")
    def test_get_patient_chat_digest(self, mock_resolve, mock_conn, mock_jwt, mock_verify):
        """Doctor can retrieve executive clinical digest and flagged exchanges."""
        from endpoints.doctor_notes import get_patient_chat_digest
        from app import app
        mock_resolve.return_value = (202, None)

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            {
                "id": 1,
                "patient_id": 202,
                "role": "patient",
                "query": "I am having severe insomnia and waking up feeling exhausted.",
                "response": "I hear how difficult that is. Rest is important.",
                "input_handling": "direct",
                "created_at": datetime.now(timezone.utc),
            },
            {
                "id": 2,
                "patient_id": 202,
                "role": "patient",
                "query": "I feel really anxious today about my heart rate.",
                "response": "Take a gentle breath with me.",
                "input_handling": "direct",
                "created_at": datetime.now(timezone.utc),
            }
        ]
        mock_conn.return_value.cursor.return_value = mock_cur

        with app.test_request_context("/api/patients/202/chat_digest", method="GET"):
            resp, code = get_patient_chat_digest(202)
            self.assertEqual(code, 200)
            data = resp.get_json()
            self.assertIn("digest", data)
            self.assertIn("flagged_exchanges", data)
            self.assertEqual(data["total_turns"], 2)
            self.assertGreaterEqual(len(data["flagged_exchanges"]), 1)
            categories = [fx["category"] for fx in data["flagged_exchanges"]]
            self.assertTrue(any("Sleep" in c for c in categories))
            self.assertTrue(any("Anxiety" in c for c in categories))


if __name__ == "__main__":
    unittest.main()
