"""Minimal client for the local Ollama HTTP API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from rag.config import OLLAMA_URL


def request(path: str, payload: dict) -> dict:
    http_request = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=300) as response:
            return json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Could not connect to Ollama. Run `ollama serve` in another terminal."
        ) from exc


def stream(path: str, payload: dict):
    """Yield decoded events from an Ollama newline-delimited JSON response."""
    http_request = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=json.dumps({**payload, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=300) as response:
            for line in response:
                if line.strip():
                    yield json.loads(line)
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Could not connect to Ollama. Run `ollama serve` in another terminal."
        ) from exc
