"""Streamlit interface for the Southampton Opportunity Engine."""

from __future__ import annotations

import json

import streamlit as st

from sotonship_rag.config import CHAT_MODEL, EMBED_MODEL, INDEX_FILE
from sotonship_rag.generator import generate_answer
from sotonship_rag.indexer import build_index


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
    records = payload.get("records", [])
    return len({record["source"] for record in records}), len(records)


with st.sidebar:
    st.header("System")
    st.caption("Runs locally through Ollama")
    st.text(f"Chat: {CHAT_MODEL}")
    st.text(f"Embeddings: {EMBED_MODEL}")

    document_count, chunk_count = index_summary()
    col_a, col_b = st.columns(2)
    col_a.metric("Documents", document_count)
    col_b.metric("Chunks", chunk_count)

    top_k = st.slider("Evidence chunks", min_value=1, max_value=10, value=5)

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

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("sources"):
            with st.expander("Evidence used"):
                for number, source in enumerate(message["sources"], start=1):
                    st.markdown(
                        f"**Source {number}: `{source['source']}` — chunk {source['chunk']}**  "
                        f"\nSimilarity: `{source['score']:.3f}`"
                    )
                    st.write(source["text"])
                    if number < len(message["sources"]):
                        st.divider()

question = st.chat_input("Ask a question in English...")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Searching the evidence and generating an answer..."):
                result = generate_answer(question, top_k=top_k)
            st.markdown(result["answer"])
            with st.expander("Evidence used"):
                for number, source in enumerate(result["sources"], start=1):
                    st.markdown(
                        f"**Source {number}: `{source['source']}` — chunk {source['chunk']}**  "
                        f"\nSimilarity: `{source['score']:.3f}`"
                    )
                    st.write(source["text"])
                    if number < len(result["sources"]):
                        st.divider()
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": result["answer"],
                    "sources": result["sources"],
                }
            )
        except Exception as exc:
            st.error(str(exc))
