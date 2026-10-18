"""Application configuration and project paths."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
INDEX_FILE = PROCESSED_DATA_DIR / "index.json"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

# "gemini" (hosted, needs GEMINI_API_KEY; used on Render) or "ollama" (local). Default: gemini when a key is set.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini" if GEMINI_API_KEY else "ollama").lower()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:8b")

GEMINI_URL = os.getenv("GEMINI_URL", "https://generativelanguage.googleapis.com/v1beta")
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_EMBED_DIM = int(os.getenv("GEMINI_EMBED_DIM", "768"))
# Gemini 3 models take "low" / "medium" / "high"; set to "" for models without thinking levels (e.g. 2.5)
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low")

CHAT_MODEL = GEMINI_CHAT_MODEL if LLM_PROVIDER == "gemini" else OLLAMA_CHAT_MODEL
EMBED_MODEL = GEMINI_EMBED_MODEL if LLM_PROVIDER == "gemini" else OLLAMA_EMBED_MODEL
# Gemini counts thinking tokens in the output limit, so it gets more room; the prompt keeps answers short
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", os.getenv("OLLAMA_MAX_OUTPUT_TOKENS",
                                                                "1500" if LLM_PROVIDER == "gemini" else "220")))

# extra browser origins allowed to call the API (comma-separated); the deployed site is same-origin and needs none
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"] + [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]
