"""Embeddings via Ollama (nomic-embed-text style prefixes), with chunk-and-average for long texts."""

from __future__ import annotations

import hashlib
import math
import os

from services.budget import LRUCache, split_into_chunks
from services.graph.client import GraphUnavailable
from services.llm import LLMError, embed_texts

_cache = LRUCache(maxsize=512)
CHUNK_TOKENS = 400          # well inside the embedding model's window; nothing is truncated


def model_name() -> str:
    return os.getenv("NVIDIA_EMBED_MODEL") or os.getenv("LLM_EMBED_MODEL") or os.getenv("OLLAMA_EMBED_MODEL", "")


def _embed(prefix: str, text: str) -> list[float]:
    chunks = split_into_chunks(text.strip(), CHUNK_TOKENS) or [text]
    try:
        vectors = embed_texts([f"{prefix}{c}" for c in chunks])
    except LLMError as exc:
        raise GraphUnavailable(f"embedding failed: {exc}") from exc
    if not vectors:
        raise GraphUnavailable("embedding service is not configured")
    if len(vectors) == 1:
        return vectors[0]
    summed = [sum(col) for col in zip(*vectors)]
    norm = math.sqrt(sum(x * x for x in summed)) or 1.0
    return [x / norm for x in summed]


def embed_document(text: str) -> list[float]:
    return _embed("search_document: ", text)


def embed_query(text: str, patient_id: int | None = None) -> list[float]:
    key = (patient_id, hashlib.sha256(text.encode()).hexdigest())
    hit = _cache.get(key)
    if hit is None:
        hit = _embed("search_query: ", text)
        _cache.put(key, hit)
    return hit
