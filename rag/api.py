"""HTTP API for the Southampton Opportunity Engine frontend."""

from __future__ import annotations

import json
from collections.abc import Iterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

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


app = FastAPI(title="Southampton Opportunity Engine API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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


def main() -> None:
    uvicorn.run("rag.api:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
