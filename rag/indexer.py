"""Build the local vector index from source documents."""

from __future__ import annotations

import json

from rag.config import EMBED_MODEL, INDEX_FILE, PROJECT_ROOT, RAW_DATA_DIR, USE_EMBEDDINGS
from rag.documents import SUPPORTED_SUFFIXES, chunk_text, read_document
from rag.embeddings import embed


def build_index() -> None:
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(
        path
        for path in RAW_DATA_DIR.rglob("*")
        if path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not paths:
        raise RuntimeError(f"Add .txt, .md, or .pdf documents to {RAW_DATA_DIR}.")

    records = []
    for path in paths:
        for number, chunk in enumerate(chunk_text(read_document(path)), start=1):
            records.append(
                {
                    "source": str(path.relative_to(PROJECT_ROOT)),
                    "chunk": number,
                    "text": chunk,
                }
            )

    if USE_EMBEDDINGS:  # keyword-only search (Groq) needs no vectors
        vectors = embed([record["text"] for record in records])
        for record, vector in zip(records, vectors, strict=True):
            record["embedding"] = vector

    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps({"embedding_model": EMBED_MODEL, "records": records}),
        encoding="utf-8",
    )
    print(f"Indexed {len(records)} chunks from {len(paths)} documents -> {INDEX_FILE}")
