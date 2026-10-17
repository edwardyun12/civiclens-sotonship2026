"""Retrieve the most relevant document chunks."""

from __future__ import annotations

import json

from sotonship_rag.config import INDEX_FILE
from sotonship_rag.embeddings import cosine_similarity, embed


def retrieve(question: str, top_k: int = 5) -> list[dict]:
    if not INDEX_FILE.exists():
        raise RuntimeError("Index not found. Run `sotonship-rag index` first.")

    index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    query_vector = embed([question])[0]
    scored = []
    for record in index["records"]:
        item = {key: value for key, value in record.items() if key != "embedding"}
        item["score"] = cosine_similarity(query_vector, record["embedding"])
        scored.append(item)
    return sorted(scored, key=lambda item: item["score"], reverse=True)[:top_k]
