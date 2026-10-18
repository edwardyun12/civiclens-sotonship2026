"""The Gemini client builds the right requests and reads replies, streams and embeddings (no network needed)."""
import io
import json

from rag import gemini as G


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def capture(monkeypatch, body: bytes):
    sent = {}

    def urlopen(req, timeout):
        sent["url"], sent["payload"], sent["key"] = req.full_url, json.loads(req.data), req.get_header("X-goog-api-key")
        return FakeResponse(body)

    monkeypatch.setattr(G, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(G.urllib.request, "urlopen", urlopen)
    return sent


def test_complete_json_skips_thoughts(monkeypatch):
    reply = {"candidates": [{"content": {"parts": [{"text": "hmm", "thought": True}, {"text": '{"a": 1}'}]}}]}
    sent = capture(monkeypatch, json.dumps(reply).encode())
    assert G.complete("hi", 100, 0, json_mode=True) == '{"a": 1}'
    assert sent["url"].endswith(f"models/{G.GEMINI_CHAT_MODEL}:generateContent") and sent["key"] == "test-key"
    assert sent["payload"]["generationConfig"]["responseMimeType"] == "application/json"


def test_stream_reads_server_sent_events(monkeypatch):
    events = [{"candidates": [{"content": {"parts": [{"text": t}]}}]} for t in ("Hello ", "world")]
    capture(monkeypatch, "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode())
    assert "".join(G.stream("hi", 100)) == "Hello world"


def test_embed_batches_and_task(monkeypatch):
    sent = capture(monkeypatch, json.dumps({"embeddings": [{"values": [1.0, 0.0]}]}).encode())
    assert G.embed(["a"], "RETRIEVAL_QUERY") == [[1.0, 0.0]]
    assert sent["payload"]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(G, "GEMINI_API_KEY", "")
    try:
        G.complete("hi", 10)
    except RuntimeError as exc:
        assert "GEMINI_API_KEY" in str(exc)
        return
    raise AssertionError("expected RuntimeError")
