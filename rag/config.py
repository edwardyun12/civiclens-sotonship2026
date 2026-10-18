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

# "groq" (hosted website: Groq free API for chat + Gemini embeddings), "gemini" (Gemini for both) or "ollama" (local).
# Default: groq when GROQ_API_KEY is set, else gemini when GEMINI_API_KEY is set, else ollama.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq" if GROQ_API_KEY else "gemini" if GEMINI_API_KEY else "ollama").lower()

GROQ_URL = os.getenv("GROQ_URL", "https://api.groq.com/openai/v1")
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "qwen/qwen3.8-27b")
# Qwen: none / low / medium / high ("none" = answer directly); GPT-OSS: low / medium / high. Empty = model default here.
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:8b")

GEMINI_URL = os.getenv("GEMINI_URL", "https://generativelanguage.googleapis.com/v1beta")
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.8-flash")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_EMBED_DIM = int(os.getenv("GEMINI_EMBED_DIM", "768"))
# Gemini 3 models take "low" / "medium" / "high"; set to "" for models without thinking levels (e.g. 2.5)
GEMINI_THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low")

CHAT_MODEL = {"groq": GROQ_CHAT_MODEL, "gemini": GEMINI_CHAT_MODEL}.get(LLM_PROVIDER, OLLAMA_CHAT_MODEL)
# Groq has no embeddings API, so the groq provider searches documents with Gemini embeddings
EMBED_MODEL = GEMINI_EMBED_MODEL if LLM_PROVIDER in ("gemini", "groq") else OLLAMA_EMBED_MODEL
# Gemini counts thinking tokens in the output limit, so it gets more room. Groq's free plan counts the requested
# limit against 8,000 tokens a minute, so it gets a tight one; the prompt keeps answers short anyway.
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", os.getenv("OLLAMA_MAX_OUTPUT_TOKENS",
                                                                {"gemini": "1500", "groq": "500"}.get(LLM_PROVIDER, "220"))))

# extra browser origins allowed to call the API (comma-separated); the deployed site is same-origin and needs none
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"] + [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]
