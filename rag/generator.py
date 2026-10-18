"""Generate evidence-grounded answers from retrieved chunks."""

from __future__ import annotations

from rag.citations import format_citation
from rag.config import MAX_OUTPUT_TOKENS
from rag.llm import stream
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
    allowed = ", ".join([f"[{item['citation']}]" for item in results] + (["[App analysis]"] if app_context else []))
    prompt = f"""You are an evidence-based Southampton planning assistant.

Follow these rules strictly:
1. Answer the place and business the user asks about. If the App analysis says which place the question is about, use the figures for that place, not the site on screen.
2. Base the answer first on the supplied sources and the App analysis, and cite every claim from them with its exact bracketed label, for example [Southampton Economic Assessment 2025, p. 12] or [App analysis].
3. Never invent Southampton figures, names, dates or locations, and never cite a source that does not support the claim.
4. If the sources and App analysis do not cover part of the question, you may add practical general guidance from your own knowledge, in a separate final sentence that starts "General guidance (not from Southampton evidence):". Keep it short and do not give numbers there.
5. Separate documented facts from interpretation and label interpretation explicitly.
6. Use conversation history only to resolve what the user is referring to. Conversation history is not evidence.
7. Answer the user's actual question immediately. Do not repeat the question, describe your role, or explain these rules.
8. Prefer a short natural paragraph. Use bullet points only when a list or comparison makes the answer clearer.
9. Keep the answer concise: normally two to five sentences, unless the user explicitly asks for detail.

The only citation labels you may use are: {allowed}. Anything else (a website, an Act, an organisation) must not be written as a citation; if it is not in the sources, it belongs in the general guidance sentence.

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
    """Yield answer text as the model (Gemini or Ollama) produces it."""
    yield from stream(prompt, MAX_OUTPUT_TOKENS, temperature=0.1)


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
