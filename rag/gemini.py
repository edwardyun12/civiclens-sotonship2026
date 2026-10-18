"""Minimal client for the Google Gemini REST API (used when LLM_PROVIDER=gemini, e.g. on Render)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from rag.config import GEMINI_API_KEY, GEMINI_CHAT_MODEL, GEMINI_EMBED_DIM, GEMINI_EMBED_MODEL, GEMINI_THINKING_LEVEL, GEMINI_URL

EMBED_BATCH = 100  # batchEmbedContents accepts at most 100 texts per call


def _open(path: str, payload: dict):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set on the server.")
    req = urllib.request.Request(
        f"{GEMINI_URL}/{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
    )
    try:
        return urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Gemini API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach the Gemini API.") from exc


def _body(prompt: str, max_tokens: int, temperature: float, json_mode: bool) -> dict:
    config: dict = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if json_mode:
        config["responseMimeType"] = "application/json"
    if GEMINI_THINKING_LEVEL:
        config["thinkingConfig"] = {"thinkingLevel": GEMINI_THINKING_LEVEL}
    return {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}


def _text(reply: dict) -> str:
    parts = (reply.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def complete(prompt: str, max_tokens: int, temperature: float = 0.1, json_mode: bool = False) -> str:
    with _open(f"models/{GEMINI_CHAT_MODEL}:generateContent", _body(prompt, max_tokens, temperature, json_mode)) as r:
        return _text(json.load(r))


def stream(prompt: str, max_tokens: int, temperature: float = 0.1):
    """Yield text pieces from a server-sent-events stream."""
    with _open(f"models/{GEMINI_CHAT_MODEL}:streamGenerateContent?alt=sse",
               _body(prompt, max_tokens, temperature, False)) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if line.startswith("data:"):
                piece = _text(json.loads(line[5:]))
                if piece:
                    yield piece


def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        requests = [
            {"model": f"models/{GEMINI_EMBED_MODEL}", "content": {"parts": [{"text": t}]},
             "taskType": task, "outputDimensionality": GEMINI_EMBED_DIM}
            for t in texts[i:i + EMBED_BATCH]
        ]
        with _open(f"models/{GEMINI_EMBED_MODEL}:batchEmbedContents", {"requests": requests}) as r:
            vectors += [e["values"] for e in json.load(r)["embeddings"]]
    return vectors
