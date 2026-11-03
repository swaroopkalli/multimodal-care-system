"""LLM client supporting NVIDIA NIM Cloud API and local Ollama inference."""

from __future__ import annotations

import json
import os
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class LLMError(RuntimeError):
    """Raised when inference cannot return a usable response."""


@dataclass
class LLMResult:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    done_reason: str | None = None

    @property
    def truncated(self) -> bool:
        return self.done_reason == "length"


def _get_ssl_context() -> ssl.SSLContext:
    if os.getenv("NVIDIA_SSL_VERIFY", "true").lower() in {"0", "false", "no"}:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    try:
        # pyrefly: ignore[missing-import]
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def is_nvidia_configured() -> bool:
    """Return True if NVIDIA NIM API key is configured."""
    return bool(os.getenv("NVIDIA_API_KEY", "").strip())


def context_settings() -> dict:
    """Context window numbers shared by the client and the budgeter."""
    num_ctx = int(os.getenv("NVIDIA_NUM_CTX") or os.getenv("LLM_NUM_CTX") or os.getenv("OLLAMA_NUM_CTX") or "8192")
    ratio = float(os.getenv("NVIDIA_PROMPT_BUDGET_RATIO") or os.getenv("LLM_PROMPT_BUDGET_RATIO") or os.getenv("OLLAMA_PROMPT_BUDGET_RATIO") or "0.8")
    if num_ctx < 512 or not 0.1 <= ratio <= 0.95:
        raise LLMError("NUM_CTX must be >= 512 and PROMPT_BUDGET_RATIO within 0.1-0.95")
    prompt_budget = int(num_ctx * ratio)
    reserve = num_ctx - prompt_budget
    if os.getenv("NVIDIA_MAX_TOKENS", "").strip():
        configured = os.getenv("NVIDIA_MAX_TOKENS", "").strip()
    elif "OLLAMA_NUM_PREDICT" in os.environ:
        configured = os.environ["OLLAMA_NUM_PREDICT"].strip()
    else:
        configured = ""
    num_predict = min(reserve, int(configured)) if configured else reserve
    return {
        "num_ctx": num_ctx,
        "ratio": ratio,
        "prompt_budget": prompt_budget,
        "response_reserve": reserve,
        "num_predict": num_predict,
    }


def _timeouts() -> tuple[float, int]:
    try:
        timeout = float(os.getenv("NVIDIA_TIMEOUT_SECONDS") or os.getenv("LLM_TIMEOUT_SECONDS") or os.getenv("OLLAMA_TIMEOUT_SECONDS") or "60")
        retries = max(0, int(os.getenv("NVIDIA_RETRIES") or os.getenv("LLM_RETRIES") or os.getenv("OLLAMA_RETRIES") or "2"))
    except ValueError as exc:
        raise LLMError("TIMEOUT_SECONDS and RETRIES must be numeric") from exc
    if timeout <= 0:
        raise LLMError("TIMEOUT_SECONDS must be greater than zero")
    return timeout, retries


def _nvidia_nim_chat_ex(messages: list[dict[str, str]], temperature: float) -> LLMResult:
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise LLMError(
            "NVIDIA_API_KEY environment variable is not set. "
            "Please obtain an API key from build.nvidia.com and set it in your .env file."
        )

    base_url = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
    model = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-bolt-e4b").strip()
    if not model:
        raise LLMError("NVIDIA_MODEL must be configured (e.g. 'nvidia/nemotron-3.5-bolt-e4b')")

    timeout, retries = _timeouts()
    ctx = context_settings()

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": ctx["num_predict"],
        "stream": False,
    }).encode("utf-8")

    if base_url.endswith("/chat/completions"):
        endpoint = base_url
    else:
        endpoint = f"{base_url}/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    request = Request(endpoint, data=payload, headers=headers, method="POST")
    ssl_context = _get_ssl_context()
    urlopen_kwargs = {"context": ssl_context} if ssl_context is not None else {}

    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout, **urlopen_kwargs) as response:
                result = json.loads(response.read().decode("utf-8"))

            choices = result.get("choices", [])
            if not choices or not isinstance(choices, list):
                raise LLMError("NVIDIA NIM returned an empty or malformed 'choices' payload")

            choice = choices[0]
            content = choice.get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise LLMError("NVIDIA NIM returned a malformed or empty chat response")

            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
            completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
            done_reason = choice.get("finish_reason")

            return LLMResult(
                content=content.strip(),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                done_reason=done_reason,
            )

        except HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""

            if exc.code == 401:
                raise LLMError("NVIDIA API authentication failed (HTTP 401). Please verify your NVIDIA_API_KEY.") from exc
            if exc.code == 404:
                raise LLMError(f"NVIDIA model '{model}' not found or endpoint invalid (HTTP 404): {detail[:200]}") from exc
            if exc.code == 429:
                if attempt >= retries:
                    raise LLMError(f"NVIDIA API rate limit exceeded (HTTP 429): {detail[:200]}") from exc
            elif exc.code < 500 or attempt >= retries:
                raise LLMError(f"NVIDIA API request failed (HTTP {exc.code}): {detail[:300]}") from exc

        except (URLError, TimeoutError, OSError) as exc:
            if attempt >= retries:
                raise LLMError(f"NVIDIA API endpoint is unreachable at {base_url}: {exc}") from exc

        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError, TypeError) as exc:
            raise LLMError("NVIDIA NIM returned an invalid response") from exc

        time.sleep(min(0.25 * (2 ** attempt), 1.0))

    raise LLMError("NVIDIA API request failed after retries")


