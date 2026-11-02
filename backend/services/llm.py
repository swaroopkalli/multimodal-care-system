"""NVIDIA NIM client using MiniMax-M3.1-Flash for conversational and clinical support."""

from __future__ import annotations

import json
import os
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMError(RuntimeError):
    """Raised when LLM inference cannot return a usable response."""


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


def _nvidia_nim_chat(messages: list[dict[str, str]], temperature: float) -> str:
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        raise LLMError(
            "NVIDIA_API_KEY environment variable is not set. "
            "Please obtain an API key from build.nvidia.com and set it in your .env file."
        )

    base_url = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
    model = os.getenv("NVIDIA_MODEL", "minimaxai/minimax-m3.1-flash").strip()
    if not model:
        raise LLMError("NVIDIA_MODEL must be configured (e.g. 'minimaxai/minimax-m3.1-flash')")

    try:
        timeout = float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "60"))
        retries = max(0, int(os.getenv("NVIDIA_RETRIES", "2")))
        max_tokens = int(os.getenv("NVIDIA_MAX_TOKENS", "1024"))
    except ValueError as exc:
        raise LLMError("NVIDIA configuration parameters (timeout, retries, max_tokens) must be numeric") from exc
    if timeout <= 0:
        raise LLMError("NVIDIA_TIMEOUT_SECONDS must be greater than zero")

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
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
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout, context=ssl_context) as response:
                result = json.loads(response.read().decode("utf-8"))

            choices = result.get("choices", [])
            if not choices or not isinstance(choices, list):
                raise LLMError("NVIDIA NIM returned an empty or malformed 'choices' payload")

            content = choices[0].get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise LLMError("NVIDIA NIM returned a malformed or empty chat response")

            return content.strip()

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
            raise LLMError("NVIDIA NIM returned an unparseable response") from exc

        time.sleep(min(0.25 * (2 ** attempt), 1.0))

    raise LLMError("NVIDIA API request failed after retries")


def generate_response(system_prompt: str, context: str, query: str) -> str:
    """Generate a grounded clinical response using patient context and RAG facts."""
    return _nvidia_nim_chat([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Context about the patient:\n{context}\n\nUser Query:\n{query}"},
    ], 0.4)


def generate_chat_response(system_prompt: str, chat_history: list, query: str) -> str:
    """Generate a conversational response preserving chat history and role."""
    messages = [{"role": "system", "content": system_prompt}]
    for item in chat_history:
        role = "assistant" if item.get("role") in {"model", "assistant"} else item.get("role")
        parts = item.get("parts", [])
        if role in {"user", "assistant"} and parts and isinstance(parts[0], str):
            messages.append({"role": role, "content": parts[0]})
    messages.append({"role": "user", "content": query})
    return _nvidia_nim_chat(messages, 0.6)
