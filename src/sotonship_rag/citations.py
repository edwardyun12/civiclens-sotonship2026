"""Human-readable citation labels for retrieved evidence."""

from __future__ import annotations

import re
from pathlib import Path


PDF_PAGE_PATTERN = re.compile(r"\[PDF page (\d+)\]", re.IGNORECASE)


def document_title(source: str) -> str:
    """Convert a source filename into a readable document title."""
    return Path(source).stem.replace("_", " ").replace("-", " ").title()


def extract_pdf_pages(text: str) -> list[int]:
    """Return unique PDF page markers in their numeric order."""
    return sorted({int(page) for page in PDF_PAGE_PATTERN.findall(text)})


def format_citation(
    source: str,
    text: str,
    chunk: int,
    fallback_page: int | None = None,
) -> str:
    """Build a citation from the filename and page markers in a chunk."""
    title = document_title(source)
    pages = extract_pdf_pages(text)
    if not pages and fallback_page is not None:
        pages = [fallback_page]
    if not pages:
        return f"{title}, section {chunk}"
    if len(pages) == 1:
        return f"{title}, p. {pages[0]}"
    if pages == list(range(pages[0], pages[-1] + 1)):
        return f"{title}, pp. {pages[0]}–{pages[-1]}"
    return f"{title}, pp. {', '.join(str(page) for page in pages)}"


def linkify_citations(answer: str, sources: list[dict], anchor_prefix: str) -> str:
    """Convert generated citation labels into links to rendered evidence cards."""
    linked = answer
    seen: set[str] = set()
    for number, source in enumerate(sources, start=1):
        citation = source["citation"]
        if citation in seen:
            continue
        seen.add(citation)
        linked = linked.replace(
            f"[{citation}]",
            f"[{citation}](#{anchor_prefix}-source-{number})",
        )
    return linked