def _ollama_post_json(path: str, body: dict, timeout: float, retries: int) -> dict:
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
        time.sleep(min(1.0 * (2 ** attempt), 5.0))
    raise LLMError("Ollama request failed")


def _ollama_chat_ex_native(messages: list[dict[str, str]], temperature: float) -> LLMResult:
    model = (os.getenv("OLLAMA_MODEL") or os.getenv("NVIDIA_MODEL") or "llama3.2:3b").strip()
    if not model:
        raise LLMError("OLLAMA_MODEL must be set to an installed Ollama model tag")
    timeout, retries = _timeouts()
    ctx = context_settings()
    result = _ollama_post_json("/api/chat", {
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


def chat_ex(messages: list[dict[str, str]], temperature: float = 0.4) -> LLMResult:
    if is_nvidia_configured():
        return _nvidia_nim_chat_ex(messages, temperature)
    return _ollama_chat_ex_native(messages, temperature)


def chat(messages: list[dict[str, str]], temperature: float = 0.4) -> str:
    return chat_ex(messages, temperature).content


_chat_ex = chat_ex
_chat = chat
_ollama_chat_ex = chat_ex
_ollama_chat = chat
_nvidia_nim_chat = lambda msgs, temp: _nvidia_nim_chat_ex(msgs, temp).content


def generate_response_ex(system_prompt: str, context: str, query: str, temperature: float = 0.4) -> LLMResult:
    return _chat_ex([
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
        role = "assistant" if item.get("role") in {"model", "assistant"} else item.get("role")
        parts = item.get("parts", [])
        if role in {"user", "assistant"} and parts and isinstance(parts[0], str):
            messages.append({"role": role, "content": parts[0]})
    content = query if not context else f"Context about the patient:\n{context}\n\nPatient message:\n{query}"
    messages.append({"role": "user", "content": content})
    return messages


def generate_chat_response_ex(system_prompt: str, chat_history: list, query: str,
                              context: str | None = None, temperature: float = 0.6) -> LLMResult:
    return _chat_ex(build_chat_messages(system_prompt, chat_history, query, context), temperature)


def generate_chat_response(system_prompt: str, chat_history: list, query: str) -> str:
    """Generate a conversational response while preserving role and history."""
    return generate_chat_response_ex(system_prompt, chat_history, query).content


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts via configured model if available, or return empty list."""
    model = (os.getenv("NVIDIA_EMBED_MODEL") or os.getenv("LLM_EMBED_MODEL") or os.getenv("OLLAMA_EMBED_MODEL", "")).strip()
    base_url = (os.getenv("OLLAMA_BASE_URL") or "").strip().rstrip("/")
    if not model or not base_url or not texts:
        return []
    timeout, retries = _timeouts()
    request = Request(f"{base_url}/api/embed", data=json.dumps({"model": model, "input": texts, "truncate": False}).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            vectors = result.get("embeddings") if isinstance(result, dict) else None
            if not isinstance(vectors, list) or len(vectors) != len(texts) or not all(vectors):
                raise LLMError("Ollama returned malformed embeddings")
            return vectors
        except Exception as exc:
            if attempt >= retries:
                raise LLMError(f"Embedding failed: {exc}") from exc
            time.sleep(1.0)
    return []
