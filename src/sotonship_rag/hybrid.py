"""Keyword tokenisation and rank fusion for hybrid retrieval."""

from __future__ import annotations

import re


TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[./&'-][a-z0-9]+)*", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Tokenise English prose while retaining useful numeric expressions."""
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def reciprocal_rank_fusion(
    vector_ranking: list[int],
    keyword_ranking: list[int],
    rank_constant: int = 60,
) -> dict[int, float]:
    """Combine independent result rankings without normalising their scores."""
    fused: dict[int, float] = {}
    for ranking in (vector_ranking, keyword_ranking):
        for rank, record_index in enumerate(ranking, start=1):
            fused[record_index] = fused.get(record_index, 0.0) + 1.0 / (
                rank_constant + rank
            )
    return fused
