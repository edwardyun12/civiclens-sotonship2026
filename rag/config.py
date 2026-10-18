"""Application configuration and project paths."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
INDEX_FILE = PROCESSED_DATA_DIR / "index.json"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

# "groq" (hosted website: Groq free API for chat; keyword-only document search, since Groq has no embeddings),
# or "ollama" (local, hybrid keyword + vector search). Default: groq when GROQ_API_KEY is set, else ollama.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq" if GROQ_API_KEY else "ollama").lower()

GROQ_URL = os.getenv("GROQ_URL", "https://api.groq.com/openai/v1")
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "qwen/qwen3.8-27b")
# Qwen: none / low / medium / high ("none" = answer directly); GPT-OSS: low / medium / high. Empty = model default here.
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:8b")

CHAT_MODEL = GROQ_CHAT_MODEL if LLM_PROVIDER == "groq" else OLLAMA_CHAT_MODEL
# Groq has no embeddings API, so with the groq provider document search is keyword-only (BM25): no second AI service
EMBED_MODEL = "bm25-only" if LLM_PROVIDER == "groq" else OLLAMA_EMBED_MODEL
USE_EMBEDDINGS = EMBED_MODEL != "bm25-only"
# Groq's free plan counts the requested
# limit against 8,000 tokens a minute, so it gets a tight one; the prompt keeps answers short anyway.
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", os.getenv("OLLAMA_MAX_OUTPUT_TOKENS",
                                                                "500" if LLM_PROVIDER == "groq" else "220")))

# extra browser origins allowed to call the API (comma-separated); the deployed site is same-origin and needs none
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"] + [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]
