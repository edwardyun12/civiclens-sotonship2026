"""Command-line interface for indexing and querying."""

from __future__ import annotations

import argparse
import sys

from rag.generator import answer
from rag.indexer import build_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Southampton RAG assistant (Groq or local Ollama)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("index", help="Index documents in data/raw")
    query_parser = subparsers.add_parser("query", help="Ask a question")
    query_parser.add_argument("question")
    query_parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    try:
        if args.command == "index":
            build_index()
        else:
            answer(args.question, args.top_k)
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
