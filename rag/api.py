"""HTTP API for the Southampton Opportunity Engine frontend."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rag.classify import classify_business
from rag.config import CHAT_MODEL, CORS_ORIGINS, FRONTEND_DIST, LLM_PROVIDER
from rag.generator import prepare_answer, stream_generated_answer
from rag.routing import direct_response


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)
    history: list[ChatMessage] = Field(default_factory=list)
    top_k: int = Field(default=3, ge=1, le=5)
    # what the user is looking at in the app (page, business, site, scores), computed by the app's own model
    context: str | None = Field(default=None, max_length=4_000)


class BusinessType(BaseModel):
    label: str = Field(max_length=120)
    cat: str = ""
    grp: str = ""
    n: int = 0


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=2, max_length=200)
    types: list[BusinessType] = Field(default_factory=list, max_length=400)
    sectors: list[str] = Field(default_factory=list, max_length=30)


app = FastAPI(title="Southampton Opportunity Engine API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "provider": LLM_PROVIDER, "model": CHAT_MODEL}


@app.post("/api/classify")
def classify(payload: ClassifyRequest) -> dict:
    """Business simulator: let the LLM classify a business idea into sector, niche and competitor types."""
    try:
        return {"ok": True, **classify_business(payload.text, [t.model_dump() for t in payload.types], payload.sectors)}
    except Exception as exc:  # the page falls back to its own matching
        return {"ok": False, "error": str(exc)}


@app.post("/api/chat")
def chat(payload: ChatRequest) -> StreamingResponse:
    history = [message.model_dump() for message in payload.history[-4:]]

    def events() -> Iterator[str]:
        direct = direct_response(payload.question)
        if direct is not None:
            yield json.dumps({"type": "sources", "sources": []}) + "\n"
            yield json.dumps({"type": "token", "content": direct}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
            return

        try:
            sources, prompt = prepare_answer(
                payload.question,
                top_k=payload.top_k,
                conversation_history=history,
                app_context=payload.context,
            )
            public_sources = [
                {
                    "citation": source["citation"],
                    "source": source["source"],
                    "chunk": source["chunk"],
                    "preview": source["text"][:360],
                    "vectorScore": source["vector_score"],
                    "bm25Score": source["bm25_score"],
                    "hybridScore": source["rrf_score"],
                }
                for source in sources
            ]
            yield json.dumps({"type": "sources", "sources": public_sources}) + "\n"
            for token in stream_generated_answer(prompt):
                yield json.dumps({"type": "token", "content": token}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


# the built React app (npm run build -> frontend/dist), so one server hosts the whole website (Render)
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


def main() -> None:
    # Render sets PORT and needs 0.0.0.0; locally it stays on 127.0.0.1:8000
    port = os.getenv("PORT")
    host = "0.0.0.0" if port else "127.0.0.1"
    uvicorn.run("rag.api:app", host=host, port=int(port or 8000), reload=False)


if __name__ == "__main__":
    main()
