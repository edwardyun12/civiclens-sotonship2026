# Southampton Opportunity Engine

## Project Objective
Module A — Business ecosystem intelligence
Analyse which industries are growing or shrinking, where businesses cluster, how business births and deaths change, and where commercial activity appears concentrated.
Output: sector trends, commercial hotspots and neighbourhood comparisons.




Module B — Business gap and opportunity detector
Compare existing business categories with population needs, local demographics, transport access, vacancies and nearby competition.
Output: potential underserved services and business types worth investigating.




Module C — Urban planning scenario simulator
Let a planner explore what might happen if a vacant unit became a café, affordable workspace, childcare centre or health service, and compare possible outcomes.
Output: scenario comparisons for accessibility, service coverage, commercial diversity and potential jobs.




Module D — AI planning analyst
A user asks questions in ordinary language. The AI retrieves supporting statistics and planning documents, explains its analysis and recommends options with source links and uncertainty.
Output: a decision brief, evidence trail and recommendations for human review.

## Repository structure

```text
.
├── data/
│   ├── raw/
│   │   ├── official/       # Council and public-sector source documents
│   │   └── project/        # Internal project material
│   └── processed/          # Generated indexes; excluded from Git
├── src/sotonship_rag/
│   ├── cli.py              # Command-line entry point
│   ├── config.py           # Models, Ollama URL, and paths
│   ├── documents.py        # PDF/text loading and chunking
│   ├── embeddings.py       # Embeddings and vector similarity
│   ├── generator.py        # Grounded answer generation
│   ├── indexer.py          # Document indexing pipeline
│   ├── ollama.py           # Local Ollama client
│   ├── retriever.py        # Relevant-chunk retrieval
│   └── web.py              # Streamlit chat interface
├── tests/                  # Automated tests
├── pyproject.toml          # Package metadata and CLI definition
└── requirements.txt        # Runtime dependencies
```

## Local RAG setup

The first prototype uses Ollama locally. `qwen3:8b` generates answers and
`nomic-embed-text` creates retrieval embeddings.

```bash
# Create the project environment once
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

# Terminal 1
ollama serve

# Run once
ollama pull nomic-embed-text

# Terminal 2
sotonship-rag index
sotonship-rag query "What safeguards should recommendations include?"
```

Add UTF-8 `.txt`, `.md`, or text-based `.pdf` source files under the appropriate
`data/raw/` subdirectory, then rebuild the index. Generated indexes stay under
`data/processed/` and are intentionally excluded from Git.

Alternative module invocation:

```bash
python -m sotonship_rag index
python -m sotonship_rag query "What are Southampton's economic priorities?"
```

## Streamlit interface

With Ollama running, start the local web interface:

```bash
streamlit run src/sotonship_rag/web.py
```

Then open `http://localhost:8501`. The sidebar shows the active local models,
index size, retrieval depth, and controls for rebuilding the document index.

## Tests

```bash
python -m unittest discover -v
```

The current suite covers document chunking and vector similarity.
