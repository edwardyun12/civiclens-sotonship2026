"""Shared settings for the places database: paths, matching thresholds, the source log, and geometry helpers
(distances, inside-the-city test, ward lookup)."""
from __future__ import annotations

import json
import math
from datetime import datetime
from datetime import timezone

import pandas as pd

from simulator.paths import DB, DB_RAW as RAW, PROC, ROOT  # noqa: F401  re-exported for the other modules


UA = {"User-Agent": "SotonShip2026-planning-simulator/0.2 (hackathon; open data)"}
LA_NAME = "Southampton"
TODAY = datetime.now(timezone.utc).date()

# Matching thresholds (metres / 0-1 name similarity). Design choices; see docs/DATA_PLAN.md.
MATCH_NEAR_M, MATCH_NEAR_SIM = 100, 0.55      # close together and similar names
MATCH_FAR_M, MATCH_FAR_SIM = 300, 0.85        # further apart but almost the same name
SPREAD_FLAG_M = 75                            # sources disagree on location by more than this
POSTCODE_FLAG_M = 250                         # coordinates far from their own postcode centre
GOOGLE_FLAG_M = 50
STALE_OSM_YEARS, STALE_FSA_YEARS = 3, 4

SOURCES: dict[str, dict] = {}


def note(key, title, url, licence, rows):
    SOURCES[key] = {"title": title, "url": url, "licence": licence,
                    "downloaded": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "rows": int(rows)}


def metres(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(a))


def load_city():
    """City outline from the LSOA boundaries already in the repo. Returns (rings, bbox)."""
    gj = json.loads((PROC / "lsoa.geojson").read_text())
    rings = []
    for f in gj["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for p in polys:
            rings.append(p)  # list of rings (outer + holes)
    xs = [x for p in rings for r in p for x, _ in r]
    ys = [y for p in rings for r in p for _, y in r]
    return rings, (min(ys), min(xs), max(ys), max(xs))


def _in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_city(lat, lon, polys) -> bool:
    for p in polys:
        if _in_ring(lon, lat, p[0]) and not any(_in_ring(lon, lat, h) for h in p[1:]):
            return True
    return False


_OA = None


def ward_of(lat, lon) -> str:
    """Ward of the nearest Census Output Area centre (for the area view)."""
    global _OA
    if _OA is None:
        o = pd.read_csv(PROC / "oa.csv")
        _OA = (o["lat"].to_numpy(), o["lon"].to_numpy(), o["ward"].to_numpy())
    if pd.isna(lat):
        return ""
    la, lo, w = _OA
    d = (la - lat) ** 2 + ((lo - lon) * 0.63) ** 2
    return str(w[int(d.argmin())])
