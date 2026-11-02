"""NVIDIA NIM client unit tests; all HTTP responses are synthetic."""

import json
import os
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from services.llm import LLMError, _nvidia_nim_chat, generate_chat_response, generate_response


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class FakeHTTPError(HTTPError):
    def __init__(self, code, msg="Error", body="detail"):
        super().__init__("http://test", code, msg, {}, None)
        self._body = body.encode("utf-8")

    def read(self):
        return self._body


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "NVIDIA_API_KEY": "nvapi-fake-test-key",
            "NVIDIA_BASE_URL": "https://integrate.api.nvidia.test/v1",
            "NVIDIA_MODEL": "minimaxai/minimax-m3.1-flash",
            "NVIDIA_RETRIES": "0",
            "NVIDIA_TIMEOUT_SECONDS": "5",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    @patch("services.llm.urlopen")
    def test_grounded_call_preserves_system_and_context(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({
            "choices": [{"message": {"content": "clinical summary"}}]
        })
        result = generate_response("system rules", "patient vitals facts", "clinical query")
        self.assertEqual(result, "clinical summary")

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://integrate.api.nvidia.test/v1/chat/completions")
        self.assertEqual(request.headers.get("Authorization"), "Bearer nvapi-fake-test-key")

        body = json.loads(request.data)
        self.assertEqual(body["model"], "minimaxai/minimax-m3.1-flash")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "system rules"})
        self.assertIn("patient vitals facts", body["messages"][1]["content"])
        self.assertEqual(body["temperature"], 0.4)
        self.assertFalse(body["stream"])

    @patch("services.llm.urlopen")
    def test_chat_history_role_mapping(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({
            "choices": [{"message": {"content": "Supportive reply"}}]
        })
        result = generate_chat_response("wellness coach", [
            {"role": "user", "parts": ["I felt anxious today"]},
            {"role": "model", "parts": ["I understand, take deep breaths"]},
        ], "What exercises should I try?")
        self.assertEqual(result, "Supportive reply")

        body = json.loads(mock_urlopen.call_args.args[0].data)
        roles = [msg["role"] for msg in body["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(body["temperature"], 0.6)

    def test_missing_api_key_configuration(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
            with self.assertRaisesRegex(LLMError, "NVIDIA_API_KEY"):
                _nvidia_nim_chat([], 0.4)

    def test_missing_model_configuration(self):
        with patch.dict(os.environ, {"NVIDIA_MODEL": ""}):
            with self.assertRaisesRegex(LLMError, "NVIDIA_MODEL"):
                _nvidia_nim_chat([], 0.4)

    def test_invalid_numeric_parameters(self):
        with patch.dict(os.environ, {"NVIDIA_TIMEOUT_SECONDS": "invalid"}):
            with self.assertRaisesRegex(LLMError, "numeric"):
                _nvidia_nim_chat([], 0.4)

    @patch("services.llm.urlopen", side_effect=FakeHTTPError(401, "Unauthorized", "Invalid API key"))
    def test_unauthorized_error_handled(self, _mock_urlopen):
        with self.assertRaisesRegex(LLMError, "authentication failed"):
            _nvidia_nim_chat([], 0.4)

    @patch("services.llm.urlopen", side_effect=FakeHTTPError(404, "Not Found", "Model not found"))
    def test_not_found_error_handled(self, _mock_urlopen):
        with self.assertRaisesRegex(LLMError, "not found"):
            _nvidia_nim_chat([], 0.4)

    @patch("services.llm.urlopen", side_effect=TimeoutError("Connection timed out"))
    def test_unavailability_is_reported_after_bounded_attempts(self, mock_urlopen):
        with self.assertRaisesRegex(LLMError, "unreachable"):
            _nvidia_nim_chat([], 0.4)
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("services.llm.urlopen", return_value=FakeResponse({"choices": []}))
    def test_empty_choices_is_rejected(self, _mock_urlopen):
        with self.assertRaisesRegex(LLMError, "choices"):
            _nvidia_nim_chat([], 0.4)

    @patch("services.llm.urlopen", return_value=FakeResponse({"choices": [{"message": {"content": ""}}]}))
    def test_empty_content_is_rejected(self, _mock_urlopen):
        with self.assertRaisesRegex(LLMError, "malformed or empty"):
            _nvidia_nim_chat([], 0.4)


if __name__ == "__main__":
    unittest.main()
