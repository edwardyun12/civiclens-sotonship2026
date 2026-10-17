"""Pack the simulator's processed data into one compact JSON for the browser playground."""
import json, sys
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
P = REPO / "data" / "processed"

oa = pd.read_csv(P / "oa.csv")
fac = pd.read_csv(P / (sys.argv[3] if len(sys.argv) > 3 else "facilities.csv"))


def dp(pts, tol):
    """Douglas-Peucker on a list of [x,y]."""
    if len(pts) < 4:
        return pts
    a = np.asarray(pts, float)
    keep = np.zeros(len(a), bool); keep[0] = keep[-1] = True
    stack = [(0, len(a) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        p, q = a[i], a[j]
        seg = a[i + 1:j]
        d = q - p
        L = np.hypot(*d)
        if L == 0:
            dist = np.hypot(*(seg - p).T)
        else:
            dist = np.abs(d[0] * (seg[:, 1] - p[1]) - d[1] * (seg[:, 0] - p[0])) / L
        k = int(np.argmax(dist))
        if dist[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return a[keep].round(5).tolist()


def polys(geom):
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def pip_many(x, y, rings):
    """Even-odd point in polygon for arrays x,y against a list of rings (holes included)."""
    inside = np.zeros(len(x), bool)
    for r in rings:
        r = np.asarray(r, float)
        x1, y1 = r[:-1, 0], r[:-1, 1]
        x2, y2 = r[1:, 0], r[1:, 1]
        for k in range(len(x1)):
            c = ((y1[k] > y) != (y2[k] > y))
            if not c.any():
                continue
            xi = x1[k] + (y - y1[k]) * (x2[k] - x1[k]) / ((y2[k] - y1[k]) or 1e-300)
            inside ^= c & (x < xi)
    return inside


# LSOA polygons: drawing + inside-city check; boundary = edges used by exactly one LSOA
lsoa = json.loads((P / "lsoa.geojson").read_text())
segs = Counter()
lsoa_out = []
for f in lsoa["features"]:
    rings_out = []
    for poly in polys(f["geometry"]):
        for ring in poly:
            rr = [(round(x, 6), round(y, 6)) for x, y in ring]
            for a, b in zip(rr[:-1], rr[1:]):
                if a != b:
                    segs[tuple(sorted((a, b)))] += 1
            rings_out.append(dp(ring, 0.00004))
    lsoa_out.append({"code": f["properties"]["LSOA21CD"], "name": f["properties"]["LSOA21NM"], "rings": rings_out})
edge = [s for s, n in segs.items() if n == 1]
# simplify boundary edges by chaining is overkill; thin them to every segment longer than ~0 and round
edge_out = [[round(a[0], 5), round(a[1], 5), round(b[0], 5), round(b[1], 5)] for a, b in edge]

# Flood Zone 3: full-res flag per OA (as the Python engine does), simplified shapes for drawing / click checks
fl = json.loads((P / "flood_zone3.geojson").read_text())
rings_full = []
flood_out = []
for f in fl["features"]:
    for poly in polys(f["geometry"]):
        rings_full += poly
        flood_out.append([dp(r, 0.0001) for r in poly])
oa_flood = pip_many(oa.lon.to_numpy(), oa.lat.to_numpy(), rings_full)

data = {
    "oa": {
        "code": oa.oa_code.tolist(), "ward": oa.ward.tolist(),
        "lat": oa.lat.round(6).tolist(), "lon": oa.lon.round(6).tolist(),
        "pop": oa["pop"].astype(int).tolist(), "pop04": oa.pop_0_4.astype(int).tolist(),
        "q": oa.imd_quintile.astype(int).tolist(), "flood": oa_flood.astype(int).tolist(),
    },
    "fac": [{"c": r.category, "n": (r["name"] if isinstance(r["name"], str) else ""), "lat": round(r.lat, 6),
             "lon": round(r.lon, 6), "s": r.source, "id": r.osm_id,
             **({"conf": int(r.confidence), "fl": (r.flags if isinstance(r.flags, str) else "")} if "confidence" in fac else {})}
            for _, r in fac.iterrows()],
    "lsoa": lsoa_out,
    "edges": edge_out,
    "flood": flood_out,
    "sources": json.loads((REPO / "data" / "raw" / "SOURCES.json").read_text()),
}
OUT.write_text(json.dumps(data, separators=(",", ":")))
print("OAs", len(oa), "facilities", Counter(fac.category), "flood OAs", int(oa_flood.sum()),
      "edges", len(edge_out), "lsoa verts", sum(len(r) for l in lsoa_out for r in l["rings"]),
      "flood verts", sum(len(r) for p in flood_out for r in p), "bytes", OUT.stat().st_size)
