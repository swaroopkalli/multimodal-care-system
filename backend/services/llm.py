"""Small Ollama client preserving the chat service's existing public API."""

from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMError(RuntimeError):
    """Raised when local inference cannot return a usable response."""


def _ollama_chat(messages: list[dict[str, str]], temperature: float) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "").strip()
    if not model:
        raise LLMError("OLLAMA_MODEL must be set to an installed Ollama model tag")
    try:
        timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
        retries = max(0, int(os.getenv("OLLAMA_RETRIES", "2")))
    except ValueError as exc:
        raise LLMError("OLLAMA_TIMEOUT_SECONDS and OLLAMA_RETRIES must be numeric") from exc
    if timeout <= 0:
        raise LLMError("OLLAMA_TIMEOUT_SECONDS must be greater than zero")

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }).encode("utf-8")
    request = Request(
        f"{base_url}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            content = result.get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise LLMError("Ollama returned a malformed or empty chat response")
            return content
        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            if exc.code == 404:
                raise LLMError(f"Ollama model '{model}' is unavailable; pull it first") from exc
            if exc.code < 500 or attempt >= retries:
                raise LLMError(f"Ollama request failed (HTTP {exc.code}): {detail[:300]}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt >= retries:
                raise LLMError(f"Ollama is unavailable at {base_url}: {exc}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError, TypeError) as exc:
            raise LLMError("Ollama returned an invalid response") from exc
        time.sleep(min(0.25 * (2 ** attempt), 1.0))
    raise LLMError("Ollama request failed")


def generate_response(system_prompt: str, context: str, query: str) -> str:
    """Generate a grounded response, retaining the former function signature."""
    return _ollama_chat([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Context about the patient:\n{context}\n\nUser Query:\n{query}"},
    ], 0.4)


def generate_chat_response(system_prompt: str, chat_history: list, query: str) -> str:
    """Generate a conversational response while preserving role and history."""
    messages = [{"role": "system", "content": system_prompt}]
    for item in chat_history:
        role = "assistant" if item.get("role") == "model" else item.get("role")
        parts = item.get("parts", [])
        if role in {"user", "assistant"} and parts and isinstance(parts[0], str):
            messages.append({"role": role, "content": parts[0]})
    messages.append({"role": "user", "content": query})
    return _ollama_chat(messages, 0.6)
