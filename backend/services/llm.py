"""Small Ollama client (chat + embeddings) with an explicit context window.

Public API kept from the original module: ``generate_response`` and
``generate_chat_response`` still return plain strings. The ``*_ex`` variants also
return token usage so callers can detect truncation instead of guessing.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMError(RuntimeError):
    """Raised when local inference cannot return a usable response."""


@dataclass
class LLMResult:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    done_reason: str | None = None

    @property
    def truncated(self) -> bool:
        return self.done_reason == "length"


def context_settings() -> dict:
    """Context window numbers shared by the client and the budgeter."""
    num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    ratio = float(os.getenv("OLLAMA_PROMPT_BUDGET_RATIO", "0.8"))
    if num_ctx < 512 or not 0.1 <= ratio <= 0.95:
        raise LLMError("OLLAMA_NUM_CTX must be >= 512 and OLLAMA_PROMPT_BUDGET_RATIO within 0.1-0.95")
    prompt_budget = int(num_ctx * ratio)
    reserve = num_ctx - prompt_budget
    configured = os.getenv("OLLAMA_NUM_PREDICT", "").strip()
    num_predict = min(reserve, int(configured)) if configured else reserve
    return {"num_ctx": num_ctx, "ratio": ratio, "prompt_budget": prompt_budget,
            "response_reserve": reserve, "num_predict": num_predict}


def _post_json(path: str, body: dict, timeout: float, retries: int) -> dict:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    request = Request(f"{base_url}{path}", data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    model = body.get("model")
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
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
        time.sleep(min(1.0 * (2 ** attempt), 5.0))     # model (re)loads can take a few seconds
    raise LLMError("Ollama request failed")


def _timeouts() -> tuple[float, int]:
    try:
        timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
        retries = max(0, int(os.getenv("OLLAMA_RETRIES", "2")))
    except ValueError as exc:
        raise LLMError("OLLAMA_TIMEOUT_SECONDS and OLLAMA_RETRIES must be numeric") from exc
    if timeout <= 0:
        raise LLMError("OLLAMA_TIMEOUT_SECONDS must be greater than zero")
    return timeout, retries


def _ollama_chat_ex(messages: list[dict[str, str]], temperature: float) -> LLMResult:
    model = os.getenv("OLLAMA_MODEL", "").strip()
    if not model:
        raise LLMError("OLLAMA_MODEL must be set to an installed Ollama model tag")
    timeout, retries = _timeouts()
    ctx = context_settings()
    result = _post_json("/api/chat", {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": ctx["num_ctx"], "num_predict": ctx["num_predict"]},
    }, timeout, retries)
    content = result.get("message", {}).get("content") if isinstance(result, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise LLMError("Ollama returned a malformed or empty chat response")
    return LLMResult(content=content, prompt_tokens=result.get("prompt_eval_count"),
                     completion_tokens=result.get("eval_count"), done_reason=result.get("done_reason"))


def _ollama_chat(messages: list[dict[str, str]], temperature: float) -> str:
    return _ollama_chat_ex(messages, temperature).content


def generate_response_ex(system_prompt: str, context: str, query: str, temperature: float = 0.4) -> LLMResult:
    return _ollama_chat_ex([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Context about the patient:\n{context}\n\nUser Query:\n{query}"},
    ], temperature)


def generate_response(system_prompt: str, context: str, query: str) -> str:
    """Generate a grounded response, retaining the former function signature."""
    return generate_response_ex(system_prompt, context, query).content


def build_chat_messages(system_prompt: str, chat_history: list, query: str,
                        context: str | None = None) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]
    for item in chat_history:
        role = "assistant" if item.get("role") == "model" else item.get("role")
        parts = item.get("parts", [])
        if role in {"user", "assistant"} and parts and isinstance(parts[0], str):
            messages.append({"role": role, "content": parts[0]})
    content = query if not context else f"Context about the patient:\n{context}\n\nPatient message:\n{query}"
    messages.append({"role": "user", "content": content})
    return messages


def generate_chat_response_ex(system_prompt: str, chat_history: list, query: str,
                              context: str | None = None, temperature: float = 0.6) -> LLMResult:
    return _ollama_chat_ex(build_chat_messages(system_prompt, chat_history, query, context), temperature)


def generate_chat_response(system_prompt: str, chat_history: list, query: str) -> str:
    """Generate a conversational response while preserving role and history."""
    return generate_chat_response_ex(system_prompt, chat_history, query).content


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts with the configured Ollama embedding model (no silent truncation)."""
    model = os.getenv("OLLAMA_EMBED_MODEL", "").strip()
    if not model:
        raise LLMError("OLLAMA_EMBED_MODEL must be set to an installed embedding model")
    if not texts:
        return []
    timeout, retries = _timeouts()
    result = _post_json("/api/embed", {"model": model, "input": texts, "truncate": False}, timeout, retries)
    vectors = result.get("embeddings") if isinstance(result, dict) else None
    if not isinstance(vectors, list) or len(vectors) != len(texts) or not all(vectors):
        raise LLMError("Ollama returned malformed embeddings")
    return vectors
