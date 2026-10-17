"""Rebuild the two browser pages in viewer/ from the templates in viewer/src/ and the current data.

    python viewer/build_viewers.py            # needs: pandas, numpy; node optional (engine check)

Inputs: data/processed/{oa.csv, facilities.csv, facilities_places.csv, lsoa.geojson, flood_zone3.geojson},
        data/db/places.csv + source_records.csv + summary.json (falls back to data/db/sample/).
Outputs: viewer/site_simulator.html, viewer/places_register.html (self-contained, open by double-click).
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.build_places import specialty_of  # noqa: E402

SRC = ROOT / "viewer" / "src"
DB = ROOT / "data" / "db" if (ROOT / "data" / "db" / "places.csv").exists() else ROOT / "data" / "db" / "sample"


def esc(s: str) -> str:
    return s.replace("</", "<\\/")  # safe inside <script> tags


def pack(fac_file: str) -> dict:
    """City data (Output Areas, sites, LSOA shapes, flood shapes) via viewer/src/pack_city.py."""
    out = Path(tempfile.mkdtemp()) / "data.json"
    subprocess.run([sys.executable, str(SRC / "pack_city.py"), str(ROOT), str(out), fac_file], check=True)
    return json.loads(out.read_text(encoding="utf-8"))


def places_slim(places: pd.DataFrame) -> dict:
    p = places[places["lat"].notna()]
    fl = p["flags"].fillna("")
    return {"lat": p["lat"].round(6).tolist(), "lon": p["lon"].round(6).tolist(), "name": p["name"].fillna("").tolist(),
            "cat": p["category"].tolist(), "grp": p["industry_group"].fillna("Other").tolist(),
            "ro": fl.str.contains("REGISTERED_OFFICE_ONLY").astype(int).tolist(),
            "cf": p["customer_facing"].astype(str).str.lower().eq("true").astype(int).tolist(),
            "src": p["sources"].fillna("").tolist(), "conf": p["confidence"].astype(int).tolist(),
            "id": p["place_id"].tolist(), "co": p["company_number"].fillna("").tolist()}


def area_data() -> dict:
    oa = pd.read_csv(ROOT / "data" / "processed" / "oa.csv")
    return {"oa": {"lat": oa.lat.round(6).tolist(), "lon": oa.lon.round(6).tolist(), "pop": oa["pop"].astype(int).tolist(),
                   "ward": oa.ward.tolist(), "q": oa.imd_quintile.astype(int).tolist()},
            "lsoa_ward": oa.groupby("lsoa").ward.agg(lambda s: s.mode().iloc[0]).to_dict(),
            "ward_pop": oa.groupby("ward")["pop"].sum().astype(int).to_dict()}


def main():
    places = pd.read_csv(DB / "places.csv", dtype={"company_number": str})
    places_csv = (DB / "places.csv").read_text(encoding="utf-8")
    if "specialty" not in places:  # builds made before the advanced search: add the labels the same way
        sp = places.apply(specialty_of, axis=1)
        places["specialty"], places["specialty_from"] = sp.str[0], sp.str[1]
        places_csv = places.to_csv(index=False)
    summary = json.loads((DB / "summary.json").read_text(encoding="utf-8"))
    sources = summary.pop("sources", {})
    city_places = pack("facilities_places.csv")
    city_base = pack("facilities.csv")
    engine = (SRC / "engine.js").read_text(encoding="utf-8")

    sim = ((SRC / "site_simulator.template.html").read_text(encoding="utf-8")
           .replace("__DATA__", esc(json.dumps(city_places, separators=(",", ":"))))
           .replace("__BASEFAC__", esc(json.dumps(city_base["fac"], separators=(",", ":"))))
           .replace("__PLACES__", esc(json.dumps(places_slim(places), separators=(",", ":"))))
           .replace("__PSOURCES__", esc(json.dumps(sources)))
           .replace("__ENGINE__", engine))
    (ROOT / "viewer" / "site_simulator.html").write_text(sim, encoding="utf-8", newline="")

    geo = {"lsoa": city_places["lsoa"], "edges": city_places["edges"]}
    reg = ((SRC / "places_register.template.html").read_text(encoding="utf-8")
           .replace("__PLACES__", esc(places_csv))
           .replace("__RECS__", esc((DB / "source_records.csv").read_text(encoding="utf-8")))
           .replace("__GEO__", esc(json.dumps(geo, separators=(",", ":"))))
           .replace("__SUMMARY__", esc(json.dumps(summary)))
           .replace("__AREA__", esc(json.dumps(area_data(), separators=(",", ":")))))
    (ROOT / "viewer" / "places_register.html").write_text(reg, encoding="utf-8", newline="")
    print(f"Built viewer/site_simulator.html ({len(sim):,} bytes) and viewer/places_register.html ({len(reg):,} bytes) from {DB}")

    if shutil.which("node"):  # JS engine must still match the Python engine's saved results
        tmp = Path(tempfile.mkdtemp())
        for f in ("engine.js", "verify_engine.js"):
            shutil.copy(SRC / f, tmp / f)
        (tmp / "data.json").write_text(json.dumps(city_base), encoding="utf-8")
        subprocess.run(["node", str(tmp / "verify_engine.js"), str(ROOT)], check=False)


if __name__ == "__main__":
    main()
