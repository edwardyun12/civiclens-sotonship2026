"""One interface over the model backends, chosen by LLM_PROVIDER: Groq (hosted website; Gemini embeddings),
Gemini (hosted) or Ollama (local)."""

from __future__ import annotations

from rag import gemini, groq, ollama
from rag.config import LLM_PROVIDER, OLLAMA_CHAT_MODEL, OLLAMA_EMBED_MODEL


def complete(prompt: str, max_tokens: int, temperature: float = 0.1, json_mode: bool = False) -> str:
    if LLM_PROVIDER == "groq":
        return groq.complete(prompt, max_tokens, temperature, json_mode)
    if LLM_PROVIDER == "gemini":
        return gemini.complete(prompt, max_tokens, temperature, json_mode)
    reply = ollama.request("/api/chat", {
        "model": OLLAMA_CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        **({"format": "json"} if json_mode else {}),
        "think": False,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    })
    return reply.get("message", {}).get("content", "")


def stream(prompt: str, max_tokens: int, temperature: float = 0.1):
    if LLM_PROVIDER == "groq":
        yield from groq.stream(prompt, max_tokens, temperature)
        return
    if LLM_PROVIDER == "gemini":
        yield from gemini.stream(prompt, max_tokens, temperature)
        return
    events = ollama.stream("/api/chat", {
        "model": OLLAMA_CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "think": False,
        "options": {"temperature": temperature, "num_predict": max_tokens, "repeat_penalty": 1.1},
    })
    for event in events:
        content = event.get("message", {}).get("content", "")
        if content:
            yield content


def embed(texts: list[str], query: bool = False) -> list[list[float]]:
    if LLM_PROVIDER in ("gemini", "groq"):  # Groq has no embeddings API
        return gemini.embed(texts, "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT")
    return ollama.request("/api/embed", {"model": OLLAMA_EMBED_MODEL, "input": texts})["embeddings"]
