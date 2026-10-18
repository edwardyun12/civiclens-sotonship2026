"""Minimal client for the Groq chat API (OpenAI-compatible), used when LLM_PROVIDER=groq, e.g. on Render.

Groq has no embeddings API, so with this provider document search is keyword-only (BM25; see rag/llm.py).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from rag.config import GROQ_API_KEY, GROQ_CHAT_MODEL, GROQ_REASONING_EFFORT, GROQ_URL

THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _open(payload: dict):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set on the server.")
    req = urllib.request.Request(
        f"{GROQ_URL}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {GROQ_API_KEY}"},
    )
    try:
        return urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        if exc.code == 429:
            raise RuntimeError("The free Groq API limit was reached; please try again in a minute.") from exc
        raise RuntimeError(f"Groq API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not reach the Groq API.") from exc


def _reasoning_options() -> dict:
    """Keep the model's reasoning out of the answer. GPT-OSS and Qwen take different parameters."""
    if "gpt-oss" in GROQ_CHAT_MODEL:
        return {"include_reasoning": False, "reasoning_effort": GROQ_REASONING_EFFORT or "low"}
    if "qwen" in GROQ_CHAT_MODEL:
        return {"reasoning_format": "hidden", "reasoning_effort": GROQ_REASONING_EFFORT or "none"}
    return {}


def _body(prompt: str, max_tokens: int, temperature: float, json_mode: bool, stream: bool) -> dict:
    body: dict = {
        "model": GROQ_CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
        "stream": stream,
        **_reasoning_options(),
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def complete(prompt: str, max_tokens: int, temperature: float = 0.1, json_mode: bool = False) -> str:
    with _open(_body(prompt, max_tokens, temperature, json_mode, False)) as r:
        reply = json.load(r)
    content = (reply.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return THINK_BLOCK.sub("", content)


def stream(prompt: str, max_tokens: int, temperature: float = 0.1):
    """Yield text pieces from a server-sent-events stream."""
    with _open(_body(prompt, max_tokens, temperature, False, True)) as r:
        for raw in r:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            piece = (json.loads(data).get("choices") or [{}])[0].get("delta", {}).get("content")
            if piece:
                yield piece
