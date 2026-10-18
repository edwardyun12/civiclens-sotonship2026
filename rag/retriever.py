"""Retrieve the most relevant document chunks."""

from __future__ import annotations

import json

from rank_bm25 import BM25Okapi

from rag.citations import extract_pdf_pages, format_citation
from rag.config import INDEX_FILE, PROJECT_ROOT
from rag.embeddings import cosine_similarity, embed
from rag.hybrid import reciprocal_rank_fusion, tokenize


def retrieve(question: str, top_k: int = 3) -> list[dict]:
    if not INDEX_FILE.exists():
        raise RuntimeError("Index not found. Run `sotonship-rag index` first.")

    index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    records = [
        record
        for record in index["records"]
        if (PROJECT_ROOT / record["source"]).is_file()
    ]
    if not records:
        raise RuntimeError(
            "The index contains no records backed by current source files. "
            "Ask the data team to rebuild the document index."
        )
    query_vector = embed([question])[0]
    vector_scores = [
        cosine_similarity(query_vector, record["embedding"])
        for record in records
    ]

    tokenized_corpus = [tokenize(record["text"]) for record in records]
    bm25 = BM25Okapi(tokenized_corpus)
    bm25_scores = list(bm25.get_scores(tokenize(question)))

    candidate_pool = min(len(records), max(10, top_k * 4))
    vector_ranking = sorted(
        range(len(records)),
        key=lambda record_index: vector_scores[record_index],
        reverse=True,
    )[:candidate_pool]
    keyword_ranking = []
    if bm25_scores and max(bm25_scores) > 0:
        keyword_ranking = sorted(
            range(len(records)),
            key=lambda record_index: bm25_scores[record_index],
            reverse=True,
        )[:candidate_pool]

    fused_scores = reciprocal_rank_fusion(vector_ranking, keyword_ranking)
    fused_ranking = sorted(
        fused_scores,
        key=lambda record_index: (
            fused_scores[record_index],
            vector_scores[record_index],
        ),
        reverse=True,
    )

    scored = []
    latest_page_by_source: dict[str, int] = {}
    prepared_records = []
    for record_index, record in enumerate(records):
        item = {key: value for key, value in record.items() if key != "embedding"}
        item["score"] = vector_scores[record_index]
        item["vector_score"] = vector_scores[record_index]
        item["bm25_score"] = bm25_scores[record_index]
        item["rrf_score"] = fused_scores.get(record_index, 0.0)
        pages = extract_pdf_pages(item["text"])
        fallback_page = latest_page_by_source.get(item["source"])
        item["citation"] = format_citation(
            item["source"],
            item["text"],
            item["chunk"],
            fallback_page=fallback_page,
        )
        if pages:
            latest_page_by_source[item["source"]] = pages[-1]
        prepared_records.append(item)

    for record_index in fused_ranking[:top_k]:
        scored.append(prepared_records[record_index])
    return scored
