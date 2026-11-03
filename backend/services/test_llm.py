"""NVIDIA NIM client unit tests; all HTTP responses are synthetic."""

import json
import os
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from services.llm import (
    LLMError,
    LLMResult,
    _nvidia_nim_chat_ex,
    context_settings,
    generate_chat_response,
    generate_chat_response_ex,
    generate_response,
    generate_response_ex,
)


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
            "NVIDIA_MODEL": "nvidia/nemotron-3.5-bolt-e4b",
            "NVIDIA_RETRIES": "0",
            "NVIDIA_TIMEOUT_SECONDS": "5",
            "NVIDIA_NUM_CTX": "8192",
            "NVIDIA_PROMPT_BUDGET_RATIO": "0.8",
            "NVIDIA_MAX_TOKENS": "1024",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    @patch("services.llm.urlopen")
    def test_grounded_call_preserves_system_and_context(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({
            "choices": [{"message": {"content": "clinical summary"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 18},
        })
        result = generate_response("system rules", "patient vitals facts", "clinical query")
        self.assertEqual(result, "clinical summary")

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://integrate.api.nvidia.test/v1/chat/completions")
        self.assertEqual(request.headers.get("Authorization"), "Bearer nvapi-fake-test-key")

        body = json.loads(request.data)
        self.assertEqual(body["model"], "nvidia/nemotron-3.5-bolt-e4b")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "system rules"})
        self.assertIn("patient vitals facts", body["messages"][1]["content"])
        self.assertEqual(body["temperature"], 0.4)
        self.assertFalse(body["stream"])

    @patch("services.llm.urlopen")
    def test_extended_result_carries_tokens_and_truncation(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({
            "choices": [{"message": {"content": "partially done"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })
        res = generate_response_ex("sys", "ctx", "query")
        self.assertIsInstance(res, LLMResult)
        self.assertEqual(res.content, "partially done")
        self.assertEqual(res.prompt_tokens, 100)
        self.assertEqual(res.completion_tokens, 50)
        self.assertTrue(res.truncated)

    @patch("services.llm.urlopen")
    def test_chat_history_role_mapping(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({
            "choices": [{"message": {"content": "Supportive reply"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
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

    def test_context_settings_budget(self):
        s = context_settings()
        self.assertEqual(s["num_ctx"], 8192)
        self.assertEqual(s["prompt_budget"], int(8192 * 0.8))
        self.assertEqual(s["num_predict"], 1024)

    def test_missing_api_key_configuration(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
            with self.assertRaisesRegex(LLMError, "NVIDIA_API_KEY"):
                _nvidia_nim_chat_ex([], 0.4)

    def test_missing_model_configuration(self):
        with patch.dict(os.environ, {"NVIDIA_MODEL": "", "OLLAMA_MODEL": ""}):
            with self.assertRaisesRegex(LLMError, "NVIDIA_MODEL"):
                _nvidia_nim_chat_ex([], 0.4)

    @patch("services.llm.urlopen", side_effect=FakeHTTPError(401, "Unauthorized", "Invalid API key"))
    def test_unauthorized_error_handled(self, _mock_urlopen):
        with self.assertRaisesRegex(LLMError, "authentication failed"):
            _nvidia_nim_chat_ex([], 0.4)

    @patch("services.llm.urlopen", side_effect=FakeHTTPError(404, "Not Found", "Model not found"))
    def test_not_found_error_handled(self, _mock_urlopen):
        with self.assertRaisesRegex(LLMError, "not found"):
            _nvidia_nim_chat_ex([], 0.4)

    @patch("services.llm.urlopen", side_effect=TimeoutError("Connection timed out"))
    def test_unavailability_is_reported_after_bounded_attempts(self, mock_urlopen):
        with self.assertRaisesRegex(LLMError, "unreachable"):
            _nvidia_nim_chat_ex([], 0.4)
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("services.llm.urlopen", return_value=FakeResponse({"choices": []}))
    def test_empty_choices_is_rejected(self, _mock_urlopen):
        with self.assertRaisesRegex(LLMError, "choices"):
            _nvidia_nim_chat_ex([], 0.4)


if __name__ == "__main__":
    unittest.main()
