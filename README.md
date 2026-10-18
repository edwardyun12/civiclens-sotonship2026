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
├── run.py                  # One entry point: python run.py app | test | eval | viewers | places | population | rag | api | frontend
├── simulator/              # Module C model (Python)
│   ├── config.py           #   every design choice: categories, radii, weights, jobs
│   ├── engine.py           #   deterministic engine: coverage, scores, optimiser (no AI)
│   ├── brief.py            #   AI brief + numbers audit
│   ├── app.py              #   Streamlit app
│   └── paths.py            #   every data folder, defined once
├── pipeline/               # Builds data/ (run rarely)
│   ├── city_data.py        #   ONS geography, Census 2021, IMD, OSM/NHS sites, flood zones
│   ├── population.py       #   ONS mid-2024 small area population estimates
│   └── places/             #   places database: sources, names, business_types, merge, companies, build
├── rag/                    # Module D local RAG assistant (Ollama)
│   ├── api.py              #   FastAPI bridge for the React experience
│   ├── cli.py              #   command-line entry point
│   ├── config.py           #   models, Ollama URL, and paths
│   ├── documents.py        #   PDF/text loading and chunking
│   ├── embeddings.py       #   embeddings and vector similarity
│   ├── generator.py        #   grounded answer generation
│   ├── indexer.py          #   document indexing pipeline
│   ├── ollama.py           #   local Ollama client
│   ├── retriever.py        #   relevant-chunk retrieval
│   └── web.py              #   Streamlit chat interface
├── frontend/               # Vite + React app (places map with People heat map, simulator, RAG chat)
├── viewer/                 # Self-contained browser pages (simulator, places register) + templates in viewer/src/
├── data/
│   ├── raw/                # Downloaded sources + SOURCES.json; official/ and project/ hold RAG documents
│   ├── processed/          # Simulator input data (committed); RAG index.json (excluded from Git)
│   └── db/                 # Places database
├── tests/                  # pytest tests
├── evaluation/             # Evidence scripts and results/ (baseline comparison, live AI briefs)
├── docs/                   # CODEBASE.md (where to change what), SIMULATOR.md, DATA_PLAN.md, SUBMISSION.md
├── pyproject.toml          # Package metadata and CLI definition
└── requirements.txt        # Runtime dependencies
```

## Module C: planning scenario simulator

Where should the next nursery, GP, pharmacy, café or library go in Southampton, and who benefits?
Setup, data sources and licences, what the AI does, test results and known limits are in
[docs/SIMULATOR.md](docs/SIMULATOR.md); every file is explained in [docs/CODEBASE.md](docs/CODEBASE.md).

```bash
pip install -r requirements.txt
python run.py app
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
python -m rag index
python -m rag query "What are Southampton's economic priorities?"
```

## Streamlit interface

With Ollama running, start the local web interface:

```bash
python run.py rag-web
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
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development server proxies `/api`
requests to the local FastAPI service at `http://127.0.0.1:8000`.
