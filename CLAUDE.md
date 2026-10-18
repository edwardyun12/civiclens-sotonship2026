# Instructions for Claude working in this repo

Read `docs/CODEBASE.md` first (every file and function, how they connect, rules for changes), then `HANDOVER.md`
(deadline, status, to-do list).

## Git rules (required)
- Commit as `TYK3 <atyk0702@outlook.com>`: `git config user.name "TYK3"` and `git config user.email "atyk0702@outlook.com"`.
- No `Co-Authored-By: Claude`, no `Claude-Session:` link, no "Generated with Claude" footer in commits or PRs.
- Work and push only on `feature/simulator`. Never push to `main` unless the user asks. No force-push.

## Project map
- `run.py` runs everything: `python run.py` lists the commands. `docs/CODEBASE.md` has a "Where to change what" table.
- `simulator/`: `engine.py` deterministic engine (no AI), `brief.py` AI brief + numbers audit, `app.py` Streamlit app,
  `config.py` design choices, `paths.py` every data folder.
- `pipeline/`: `city_data.py` (ONS, Census, IMD, flood, OSM/NHS), `population.py` (ONS mid-2024 residents),
  `places/` (places database → `data/db/` and `data/processed/facilities_places.csv`). `SIM_DATASET=baseline` uses the 17 Oct file and Census 2021 residents.
- `viewer/` browser pages; rebuild with `python run.py viewers`. `viewer/src/engine.js` must stay in step with `simulator/engine.py`.
- `frontend/` React app, `rag/` local RAG assistant (teammate's code), `tests/` pytest, `evaluation/` evidence scripts + results.
- Docs: `docs/CODEBASE.md` (code map), `docs/SIMULATOR.md` (method, results, limits), `docs/DATA_PLAN.md` (sources, flags, names), `docs/SUBMISSION.md`.

## Commands (Windows, in the repo folder)
```bat
.venv\Scripts\activate
python run.py test
python run.py eval
python run.py places --ch-key KEY --fsa-file FHRS877en-GB.xml
python run.py population
python run.py viewers
python run.py app
```

User preference: short, practical answers.
