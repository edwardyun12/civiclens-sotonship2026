"""The Groq client builds the right requests and reads replies and streams (no network needed)."""
import io
import json

from rag import groq as Q


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def capture(monkeypatch, body: bytes, model: str = "qwen/qwen3.8-27b"):
    sent = {}

    def urlopen(req, timeout):
        sent["url"], sent["payload"], sent["auth"] = req.full_url, json.loads(req.data), req.get_header("Authorization")
        return FakeResponse(body)

    monkeypatch.setattr(Q, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(Q, "GROQ_CHAT_MODEL", model)
    monkeypatch.setattr(Q.urllib.request, "urlopen", urlopen)
    return sent


def test_complete_json_hides_reasoning(monkeypatch):
    reply = {"choices": [{"message": {"content": '<think>hmm</think>{"a": 1}'}}]}
    sent = capture(monkeypatch, json.dumps(reply).encode())
    assert Q.complete("reply in json", 100, 0, json_mode=True) == '{"a": 1}'
    assert sent["url"].endswith("/chat/completions") and sent["auth"] == "Bearer test-key"
    assert sent["payload"]["response_format"] == {"type": "json_object"}
    assert sent["payload"]["reasoning_format"] == "hidden" and "include_reasoning" not in sent["payload"]


def test_gpt_oss_uses_its_own_reasoning_switch(monkeypatch):
    sent = capture(monkeypatch, json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode(), "openai/gpt-oss-120b")
    assert Q.complete("hi", 50) == "ok"
    assert sent["payload"]["include_reasoning"] is False and "reasoning_format" not in sent["payload"]


def test_stream_reads_server_sent_events(monkeypatch):
    chunks = [{"choices": [{"delta": {"content": t}}]} for t in ("Hello ", "world")]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    capture(monkeypatch, body.encode())
    assert "".join(Q.stream("hi", 100)) == "Hello world"


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(Q, "GROQ_API_KEY", "")
    try:
        Q.complete("hi", 10)
    except RuntimeError as exc:
        assert "GROQ_API_KEY" in str(exc)
        return
    raise AssertionError("expected RuntimeError")


def test_groq_provider_never_calls_an_embeddings_service(monkeypatch):
    from rag import llm
    monkeypatch.setattr(llm, "LLM_PROVIDER", "groq")
    try:
        llm.embed(["text"])
    except RuntimeError as exc:
        assert "keyword-only" in str(exc)
        return
    raise AssertionError("expected RuntimeError")
