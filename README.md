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
│   ├── processed/          # Simulator input data (committed); RAG index.json (excluded from Git)
│   └── db/                 # Places database (simulator)
├── src/engine.py, brief.py, app.py, build_places.py, fetch_data.py   # Module C simulator
├── viewer/                 # Simulator and places register browser pages
├── docs/                   # Simulator method, data plan, codebase guide
├── src/sotonship_rag/
│   ├── api.py              # FastAPI bridge for the React experience
│   ├── cli.py              # Command-line entry point
│   ├── config.py           # Models, Ollama URL, and paths
│   ├── documents.py        # PDF/text loading and chunking
│   ├── embeddings.py       # Embeddings and vector similarity
│   ├── generator.py        # Grounded answer generation
│   ├── indexer.py          # Document indexing pipeline
│   ├── ollama.py           # Local Ollama client
│   ├── retriever.py        # Relevant-chunk retrieval
│   └── web.py              # Streamlit chat interface
├── src/front-end/           # Vite + React opportunity dashboard
├── tests/                  # Automated tests
├── pyproject.toml          # Package metadata and CLI definition
└── requirements.txt        # Runtime dependencies
```

## Module C: planning scenario simulator

Where should the next nursery, GP, pharmacy, café or library go in Southampton, and who benefits?
Setup, data sources and licences, what the AI does, test results and known limits are in
[docs/SIMULATOR.md](docs/SIMULATOR.md); every file is explained in [docs/CODEBASE.md](docs/CODEBASE.md).

```bash
pip install -r requirements.txt
streamlit run src/app.py
```

Browser pages, no install needed: open `viewer/site_simulator.html` or `viewer/places_register.html`.

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
`data/raw/` subdirectory, then rebuild the index. The generated index
(`data/processed/index.json`) is intentionally excluded from Git.

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

## React dashboard

Run the local RAG API and React application in separate terminals after Ollama
is available:

```bash
# Terminal 2 — from the repository root
source .venv/bin/activate
sotonship-api

# Terminal 3
cd src/front-end
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development server proxies `/api`
requests to the local FastAPI service at `http://127.0.0.1:8000`.
