"""Every folder the project reads or writes, in one place. To move a folder, change it here only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"                # downloaded source files + SOURCES.json (pipeline/city_data.py)
PROC = DATA / "processed"         # clean inputs the simulator reads (oa.csv, facilities*.csv, geojson)
DB = DATA / "db"                  # places database (pipeline/places)
DB_RAW = DB / "raw"               # places downloads (gitignored)
DB_SAMPLE = DB / "sample"         # small committed sample, used when no full database is built
CACHE = DATA / "cache"            # distance matrix, postcode lookups, demo briefs
LOGS = ROOT / "logs"              # AI brief log (briefs.jsonl)
VIEWER = ROOT / "viewer"          # static browser pages and their templates (viewer/src)
EVAL_RESULTS = ROOT / "evaluation" / "results"
# React app. Falls back to the old location until src/front-end is moved (it can't move while `npm run dev` runs).
FRONTEND = ROOT / "frontend" if (ROOT / "frontend").exists() else ROOT / "src" / "front-end"
