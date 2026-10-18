"""Generate evidence-grounded answers from retrieved chunks."""

from __future__ import annotations

from rag.citations import format_citation
from rag.config import CHAT_MODEL, MAX_OUTPUT_TOKENS
from rag.ollama import stream
from rag.retriever import retrieve
from rag.routing import direct_response


def build_retrieval_query(question: str, conversation_history: list[dict] | None = None) -> str:
    """Combine the latest question with up to two previous user questions."""
    previous_questions = [
        message["content"]
        for message in (conversation_history or [])
        if (
            message.get("role") == "user"
            and message.get("content")
            and direct_response(message["content"]) is None
        )
    ][-2:]
    if not previous_questions:
        return question

    lines = [f"Previous user question: {item}" for item in previous_questions]
    lines.append(f"Current user question: {question}")
    return "\n".join(lines)


def format_conversation_context(conversation_history: list[dict] | None = None) -> str:
    """Format a short context window without treating it as factual evidence."""
    messages = (conversation_history or [])[-4:]
    if not messages:
        return "No previous conversation."

    return "\n".join(
        f"{message.get('role', 'user').title()}: {message.get('content', '')[:1200]}"
        for message in messages
    )


def prepare_answer(
    question: str,
    top_k: int = 3,
    conversation_history: list[dict] | None = None,
    app_context: str | None = None,
) -> tuple[list[dict], str]:
    """Retrieve evidence and build the grounded generation prompt."""
    retrieval_query = build_retrieval_query(question, conversation_history)
    results = retrieve(retrieval_query, top_k)
    for item in results:
        item.setdefault(
            "citation",
            format_citation(item["source"], item["text"], item["chunk"]),
        )
    context = "\n\n".join(
        f"[{item['citation']}]\n{item['text']}"
        for item in results
    )
    prompt = f"""You are an evidence-based Southampton planning assistant.

Follow these rules strictly:
1. Answer only with information directly supported by the supplied sources or the App analysis below.
2. Do not use prior knowledge, assumptions, or invented details.
3. Do not guess missing names, dates, figures, locations, causes, or conclusions.
4. If the sources do not contain enough evidence, reply: "I don't know based on the available evidence."
5. If only part of the question is supported, answer that part and clearly state what cannot be verified.
6. Separate documented facts from any interpretation and label interpretation explicitly.
7. Cite every factual claim using the source's exact bracketed citation label, for example [Southampton Economic Assessment 2025, p. 12].
8. Never cite a source that does not directly support the claim.
9. Use conversation history only to resolve what the user is referring to. Conversation history is not evidence.
10. Answer the user's actual question immediately. Do not repeat the question, describe your role, or explain these rules.
11. Prefer a short natural paragraph. Use bullet points only when a list or comparison makes the answer clearer.
12. Keep the answer concise: normally two to four sentences, unless the user explicitly asks for detail.

Conversation history:
{format_conversation_context(conversation_history)}

Question: {question}

App analysis (what the user is looking at, computed by the app's own model; cite it as [App analysis]):
{app_context or 'None.'}

Sources:
{context}
"""
    return results, prompt


def stream_generated_answer(prompt: str):
    """Yield answer text as Ollama produces it."""
    events = stream(
        "/api/chat",
        {
            "model": CHAT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "think": False,
            "options": {
                "temperature": 0.1,
                "num_predict": MAX_OUTPUT_TOKENS,
                "repeat_penalty": 1.1,
            },
        },
    )
    for event in events:
        content = event.get("message", {}).get("content", "")
        if content:
            yield content


def generate_answer(
    question: str,
    top_k: int = 3,
    conversation_history: list[dict] | None = None,
) -> dict:
    """Return a complete grounded answer while consuming a streamed response."""
    results, prompt = prepare_answer(question, top_k, conversation_history)
    return {
        "answer": "".join(stream_generated_answer(prompt)),
        "sources": results,
    }


def answer(question: str, top_k: int = 3) -> None:
    result = generate_answer(question, top_k)
    print(result["answer"])
    print("\nRetrieved evidence:")
    for i, item in enumerate(result["sources"], start=1):
        print(
            f"  {i}. {item['citation']} "
            f"(vector={item['vector_score']:.3f}, bm25={item['bm25_score']:.3f}, "
            f"rrf={item['rrf_score']:.4f})"
        )
