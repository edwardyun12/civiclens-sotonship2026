# Instructions for Claude working in this repo

Read `HANDOVER.md` first: it has the deadline, status, files and the to-do list.

## Git rules (required)
- Commit as `TYK3 <atyk0702@outlook.com>`: `git config user.name "TYK3"` and `git config user.email "atyk0702@outlook.com"`.
- No `Co-Authored-By: Claude`, no `Claude-Session:` link, no "Generated with Claude" footer in commits or PRs.
- Work and push only on `feature/simulator`. Never push to `main` unless the user asks. No force-push.

## Project map
- `src/engine.py` deterministic engine (no AI). `src/brief.py` AI brief + numbers audit. `src/app.py` Streamlit app.
- `src/build_places.py` builds the places database (`data/db/`) and the simulator's site list
  (`data/processed/facilities_places.csv`). `SIM_DATASET=baseline` uses the 17 Oct file instead.
- Docs: `docs/SIMULATOR.md` (method, results, limits), `docs/DATA_PLAN.md` (sources, flags), `docs/SUBMISSION.md`.

## Commands (Windows, in the repo folder)
```bat
.venv\Scripts\activate
pytest -q
python -m tests.run_evaluation
python -m src.build_places --ch-key KEY --fsa-file FHRS877en-GB.xml
streamlit run src/app.py
```

User preference: short, practical answers.
