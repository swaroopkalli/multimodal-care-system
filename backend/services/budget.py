"""Context-window budgeting, long-input handling and a small LRU cache.

Budget model (OLLAMA_NUM_CTX, OLLAMA_PROMPT_BUDGET_RATIO=0.8):
    prompt budget   = ratio * num_ctx      (system + guard text + facts + retrieval + history + message)
    response reserve = num_ctx - prompt budget (also passed to Ollama as num_predict)
No tokenizer for the local model is available in-process, so token counts are
estimated conservatively and calibrated from the ``prompt_eval_count`` Ollama returns.
"""

from __future__ import annotations

import math
import os
import re
import threading
from collections import OrderedDict
from time import monotonic

from services.llm import context_settings

_chars_per_token = 3.0           # conservative start; calibrated from real usage
_MIN_CPT, _MAX_CPT = 2.0, 5.0
_lock = threading.Lock()


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / _chars_per_token) + 4


def record_usage(prompt_chars: int, prompt_tokens: int | None) -> None:
    """Calibrate chars-per-token from an observed Ollama prompt_eval_count (kept on the cautious side)."""
    global _chars_per_token
    if not prompt_tokens or prompt_tokens < 50 or prompt_chars < 100:
        return
    observed = prompt_chars / prompt_tokens
    with _lock:
        blended = 0.7 * _chars_per_token + 0.3 * observed
        _chars_per_token = max(_MIN_CPT, min(_MAX_CPT, min(blended, observed * 0.9 + 0.1 * blended)))


def prompt_budget() -> int:
    return context_settings()["prompt_budget"]


class InputTooLong(Exception):
    """The message cannot be handled within limits without losing information."""


def max_input_chars() -> int:
    return int(os.getenv("CHAT_MAX_INPUT_CHARS", "20000"))


def split_into_chunks(text: str, max_tokens: int) -> list[str]:
    """Split on paragraph/sentence boundaries into chunks of <= max_tokens. No text is dropped."""
    max_chars = max(200, int((max_tokens - 4) * _chars_per_token))
    pieces: list[str] = []
    for para in re.split(r"(\n\s*\n)", text):
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        for sent in re.split(r"(?<=[.!?])\s+", para):
            while len(sent) > max_chars:                 # unbroken run: split on whitespace, else hard split
                cut = sent.rfind(" ", 0, max_chars)
                cut = cut if cut > max_chars // 2 else max_chars
                pieces.append(sent[:cut])
                sent = sent[cut:].lstrip()
            pieces.append(sent)
    chunks, current = [], ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip() if piece.strip() else current + piece
    if current.strip():
        chunks.append(current)
    return chunks


_DOSE_OR_DRUG = None


def _facts(text: str) -> list[str]:
    global _DOSE_OR_DRUG
    from services.guardrails.output_guard import _DOSE
    from services.guardrails.policy import named_drugs_in
    found = [m.group(0).lower() for m in _DOSE.finditer(text)]
    found += sorted(named_drugs_in(text))
    return list(dict.fromkeys(found))


def ensure_facts_preserved(original: str, condensed: str) -> str:
    """Re-attach any medication names/doses from the original that the summary dropped."""
    lowered = condensed.lower()
    missing = [f for f in _facts(original) if f not in lowered]
    if missing:
        condensed = f"{condensed}\nDetails stated by the patient (kept verbatim): {', '.join(missing)}"
    return condensed


CONDENSE_SYSTEM = (
    "You condense a long patient message so a wellness assistant can read it. Keep EVERY symptom, feeling, "
    "medication name, dose, side effect, date/time and question exactly as stated, in the patient's first-person "
    "voice. Remove only repetition. Do not add facts, interpretation or advice."
)


def condense_long_message(text: str, target_tokens: int, summarize) -> tuple[str, int]:
    """Map-reduce condensation. ``summarize(chunk) -> str``. Returns (condensed_text, passes).

    Raises InputTooLong if the text cannot be brought under ``target_tokens`` in 2 passes.
    The caller keeps the original message; nothing here truncates it.
    """
    if len(text) > max_input_chars():
        raise InputTooLong(f"Message exceeds the {max_input_chars()} character limit")
    current, passes = text, 0
    chunk_tokens = max(300, min(1200, target_tokens))
    while estimate_tokens(current) > target_tokens:
        if passes >= 2:
            raise InputTooLong("Message is too long to condense without losing information")
        parts = [summarize(c) for c in split_into_chunks(current, chunk_tokens)]
        current = "\n".join(p.strip() for p in parts if p and p.strip())
        passes += 1
    return ensure_facts_preserved(text, current), passes


class LRUCache:
    """Thread-safe LRU with optional TTL. Used only for recomputable data (embeddings, built context)."""

    def __init__(self, maxsize: int = 256, ttl: float | None = None):
        self.maxsize, self.ttl = maxsize, ttl
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, stamp = item
            if self.ttl is not None and monotonic() - stamp > self.ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def put(self, key, value) -> None:
        with self._lock:
            self._data[key] = (value, monotonic())
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def invalidate_prefix(self, prefix) -> None:
        """Drop every key whose first element equals ``prefix`` (used for per-patient invalidation)."""
        with self._lock:
            for key in [k for k in self._data if isinstance(k, tuple) and k and k[0] == prefix]:
                del self._data[key]

    def __len__(self) -> int:
        return len(self._data)
