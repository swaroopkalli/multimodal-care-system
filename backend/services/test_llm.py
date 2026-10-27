"""Ollama client unit tests; all HTTP responses are synthetic."""

import json
import os
import unittest
from unittest.mock import patch

from services.llm import LLMError, _ollama_chat, generate_chat_response, generate_response


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "OLLAMA_BASE_URL": "http://ollama.test:11434/",
            "OLLAMA_MODEL": "unit-model:tag",
            "OLLAMA_RETRIES": "0",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    @patch("services.llm.urlopen")
    def test_grounded_call_preserves_system_and_context(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"message": {"content": "summary"}})
        self.assertEqual(generate_response("rules", "patient facts", "question"), "summary")
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://ollama.test:11434/api/chat")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "unit-model:tag")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "rules"})
        self.assertIn("patient facts", body["messages"][1]["content"])
        self.assertFalse(body["stream"])

    @patch("services.llm.urlopen")
    def test_chat_history_role_mapping(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({"message": {"content": "hello"}})
        self.assertEqual(generate_chat_response("coach", [
            {"role": "user", "parts": ["hi"]},
            {"role": "model", "parts": ["hello"]},
        ], "again"), "hello")
        body = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertEqual([x["role"] for x in body["messages"]],
                         ["system", "user", "assistant", "user"])

    def test_missing_model_configuration(self):
        with patch.dict(os.environ, {"OLLAMA_MODEL": ""}):
            with self.assertRaisesRegex(LLMError, "OLLAMA_MODEL"):
                _ollama_chat([], 0.4)

    @patch("services.llm.urlopen", side_effect=TimeoutError("slow"))
    def test_unavailability_is_reported_after_bounded_attempts(self, mock_urlopen):
        with self.assertRaisesRegex(LLMError, "unavailable"):
            _ollama_chat([], 0.4)
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("services.llm.urlopen", return_value=FakeResponse({"unexpected": True}))
    def test_malformed_response_is_rejected(self, _mock_urlopen):
        with self.assertRaisesRegex(LLMError, "malformed"):
            _ollama_chat([], 0.4)


if __name__ == "__main__":
    unittest.main()
