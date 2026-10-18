"""Document loading and chunking utilities."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader


SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}


def read_document(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        pages = []
        for page_number, page in enumerate(PdfReader(path).pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"[PDF page {page_number}]\n{text}")
        if not pages:
            raise ValueError(f"Could not extract text from PDF: {path.name}")
        return "\n\n".join(pages)

    if path.suffix.lower() not in {".txt", ".md"}:
        raise ValueError(f"Unsupported file type: {path.name}")
    return path.read_text(encoding="utf-8", errors="replace")


def chunk_text(text: str, max_chars: int = 1800, overlap: int = 250) -> list[str]:
    """Split text on paragraphs while retaining a small context overlap."""
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", text)]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = current[-overlap:] + "\n\n" + paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()

    if current:
        chunks.append(current)
    return chunks
