"""Neighbourhood names inside Southampton (Weston, Thornhill, Highfield, ...) with a point for each, from OpenStreetMap.

Wards are the app's areas, but people name neighbourhoods ("open a café in Weston"). This lets the assistant and the
simulator find the place someone means. Output: frontend/public/data/neighbourhoods.json
    [{"name": "Weston", "lat": .., "lon": .., "ward": "Woolston"}, ...]
The ward is the nearest output area's ward (from city.json). Data: (c) OpenStreetMap contributors, ODbL.

    python -m pipeline.neighbourhoods
"""

from __future__ import annotations

import json
import math
import sys

import requests

from simulator.paths import FRONTEND

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = """[out:json][timeout:60];
area["boundary"="administrative"]["name"="Southampton"]["admin_level"="6"]->.city;
node(area.city)["place"~"^(suburb|neighbourhood|quarter|village|hamlet)$"]["name"];
out;"""


def nearest_ward(lat: float, lon: float, city: dict) -> str | None:
    oa = city["oa"]
    best, ward = math.inf, None
    for la, lo, w in zip(oa["lat"], oa["lon"], oa["ward"]):
        d = (la - lat) ** 2 + ((lo - lon) * 0.63) ** 2
        if d < best:
            best, ward = d, w
    return ward


def main() -> None:
    if "--help" in sys.argv:
        print(__doc__)
        return
    data_dir = FRONTEND / "public" / "data"
    city = json.loads((data_dir / "city.json").read_text(encoding="utf-8"))
    reply = requests.post(OVERPASS, data={"data": QUERY}, timeout=90, headers={"User-Agent": "sotonship2026/1.0"})
    reply.raise_for_status()
    seen, out = set(), []
    for el in reply.json()["elements"]:
        name = el["tags"]["name"].strip()
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"name": name, "lat": round(el["lat"], 5), "lon": round(el["lon"], 5), "ward": nearest_ward(el["lat"], el["lon"], city)})
    out.sort(key=lambda p: p["name"])
    (data_dir / "neighbourhoods.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} neighbourhoods -> {data_dir / 'neighbourhoods.json'}")


if __name__ == "__main__":
    main()
