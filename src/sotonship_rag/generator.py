"""Generate evidence-grounded answers from retrieved chunks."""

from __future__ import annotations

from sotonship_rag.config import CHAT_MODEL
from sotonship_rag.ollama import request
from sotonship_rag.retriever import retrieve


def generate_answer(question: str, top_k: int = 5) -> dict:
    """Return a grounded answer and the retrieved evidence used to create it."""
    results = retrieve(question, top_k)
    context = "\n\n".join(
        f"[Source {i}: {item['source']} / chunk {item['chunk']}]\n{item['text']}"
        for i, item in enumerate(results, start=1)
    )
    prompt = f"""You are an evidence-based Southampton planning assistant.
Answer only from the supplied sources. If the evidence is insufficient, say so.
Separate documented facts from your inference. Cite sources using [Source N].

Question: {question}

Sources:
{context}
"""
    response = request(
        "/api/chat",
        {
            "model": CHAT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.1},
        },
    )
    return {
        "answer": response["message"]["content"],
        "sources": results,
    }


def answer(question: str, top_k: int = 5) -> None:
    result = generate_answer(question, top_k)
    print(result["answer"])
    print("\nRetrieved evidence:")
    for i, item in enumerate(result["sources"], start=1):
        print(f"  {i}. {item['source']} chunk {item['chunk']} (score={item['score']:.3f})")
