"""Streamlit interface for the Southampton Opportunity Engine."""

from __future__ import annotations

import json
import time

import streamlit as st

from sotonship_rag.citations import linkify_citations
from sotonship_rag.config import CHAT_MODEL, EMBED_MODEL, INDEX_FILE, PROJECT_ROOT
from sotonship_rag.generator import prepare_answer, stream_generated_answer
from sotonship_rag.indexer import build_index
from sotonship_rag.routing import direct_response
from sotonship_rag.visualization import render_evidence_universe


st.set_page_config(
    page_title="Southampton Opportunity Engine",
    page_icon="S",
    layout="wide",
)

st.markdown(
    """
    <style>
        .block-container {max-width: 1050px; padding-top: 2rem;}
        [data-testid="stSidebar"] {border-right: 1px solid #e5e7eb;}
        .source-meta {color: #64748b; font-size: 0.85rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def index_summary() -> tuple[int, int]:
    if not INDEX_FILE.exists():
        return 0, 0
    payload = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    records = [
        record
        for record in payload.get("records", [])
        if (PROJECT_ROOT / record["source"]).is_file()
    ]
    return len({record["source"] for record in records}), len(records)


def render_sources(sources: list[dict], anchor_prefix: str) -> None:
    """Render link targets and expandable evidence cards."""
    st.caption("Evidence used")
    for number, source in enumerate(sources, start=1):
        st.markdown(
            f'<div id="{anchor_prefix}-source-{number}"></div>',
            unsafe_allow_html=True,
        )
        with st.expander(source["citation"]):
            st.markdown(
                f"`{source['source']}`  \n"
                f"Vector: `{source['vector_score']:.3f}` · "
                f"BM25: `{source['bm25_score']:.3f}` · "
                f"Hybrid: `{source['rrf_score']:.4f}`"
            )
            st.write(source["text"])


with st.sidebar:
    st.header("System")
    st.caption("Runs locally through Ollama")
    st.text(f"Chat: {CHAT_MODEL}")
    st.text(f"Embeddings: {EMBED_MODEL}")

    document_count, chunk_count = index_summary()
    col_a, col_b = st.columns(2)
    col_a.metric("Documents", document_count)
    col_b.metric("Chunks", chunk_count)

    top_k = st.slider("Evidence chunks", min_value=1, max_value=10, value=3)

    if st.button("Rebuild document index", use_container_width=True):
        try:
            with st.spinner("Reading and indexing documents..."):
                build_index()
            st.success("Document index rebuilt successfully.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

st.title("Southampton Opportunity Engine")
st.caption("Ask questions about Southampton's economy, planning priorities, and business opportunities.")

if not INDEX_FILE.exists():
    st.warning("No document index was found. Use the sidebar to build the index first.")

if "messages" not in st.session_state:
    st.session_state.messages = []

latest_evidence_index = next(
    (
        index
        for index in range(len(st.session_state.messages) - 1, -1, -1)
        if st.session_state.messages[index].get("sources")
    ),
    None,
)

for message_index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        anchor_prefix = f"message-{message_index}"
        content = message["content"]
        if message.get("sources"):
            content = linkify_citations(content, message["sources"], anchor_prefix)
        st.markdown(content)
        if message.get("sources") and message_index == latest_evidence_index:
            graph_question = message.get("question")
            if not graph_question and message_index > 0:
                previous_message = st.session_state.messages[message_index - 1]
                if previous_message.get("role") == "user":
                    graph_question = previous_message["content"]
            render_evidence_universe(
                graph_question or "Retrieved evidence", message["sources"]
            )
            render_sources(message["sources"], anchor_prefix)

question = st.chat_input("Ask a question in English...")
if question:
    conversation_history = st.session_state.messages[-4:]
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            response = direct_response(question)
            if response is not None:
                st.markdown(response)
                st.session_state.messages.append(
                    {"role": "assistant", "content": response}
                )
            else:
                with st.spinner("Searching the evidence..."):
                    sources, prompt = prepare_answer(
                        question,
                        top_k=top_k,
                        conversation_history=conversation_history,
                    )
                anchor_prefix = f"message-{len(st.session_state.messages)}"
                answer_placeholder = st.empty()
                answer_parts = []
                last_render = 0.0
                for part in stream_generated_answer(prompt):
                    answer_parts.append(part)
                    now = time.monotonic()
                    if now - last_render >= 0.04:
                        answer_placeholder.markdown("".join(answer_parts) + " ▌")
                        last_render = now
                answer = "".join(answer_parts)
                answer_placeholder.markdown(
                    linkify_citations(answer, sources, anchor_prefix)
                )
                render_evidence_universe(question, sources)
                render_sources(sources, anchor_prefix)
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "sources": sources,
                        "question": question,
                    }
                )
        except Exception as exc:
            st.error(str(exc))
