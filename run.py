"""One entry point for everything in this repo. Run from the repo folder:

    python run.py                      list the commands
    python run.py app                  Streamlit simulator            (simulator/app.py)
    python run.py test                 all tests                      (tests/)
    python run.py eval                 baseline comparison + optimiser (evaluation/run_evaluation.py)
    python run.py viewers              rebuild viewer/*.html + frontend/public/data (viewer/build_viewers.py)
    python run.py places [args]        build the places database       (pipeline/places)
    python run.py population [args]    refresh residents to the latest ONS estimate (pipeline/population.py)
    python run.py city-data [args]     re-download all city data       (pipeline/city_data.py)
    python run.py rag [args]           RAG command line, e.g. `rag index` (rag/cli.py)
    python run.py api                  RAG API for the React app       (rag/api.py)
    python run.py rag-web              RAG Streamlit chat              (rag/web.py)
    python run.py frontend             React app dev server            (frontend/, needs npm)

Extra arguments are passed straight through, e.g. `python run.py places --offline`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

# command -> (what it does, argv to run). "-m" commands run from the repo root so the packages import.
COMMANDS = {
    "app": ("Streamlit simulator", [PY, "-m", "streamlit", "run", "simulator/app.py"]),
    "test": ("Run all tests", [PY, "-m", "pytest", "-q", "tests"]),
    "eval": ("Baseline comparison and optimiser evidence", [PY, "-m", "evaluation.run_evaluation"]),
    "live-briefs": ("10 live AI briefs (needs ANTHROPIC_API_KEY, costs money)", [PY, "-m", "evaluation.run_live_briefs"]),
    "viewers": ("Rebuild the browser pages and React data", [PY, "viewer/build_viewers.py"]),
    "places": ("Build the places database", [PY, "-m", "pipeline.places"]),
    "population": ("Refresh residents to the latest ONS estimate", [PY, "-m", "pipeline.population"]),
    "city-data": ("Re-download all city data", [PY, "-m", "pipeline.city_data"]),
    "rag": ("RAG command line (index / query)", [PY, "-m", "rag"]),
    "api": ("RAG API for the React app", [PY, "-c", "from rag.api import main; main()"]),
    "rag-web": ("RAG Streamlit chat", [PY, "-m", "streamlit", "run", "rag/web.py"]),
}


def frontend_dir() -> Path:
    from simulator.paths import FRONTEND
    return FRONTEND


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, extra = argv[0], argv[1:]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")]))}
    if cmd == "frontend":
        npm = shutil.which("npm")
        if not npm:
            print("npm not found: install Node.js (https://nodejs.org), then run this again.")
            return 1
        d = frontend_dir()
        if not (d / "node_modules").exists():
            subprocess.run([npm, "install"], cwd=d, check=True)
        return subprocess.call([npm, "run", "dev", *extra], cwd=d)
    if cmd not in COMMANDS:
        print(f"Unknown command '{cmd}'. Commands: {', '.join([*COMMANDS, 'frontend'])}")
        return 2
    return subprocess.call([*COMMANDS[cmd][1], *extra], cwd=ROOT, env=env)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main(sys.argv[1:]))
