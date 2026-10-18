"""Embedding generation and vector similarity."""

from __future__ import annotations

import math

from rag.config import EMBED_MODEL
from rag.ollama import request


def embed(texts: list[str]) -> list[list[float]]:
    result = request("/api/embed", {"model": EMBED_MODEL, "input": texts})
    return result["embeddings"]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0
