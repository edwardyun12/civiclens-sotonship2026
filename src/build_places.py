"""Build a clean, flagged database of named places in Southampton from open registers.

Run on a machine with normal internet (the cloud workspace blocks these sites):

    python -m src.build_places                       # FSA + OSM + NHS ODS + Ofsted, today's data
    python -m src.build_places --google-key KEY      # also cross-check against Google Places (optional, billed)
    python -m src.build_places --offline             # rebuild from files already in data/db/raw (no downloads)
    python -m src.build_places --ch-key KEY          # also link places to Companies House (free key)
    python -m src.build_places --ch-bulk BasicCompanyData.csv   # same, from the free bulk file, no key

Outputs in data/db/:
    places.csv            one row per real-world place, best coordinates, name, type, flags, confidence
    source_records.csv    every record from every source, with the place_id it was matched to
    places.sqlite         the same two tables plus `sources`, for SQL queries
    summary.json          counts per source, per category and per flag
    company_links.csv     only with --ch-key/--ch-bulk: company number, status, SIC, accounts, match confidence
    google_check.csv      only if --google-key: Google place_id, distance and name/type/status checks
                          (gitignored: Google's terms limit storing their content)

Every coordinate keeps its source. Nothing is invented: if two sources disagree, the place is flagged.
No personal data: sources are registers of businesses and public services. Ofsted already withholds
childminders' names and addresses; we keep it that way.
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import math
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "db"
RAW = DB / "raw"
PROC = ROOT / "data" / "processed"
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


# ------------------------------------------------------------------ geometry helpers (no shapely needed)
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


# ------------------------------------------------------------------ names and types
STOP = {"the", "ltd", "limited", "plc", "llp", "co", "and", "of", "uk", "southampton", "t/a", "ta"}


def norm_name(s) -> str:
    s = str(s or "").lower().replace("&", " and ").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in STOP)


GENERIC = {"surgery", "practice", "pharmacy", "chemist", "chemists", "gp", "health", "centre", "center", "medical",
           "doctors", "group", "partnership", "clinic", "cafe", "coffee", "shop", "nursery", "nurseries", "day",
           "pre", "school", "preschool", "library", "store"}


def name_sim(a, b) -> float:
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return 0.0
    if a == b or (len(a) > 4 and a in b) or (len(b) > 4 and b in a):
        return 1.0
    ca, cb = set(a.split()) - GENERIC, set(b.split()) - GENERIC
    if ca and ca == cb:  # same distinctive words, e.g. "Portswood Solent Surgery" / "Solent GP Surgery Portswood"
        return 0.9
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / len(ta | tb)
    return max(jac, difflib.SequenceMatcher(None, a, b).ratio())


def norm_postcode(p) -> str:
    p = re.sub(r"\s+", "", str(p or "").upper())
    return f"{p[:-3]} {p[-3:]}" if len(p) >= 5 else ""


# One shared taxonomy. `sim` = the simulator category the engine uses (None = context only).
TYPE_MAP = {
    # (source, raw type) -> (category, sim)
    ("fsa", "Restaurant/Cafe/Canteen"): ("restaurant_cafe", None),
    ("fsa", "Takeaway/sandwich shop"): ("takeaway", None),
    ("fsa", "Pub/bar/nightclub"): ("pub_bar", None),
    ("fsa", "Retailers - supermarkets/hypermarkets"): ("supermarket", None),
    ("fsa", "Retailers - other"): ("shop_food", None),
    ("fsa", "Hotel/bed & breakfast/guest house"): ("hotel", None),
    ("fsa", "School/college/university"): ("education", None),
    ("fsa", "Hospitals/Childcare/Caring Premises"): ("care_childcare_health", None),
    ("fsa", "Mobile caterer"): ("mobile_caterer", None),
    ("fsa", "Other catering premises"): ("other_catering", None),
    ("fsa", "Manufacturers/packers"): ("food_manufacturer", None),
    ("fsa", "Distributors/Transporters"): ("food_distributor", None),
    ("fsa", "Importers/Exporters"): ("food_distributor", None),
    ("fsa", "Farmers/growers"): ("food_producer", None),
}
OSM_MAP = {
    "amenity=cafe": ("restaurant_cafe", "cafe"), "amenity=restaurant": ("restaurant_cafe", None),
    "amenity=fast_food": ("takeaway", None), "amenity=pub": ("pub_bar", None), "amenity=bar": ("pub_bar", None),
    "amenity=nightclub": ("pub_bar", None), "amenity=kindergarten": ("nursery", "nursery"),
    "amenity=childcare": ("nursery", "nursery"), "amenity=doctors": ("gp", "gp"), "healthcare=doctor": ("gp", "gp"),
    "amenity=pharmacy": ("pharmacy", "pharmacy"), "healthcare=pharmacy": ("pharmacy", "pharmacy"),
    "amenity=dentist": ("dentist", None), "amenity=library": ("library", "library"),
    "amenity=school": ("education", None), "amenity=college": ("education", None),
    "amenity=university": ("education", None), "amenity=coworking_space": ("coworking", None),
    "office=coworking": ("coworking", None), "shop=supermarket": ("supermarket", None),
    "shop=convenience": ("shop_food", None), "shop=bakery": ("shop_food", None), "shop=butcher": ("shop_food", None),
    "amenity=community_centre": ("community", None), "amenity=place_of_worship": ("community", None),
    "leisure=sports_centre": ("leisure", None), "leisure=fitness_centre": ("leisure", None),
    "tourism=hotel": ("hotel", None), "tourism=guest_house": ("hotel", None), "amenity=bank": ("finance", None),
    "amenity=post_office": ("post_office", None), "amenity=social_facility": ("care_childcare_health", None),
    "healthcare=hospital": ("hospital", None), "amenity=hospital": ("hospital", None),
}
# Which categories can plausibly be the same place (for TYPE_CONFLICT)
COMPATIBLE = [
    {"restaurant_cafe", "takeaway", "pub_bar", "other_catering", "hotel", "shop_food", "supermarket"},
    {"nursery", "care_childcare_health", "education"},
    {"gp", "care_childcare_health", "hospital", "pharmacy"},
    {"pharmacy", "shop_food", "supermarket"},
    {"library", "community", "education", "other_catering"},
    {"leisure", "other_catering", "restaurant_cafe", "education"},
]


def compatible(cats: set[str]) -> bool:
    cats = {c for c in cats if c and c != "other"}
    return len(cats) <= 1 or any(cats <= g for g in COMPATIBLE)


def osm_type(t: dict) -> tuple[str, str, str | None]:
    for k in ("amenity", "healthcare", "shop", "office", "leisure", "tourism", "craft"):
        if k in t:
            kv = f"{k}={t[k]}"
            cat, sim = OSM_MAP.get(kv, (f"shop_other" if k == "shop" else "other", None))
            return kv, cat, sim
    return "", "other", None


# ------------------------------------------------------------------ sources
def fetch_fsa() -> pd.DataFrame:
    print("[FSA] food hygiene register")
    base, hdr = "https://api.ratings.food.gov.uk", {**UA, "x-api-version": "2", "accept": "application/json"}
    auths = requests.get(f"{base}/Authorities/basic", headers=hdr, timeout=60).json()["authorities"]
    la = next(a for a in auths if a["Name"].strip().lower() == LA_NAME.lower())
    rows, page = [], 1
    while True:
        r = requests.get(f"{base}/Establishments", headers=hdr, timeout=120,
                         params={"localAuthorityId": la["LocalAuthorityId"], "pageSize": 5000, "pageNumber": page})
        r.raise_for_status()
        est = r.json().get("establishments", [])
        rows += est
        if len(est) < 5000:
            break
        page += 1
    (RAW / "fsa.json").write_text(json.dumps(rows))
    note("fsa", f"FSA Food Hygiene Rating Scheme, {LA_NAME} (API v2, LocalAuthorityId {la['LocalAuthorityId']})",
         f"{base}/Establishments", "OGL v3.0 (Food Standards Agency); rating images not used", len(rows))
    return parse_fsa(rows)


def read_fsa_xml(path: str) -> list[dict]:
    """The FSA open-data file for one council (e.g. FHRS877en-GB.xml = Southampton), turned into the same
    shape as the API's JSON so parse_fsa handles both."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    rows = []
    for e in root.iter("EstablishmentDetail"):
        d = {c.tag: (c.text or "").strip() for c in e if len(c) == 0}
        g = e.find("Geocode")
        d["geocode"] = {"latitude": (g.findtext("Latitude") or "").strip() if g is not None else "",
                        "longitude": (g.findtext("Longitude") or "").strip() if g is not None else ""}
        sc = e.find("Scores")
        if sc is not None:
            d["scores"] = {c.tag: (c.text or "").strip() for c in sc}
        rows.append(d)
    return rows


def parse_fsa(rows: list[dict]) -> pd.DataFrame:
    out = []
    for e in rows:
        g = e.get("geocode") or {}
        lat, lon = g.get("latitude"), g.get("longitude")
        btype = e.get("BusinessType", "")
        cat, sim = TYPE_MAP.get(("fsa", btype), ("other", None))
        addr = ", ".join(x for x in (e.get(f"AddressLine{i}") for i in range(1, 5)) if x)
        out.append({"source": "fsa", "source_id": str(e.get("FHRSID")), "name": e.get("BusinessName", ""),
                    "raw_type": btype, "category": cat, "sim_category": sim,
                    "lat": float(lat) if lat not in (None, "") else None, "lon": float(lon) if lon not in (None, "") else None,
                    "coord_method": "fsa_geocode", "address": addr, "postcode": norm_postcode(e.get("PostCode")),
                    "brand": "", "opening_hours": "", "website": "", "phone": e.get("Phone", "") or "",
                    "quality": f"Hygiene rating {e.get('RatingValue')}" if e.get("RatingValue") not in (None, "") else "",
                    "record_date": str(e.get("RatingDate") or "")[:10],
                    "extra": json.dumps({"rating_pending": e.get("NewRatingPending"), "scheme": e.get("SchemeType"),
                                         "la_business_id": e.get("LocalAuthorityBusinessID")})})
    return pd.DataFrame(out)


OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]


def fetch_osm(bbox) -> pd.DataFrame:
    print("[OSM] every named shop, amenity, healthcare, office, leisure and tourism feature")
    s, w, n, e = bbox
    keys = ["shop", "amenity", "healthcare", "office", "leisure", "tourism", "craft"]
    body = "".join(f'nwr["name"]["{k}"]({s},{w},{n},{e});' for k in keys)
    body += "".join(f'nwr["{k}"="{v}"]({s},{w},{n},{e});' for k, v in  # the simulator's uses, named or not
                    [("amenity", "cafe"), ("amenity", "kindergarten"), ("amenity", "childcare"), ("amenity", "doctors"),
                     ("healthcare", "doctor"), ("amenity", "pharmacy"), ("healthcare", "pharmacy"), ("amenity", "library")])
    q = f"[out:json][timeout:180];({body});out center meta;"
    last = None
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": q}, headers=UA, timeout=240)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as ex:
            last = ex
            print(f"   {url} failed: {ex}")
    else:
        raise RuntimeError(f"All Overpass mirrors failed: {last}")
    (RAW / "osm.json").write_text(json.dumps(data))
    df = parse_osm(data)
    note("osm", f"OpenStreetMap named POIs (data as of {data.get('osm3s', {}).get('timestamp_osm_base', '?')})",
         url, "ODbL 1.0 (c) OpenStreetMap contributors", len(df))
    return df


def parse_osm(data: dict) -> pd.DataFrame:
    out = []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        kv, cat, sim = osm_type(t)
        if lat is None or (not t.get("name") and not sim):
            continue  # unnamed features are kept only for the simulator's five uses (an unnamed café still exists)
        addr = ", ".join(x for x in (" ".join(filter(None, [t.get("addr:housenumber"), t.get("addr:street")])),
                                     t.get("addr:city")) if x)
        out.append({"source": "osm", "source_id": f"{el['type']}/{el['id']}", "name": t.get("name") or f"Unnamed {kv.split('=')[1]}",
                    "raw_type": kv, "category": cat, "sim_category": sim, "lat": lat, "lon": lon,
                    "coord_method": "osm_mapped" if el["type"] == "node" else "osm_building_centre",
                    "address": addr, "postcode": norm_postcode(t.get("addr:postcode")),
                    "brand": t.get("brand", ""), "opening_hours": t.get("opening_hours", ""),
                    "website": t.get("website", "") or t.get("contact:website", ""),
                    "phone": t.get("phone", "") or t.get("contact:phone", ""), "quality": "",
                    "record_date": (t.get("check_date") or el.get("timestamp", ""))[:10],
                    "extra": json.dumps({"brand_wikidata": t.get("brand:wikidata"), "operator": t.get("operator")})})
    return pd.DataFrame(out)


ODS = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
DISTRICTS = ["SO14", "SO15", "SO16", "SO17", "SO18", "SO19", "SO30", "SO31", "SO40", "SO45", "SO50", "SO52", "SO53"]
NHS_ROLES = [("gp", "NonPrimaryRoleId", "RO76", "GP practice"), ("gp", "PrimaryRoleId", "RO96", "Branch surgery"),
             ("pharmacy", "PrimaryRoleId", "RO182", "Pharmacy")]


def fetch_nhs() -> pd.DataFrame:
    print("[NHS] ODS register: GP practices, branch surgeries, pharmacies")
    rows = []
    for cat, param, role, label in NHS_ROLES:
        for d in DISTRICTS:
            r = requests.get(ODS, params={param: role, "Status": "Active", "PostCode": d, "Limit": 1000},
                             headers=UA, timeout=60)
            r.raise_for_status()
            for o in r.json().get("Organisations", []):
                rows.append({"category": cat, "label": label, "name": o["Name"].title(), "postcode": o["PostCode"],
                             "org_id": o["OrgId"], "last_change": o.get("LastChangeDate", "")})
    df = pd.DataFrame(rows).drop_duplicates(subset=["org_id"])
    df.to_csv(RAW / "nhs_ods.csv", index=False)
    note("nhs_ods", "NHS Organisation Data Service: active GP practices, branch surgeries, pharmacies", ODS,
         "OGL v3.0 (NHS England)", len(df))
    return parse_nhs(df)


def parse_nhs(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "source": "nhs_ods", "source_id": df["org_id"].astype(str), "name": df["name"],
        "raw_type": df.get("label", df.get("source", "")), "category": df["category"], "sim_category": df["category"],
        "lat": None, "lon": None, "coord_method": "postcode_centre", "address": "",
        "postcode": df["postcode"].map(norm_postcode), "brand": "", "opening_hours": "", "website": "", "phone": "",
        "quality": "", "record_date": df.get("last_change", pd.Series([""] * len(df))).astype(str).str[:10],
        "extra": "{}"})


OFSTED_PAGE = "https://www.gov.uk/api/content/government/statistical-data-sets/childcare-providers-and-inspections-management-information"


def fetch_ofsted(file: str | None = None) -> pd.DataFrame:
    print("[Ofsted] childcare providers register")
    if file:
        raw, url = Path(file).read_bytes(), file
    else:
        page = requests.get(OFSTED_PAGE, headers=UA, timeout=60).json()
        atts = page.get("details", {}).get("attachments", [])
        pick = [a for a in atts if a.get("url", "").lower().endswith(".csv")
                and ("provider data" in a.get("title", "").lower() or "most recent inspections" in a.get("title", "").lower())]
        if not pick:
            raise RuntimeError("Couldn't find the Ofsted provider CSV; download it and pass --ofsted-file")
        url = pick[0]["url"]
        print(f"   {pick[0]['title']}")
        raw = requests.get(url, headers=UA, timeout=300).content
    (RAW / "ofsted.csv").write_bytes(raw)
    df = pd.read_csv(io.BytesIO(raw), encoding="latin-1", low_memory=False)
    out = parse_ofsted(df)
    note("ofsted", "Ofsted childcare providers and inspections management information", url,
         "OGL v3.0 (Ofsted); childminders' details are redacted at source", len(out))
    return out


def _col(df, *words):
    for c in df.columns:
        lc = c.lower()
        if all(w in lc for w in words):
            return c
    return None


def parse_ofsted(df: pd.DataFrame) -> pd.DataFrame:
    """Column names change between releases, so find them by keywords."""
    c_la = _col(df, "local authority")
    c_name = _col(df, "provider name") or _col(df, "setting name") or _col(df, "name")
    c_pc = _col(df, "postcode")
    c_urn = _col(df, "urn")
    c_type = _col(df, "provider type") or _col(df, "type")
    c_places = _col(df, "places")
    c_grade = _col(df, "overall effectiveness") or _col(df, "overall")
    c_date = _col(df, "inspection date") or _col(df, "date")
    if c_la:
        df = df[df[c_la].astype(str).str.strip().str.lower() == LA_NAME.lower()]
    if c_pc:
        df = df[df[c_pc].notna() & (df[c_pc].astype(str).str.strip().str.lower() != "redacted")]
    if c_name:
        df = df[df[c_name].notna() & (df[c_name].astype(str).str.strip().str.lower() != "redacted")]
    if c_type:  # keep group settings, never childminders
        df = df[~df[c_type].astype(str).str.lower().str.contains("childminder")]
    return pd.DataFrame({
        "source": "ofsted", "source_id": df[c_urn].astype(str) if c_urn else "", "name": df[c_name] if c_name else "",
        "raw_type": df[c_type].astype(str) if c_type else "", "category": "nursery", "sim_category": "nursery",
        "lat": None, "lon": None, "coord_method": "postcode_centre", "address": "",
        "postcode": df[c_pc].map(norm_postcode) if c_pc else "", "brand": "", "opening_hours": "", "website": "",
        "phone": "", "quality": ("Ofsted: " + df[c_grade].astype(str)) if c_grade else "",
        "record_date": df[c_date].astype(str).str[:10] if c_date else "",
        "extra": [json.dumps({"registered_places": (None if not c_places or pd.isna(v) else v)})
                  for v in (df[c_places] if c_places else [None] * len(df))]})


# ------------------------------------------------------------------ postcodes
def postcode_lookup(pcs: list[str], offline: bool) -> dict[str, dict]:
    """postcodes.io bulk lookup -> {postcode: {lat, lon, status}}; terminated postcodes are marked."""
    cache_f = RAW / "postcodes.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    todo = sorted({p for p in pcs if p and p not in cache})
    if todo and not offline:
        print(f"[postcodes.io] {len(todo)} postcodes")
        for i in range(0, len(todo), 100):
            r = requests.post("https://api.postcodes.io/postcodes", json={"postcodes": todo[i:i + 100]},
                              headers=UA, timeout=60)
            r.raise_for_status()
            for res in r.json()["result"]:
                q, v = norm_postcode(res["query"]), res["result"]
                cache[q] = ({"lat": v["latitude"], "lon": v["longitude"], "status": "live"} if v and v.get("latitude")
                            else {"lat": None, "lon": None, "status": "unknown"})
        for p in [p for p in todo if cache.get(p, {}).get("status") == "unknown"]:
            r = requests.get(f"https://api.postcodes.io/terminated_postcodes/{p.replace(' ', '')}", headers=UA, timeout=30)
            if r.status_code == 200:
                v = r.json()["result"]
                cache[p] = {"lat": v.get("latitude"), "lon": v.get("longitude"), "status": "terminated"}
        cache_f.write_text(json.dumps(cache))
        note("postcodes_io", "postcodes.io (ONS Postcode Directory): postcode centres and terminated postcodes",
             "https://api.postcodes.io", "OGL v3.0; contains OS data (c) Crown copyright; Royal Mail data (c) Royal Mail",
             len(cache))
    return cache


# ------------------------------------------------------------------ matching
def match(recs: pd.DataFrame) -> pd.Series:
    """Union-find over records: same place if close and similar name. Returns place index per record."""
    n = len(recs)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    lat, lon = recs["lat"].to_numpy(), recs["lon"].to_numpy()
    src, names, pcs = recs["source"].to_numpy(), recs["name"].to_numpy(), recs["postcode"].to_numpy()
    order = sorted(range(n), key=lambda i: lat[i])  # sweep by latitude
    cands, dups = [], []
    dlat = MATCH_FAR_M / 111_000
    for a_i, a in enumerate(order):
        for b in order[a_i + 1:]:
            if lat[b] - lat[a] > dlat:
                break
            d = metres(lat[a], lon[a], lat[b], lon[b])
            if src[a] == src[b]:
                # the same business entered twice in one register (map or hygiene list): merge it.
                # Never for Companies House or NHS: two records there are two legal entities / organisations.
                if src[a] in DEDUP_SOURCES and d <= DUP_M and name_sim(names[a], names[b]) >= 0.9:
                    dups.append((a, b))
                continue
            if d > MATCH_FAR_M:
                continue
            s = name_sim(names[a], names[b])
            same_pc = pcs[a] and pcs[a] == pcs[b]
            near_ok = d <= MATCH_NEAR_M and s >= MATCH_NEAR_SIM and "ch" not in (src[a], src[b])
            if near_ok or (s >= MATCH_FAR_SIM and (d <= MATCH_FAR_M or same_pc)):
                cands.append((d / MATCH_FAR_M - s, a, b))  # best pairs first
    # merge best pairs first; keep at most one record per source in a place
    srcs_of = {i: {src[i]} for i in range(n)}
    for a, b in dups:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
            srcs_of[ra] |= srcs_of.pop(rb)
    for _, a, b in sorted(cands):
        ra, rb = find(a), find(b)
        if ra != rb and not (srcs_of[ra] & srcs_of[rb]):
            parent[rb] = ra
            srcs_of[ra] |= srcs_of.pop(rb)
    return pd.Series([find(i) for i in range(n)], index=recs.index)


DEDUP_SOURCES, DUP_M = {"osm", "fsa"}, 30
COORD_RANK = {"osm_mapped": 0, "osm_building_centre": 1, "fsa_geocode": 2, "postcode_centre": 3}
SRC_LABEL = {"fsa": "FSA", "osm": "OSM", "nhs_ods": "NHS ODS", "ofsted": "Ofsted", "ch": "Companies House"}

# Confidence penalty per flag (points off a 0-100 score). Every problem flag costs something.
PENALTY = {
    "NOT_IN_SOUTHAMPTON": 25, "DORMANT_OR_NON_TRADING": 25, "NO_COORDINATES": 20,
    "SOURCES_DISAGREE_ON_LOCATION": 15, "TYPE_CONFLICT": 15, "FAR_FROM_OWN_POSTCODE": 15, "POSTCODE_INVALID": 15,
    "NAME_DIFFERS_BETWEEN_SOURCES": 10, "POSTCODE_TERMINATED": 10, "POSSIBLE_DUPLICATE": 10, "OSM_NOT_CHECKED_3Y": 10,
    "SHARED_ADDRESS_5PLUS": 10, "COMPANY_SIC_DOESNT_FIT_TYPE": 10, "COMPANY_REGISTERED_ELSEWHERE": 5,
    "COORDS_FROM_2017_POSTCODE_FILE": 5, "FSA_INSPECTION_OVER_4Y": 5, "FSA_RATING_PENDING": 0,
}


def exclusion_reason(flags: list[str], sources: list[str]) -> str:
    """Records that are out of scope for a Southampton places database: kept in excluded_places.csv with the
    reason, never silently dropped."""
    company_only = sources == ["ch"]
    if "NOT_IN_SOUTHAMPTON" in flags:
        return "Not in Southampton (the address only contains the word Southampton, e.g. Southampton Row, London)"
    if company_only and "DORMANT_OR_NON_TRADING" in flags:
        return "Dormant or non-trading company"
    if company_only and "OUTSIDE_CITY" in flags:
        return "Company registered outside the Southampton city boundary"
    if company_only and "NO_COORDINATES" in flags:
        return "Company postcode could not be located"
    return ""


# SIC 2007 code prefix -> our category (longest prefix wins). Lets companies sit in the same taxonomy as places.
SIC_CATEGORY = {
    "56101": "restaurant_cafe", "56102": "restaurant_cafe", "56103": "takeaway", "5621": "other_catering",
    "5629": "other_catering", "5630": "pub_bar", "4711": "supermarket", "4719": "shop_other", "472": "shop_food",
    "47730": "pharmacy", "47": "shop_other", "88910": "nursery", "85100": "nursery", "85": "education",
    "86210": "gp", "86230": "dentist", "86": "health_other", "87": "care_childcare_health", "88": "care_childcare_health",
    "55": "hotel", "93": "leisure", "96020": "hair_beauty", "96": "personal_services", "91011": "library",
    "91": "community", "94": "community", "90": "leisure", "68": "property", "41": "construction", "42": "construction",
    "43": "construction", "62": "it_tech", "63": "it_tech", "58": "it_tech", "61": "it_tech", "64": "finance",
    "65": "finance", "66": "finance", "69": "professional", "70": "professional", "71": "professional",
    "72": "professional", "73": "professional", "74": "professional", "75": "health_other", "77": "business_services",
    "78": "business_services", "79": "business_services", "80": "business_services", "81": "business_services",
    "82": "business_services", "45": "motor", "46": "wholesale", "49": "transport_logistics", "50": "transport_logistics",
    "51": "transport_logistics", "52": "transport_logistics", "53": "transport_logistics", "10": "food_manufacturer",
    "11": "food_manufacturer", "95": "personal_services", "59": "it_tech", "60": "it_tech", "84": "community",
    "99999": "dormant", "74990": "dormant",
}
for _d in range(5, 34):  # remaining manufacturing and mining divisions
    SIC_CATEGORY.setdefault(f"{_d:02d}", "manufacturing")
for _d in ("01", "02", "03", "35", "36", "37", "38", "39"):
    SIC_CATEGORY.setdefault(_d, "utilities_primary")
SIM_FROM_CATEGORY = {"nursery": "nursery", "gp": "gp", "pharmacy": "pharmacy", "library": "library"}

# Broad industry groups for sorting and reporting (one per category)
INDUSTRY_GROUP = {
    **dict.fromkeys(["restaurant_cafe", "takeaway", "pub_bar", "other_catering", "mobile_caterer"], "Food and drink"),
    **dict.fromkeys(["supermarket", "shop_food", "shop_other"], "Retail"),
    **dict.fromkeys(["gp", "dentist", "pharmacy", "hospital", "health_other"], "Health"),
    **dict.fromkeys(["nursery", "education", "care_childcare_health"], "Childcare, education and care"),
    **dict.fromkeys(["library", "community"], "Community and culture"),
    **dict.fromkeys(["hotel", "leisure"], "Leisure and hospitality"),
    **dict.fromkeys(["hair_beauty", "personal_services"], "Personal services"),
    **dict.fromkeys(["professional", "finance", "property", "it_tech", "business_services", "coworking", "wholesale"],
                    "Business and professional"),
    **dict.fromkeys(["construction", "manufacturing", "food_manufacturer", "food_distributor", "food_producer",
                     "transport_logistics", "motor", "utilities_primary"], "Industry, construction and transport"),
    **dict.fromkeys(["finance_bank", "post_office"], "Business and professional"),
    "dormant": "Dormant or non-trading", "other": "Other",
}
CUSTOMER_FACING_GROUPS = {"Food and drink", "Retail", "Health", "Childcare, education and care", "Community and culture",
                          "Leisure and hospitality", "Personal services"}


def sic_category(codes: list[str]) -> str:
    for code in codes:  # the first listed SIC code is the main activity
        for n in (5, 4, 3, 2):
            if code[:n] in SIC_CATEGORY:
                return SIC_CATEGORY[code[:n]]
    return "other"


def ch_records(reg: pd.DataFrame) -> pd.DataFrame:
    """Companies as source records, so they go through the same matching and flags as every other register.
    Location = registered office postcode centre (filled in by build())."""
    codes = reg["sic_codes"].fillna("").map(lambda s: [c for c in str(s).split("|") if c])
    cats = codes.map(sic_category)
    if "industry" not in reg:
        reg = reg.assign(industry=codes.map(lambda cs: "; ".join(dict.fromkeys(SIC_DIVISIONS.get(c[:2], c) for c in cs))))
    return pd.DataFrame({
        "source": "ch", "source_id": reg["company_number"].astype(str), "name": reg["company_name"],
        "raw_type": reg["sic_codes"].fillna("").map(lambda s: "SIC " + s.replace("|", ", ") if s else "No SIC code"),
        "category": cats, "sim_category": cats.map(SIM_FROM_CATEGORY), "lat": None, "lon": None,
        "coord_method": "postcode_centre", "address": reg["address"].fillna(""), "postcode": reg["postcode"].fillna(""),
        "brand": "", "opening_hours": "", "website": "", "phone": "", "quality": "",
        "record_date": reg["incorporated"].fillna("").astype(str).str[:10],
        "extra": [json.dumps({"company_number": n, "company_type": t, "sic_codes": c, "industry": i})
                  for n, t, c, i in zip(reg["company_number"], reg.get("company_type", ""), reg["sic_codes"].fillna(""),
                                        reg.get("industry", pd.Series([""] * len(reg))).fillna(""))]})


def build(recs: pd.DataFrame, pcs: dict, polys) -> tuple[pd.DataFrame, pd.DataFrame]:
    recs = recs.reset_index(drop=True).copy()
    # 1. fill missing coordinates from the postcode centre; check given coordinates against their postcode
    pc_lat = recs["postcode"].map(lambda p: (pcs.get(p) or {}).get("lat"))
    pc_lon = recs["postcode"].map(lambda p: (pcs.get(p) or {}).get("lon"))
    recs["postcode_status"] = recs["postcode"].map(lambda p: (pcs.get(p) or {}).get("status", "missing" if not p else "unchecked"))
    nocoord = recs["lat"].isna()
    recs.loc[nocoord, "lat"], recs.loc[nocoord, "lon"] = pc_lat[nocoord], pc_lon[nocoord]
    recs.loc[nocoord, "coord_method"] = "postcode_centre"
    recs["m_from_postcode"] = [round(metres(a, b, c, d)) if pd.notna(a) and pd.notna(c) else None
                               for a, b, c, d in zip(recs.lat, recs.lon, pc_lat, pc_lon)]
    recs.loc[recs["coord_method"] == "postcode_centre", "m_from_postcode"] = 0
    recs["no_coords"] = recs["lat"].isna()
    located = recs[~recs["no_coords"]].copy()
    located["place_idx"] = match(located)
    recs["place_idx"] = located["place_idx"].reindex(recs.index)
    recs.loc[recs["no_coords"], "place_idx"] = range(10**6, 10**6 + int(recs["no_coords"].sum()))

    # duplicates inside one register: same source, near-identical name within 30 m
    recs["dup_in_source"] = False
    for (_, g) in located.groupby("source"):
        g = g.sort_values("lat")
        arr = g[["lat", "lon", "name"]].to_numpy()
        for i in range(len(arr)):
            for j in range(i + 1, len(arr)):
                if arr[j][0] - arr[i][0] > 0.0003:
                    break
                if metres(arr[i][0], arr[i][1], arr[j][0], arr[j][1]) <= 30 and name_sim(arr[i][2], arr[j][2]) >= 0.9:
                    recs.loc[[g.index[i], g.index[j]], "dup_in_source"] = True

    # companies sharing one registered address (accountants, formation agents, virtual offices)
    is_ch = recs["source"] == "ch"
    akey = recs["address"].fillna("").str.upper().str.replace(r"[^A-Z0-9]", "", regex=True) + "|" + recs["postcode"].fillna("")
    shared_addr = akey[is_ch].map(akey[is_ch].value_counts()).to_dict()

    # 2. one row per place
    rows = []
    for pid, (_, g) in enumerate(recs.groupby("place_idx", sort=False), start=1):
        g = g.assign(_r=g["coord_method"].map(COORD_RANK).fillna(9)).sort_values("_r")
        best = g.iloc[0]
        flags = []
        srcs = sorted(g["source"].unique())
        if len(srcs) == 1:
            flags.append("SINGLE_SOURCE")
        if g["no_coords"].all():
            flags.append("NO_COORDINATES")
        located_g = g.dropna(subset=["lat"])
        pts = located_g[["lat", "lon"]].to_numpy()
        spread = max((metres(*p, *q) for p in pts for q in pts), default=0)
        # precise pins must agree within 75 m; a postcode-centre pin only has to be within 250 m of them
        precise = located_g[located_g["coord_method"] != "postcode_centre"][["lat", "lon"]].to_numpy()
        rough = located_g[located_g["coord_method"] == "postcode_centre"][["lat", "lon"]].to_numpy()
        if (max((metres(*p, *q) for p in precise for q in precise), default=0) > SPREAD_FLAG_M
                or max((metres(*p, *q) for p in precise for q in rough), default=0) > POSTCODE_FLAG_M):
            flags.append("SOURCES_DISAGREE_ON_LOCATION")
        if best["coord_method"] == "postcode_centre":
            flags.append("COORDS_FROM_POSTCODE_ONLY")
        far = g["m_from_postcode"].dropna()
        if len(far) and far.max() > POSTCODE_FLAG_M:
            flags.append("FAR_FROM_OWN_POSTCODE")
        if (g["postcode_status"] == "terminated").any():
            flags.append("POSTCODE_TERMINATED")
        if (g["postcode_status"] == "unknown").any():
            flags.append("POSTCODE_INVALID")
        if len(g) > 1 and min(name_sim(a, b) for a in g["name"] for b in g["name"]) < 0.8:
            flags.append("NAME_DIFFERS_BETWEEN_SOURCES")
        if not compatible(set(g["category"])):
            flags.append("TYPE_CONFLICT")
        if g["source"].duplicated().any():
            flags.append("MERGED_DUPLICATE")  # same business listed twice in one register, now one place
        elif g["dup_in_source"].any():
            flags.append("POSSIBLE_DUPLICATE")
        for _, r in g.iterrows():
            try:
                age = (TODAY - datetime.strptime(r["record_date"], "%Y-%m-%d").date()).days / 365.25
            except (ValueError, TypeError):
                continue
            if r["source"] == "osm" and age > STALE_OSM_YEARS:
                flags.append("OSM_NOT_CHECKED_3Y")
            if r["source"] == "fsa" and age > STALE_FSA_YEARS:
                flags.append("FSA_INSPECTION_OVER_4Y")
        if re.search(r'"rating_pending": "?true', " ".join(g["extra"]).lower()):
            flags.append("FSA_RATING_PENDING")
        ch = g[g["source"] == "ch"]
        if len(ch) and len(srcs) == 1:
            flags.append("REGISTERED_OFFICE_ONLY")
            if shared_addr.get(ch.index[0], 0) >= 5:
                flags.append("SHARED_ADDRESS_5PLUS")
            if (ch["category"] == "dormant").any():
                flags.append("DORMANT_OR_NON_TRADING")
        if g["postcode"].map(lambda p: bool(p) and not str(p).startswith("SO")).all() and len(ch):
            flags.append("NOT_IN_SOUTHAMPTON")
        if (g["postcode_status"] == "approx_2017").any() and best["coord_method"] == "postcode_centre":
            flags.append("COORDS_FROM_2017_POSTCODE_FILE")
        inside = bool(pd.notna(best["lat"]) and in_city(best["lat"], best["lon"], polys))
        if not inside:
            flags.append("OUTSIDE_CITY")
        flags = sorted(set(flags))
        # confidence: sources agreeing, precise coordinates, no conflicts
        conf = 40 + 20 * (len(srcs) - 1)
        conf += {0: 20, 1: 15, 2: 10, 3: 0}.get(COORD_RANK.get(best["coord_method"], 3), 0)
        conf -= sum(PENALTY.get(f, 0) for f in flags)
        sims = [s for s in g["sim_category"].dropna().unique() if s]
        # category: prefer what the place itself shows (map, registers) over the company's SIC code
        cats = list(dict.fromkeys(list(g[g["source"] != "ch"]["category"]) + list(ch["category"])))
        chx = json.loads(ch.iloc[0]["extra"]) if len(ch) else {}
        pick = lambda col: next((v for v in g[col] if isinstance(v, str) and v), "")
        name_src = next((r for _, r in g.iterrows() if r["source"] in ("nhs_ods", "ofsted", "fsa")),
                        next((r for _, r in g.iterrows() if r["source"] != "ch"), best))
        rows.append({
            "place_id": f"P{pid:05d}", "name": name_src["name"], "category": cats[0], "all_categories": "|".join(cats),
            "sim_category": sims[0] if sims else "", "lat": None if pd.isna(best["lat"]) else round(float(best["lat"]), 6),
            "lon": None if pd.isna(best["lon"]) else round(float(best["lon"]), 6), "coord_source": SRC_LABEL[best["source"]],
            "coord_method": best["coord_method"], "location_spread_m": round(spread), "address": pick("address"),
            "postcode": pick("postcode"), "brand": pick("brand"), "opening_hours": pick("opening_hours"),
            "website": pick("website"), "phone": pick("phone"), "quality": " | ".join(v for v in g["quality"] if v),
            "sources": "|".join(SRC_LABEL[s] for s in srcs), "n_sources": len(srcs),
            "names_seen": " | ".join(dict.fromkeys(g["name"])), "inside_city": inside,
            "confidence": max(0, min(100, conf)), "flags": ";".join(flags),
            "excluded_reason": exclusion_reason(flags, srcs),
            "industry_group": INDUSTRY_GROUP.get(cats[0], "Other"),
            "customer_facing": INDUSTRY_GROUP.get(cats[0], "Other") in CUSTOMER_FACING_GROUPS,
            "company_number": chx.get("company_number", ""), "company_name": ch.iloc[0]["name"] if len(ch) else "",
            "company_type": chx.get("company_type", ""), "sic_codes": chx.get("sic_codes", ""),
            "industry": chx.get("industry", ""), "incorporated": ch.iloc[0]["record_date"] if len(ch) else "",
            "google_maps_url": (f"https://www.google.com/maps/search/?api=1&query={best['lat']:.6f},{best['lon']:.6f}"
                                if pd.notna(best["lat"]) else ""),
            "google_maps_search": "https://www.google.com/maps/search/?api=1&query=" + requests.utils.quote(
                f"{name_src['name']} {pick('postcode')} Southampton"),
        })
        recs.loc[g.index, "place_id"] = f"P{pid:05d}"
    places = pd.DataFrame(rows)
    recs = recs.drop(columns=["place_idx"])
    return places, recs


# ------------------------------------------------------------------ hand the database to the simulator
SIM_USES = ("nursery", "gp", "pharmacy", "cafe", "library")


def export_facilities(places: pd.DataFrame, bbox=None) -> pd.DataFrame:
    """Existing sites for the simulator, taken from the places database.
    A place counts as an existing nursery / GP / pharmacy / café / library when a site-level register or the map
    says so (sim_category). Companies known only by their registered office are NOT counted as sites: a company
    registered at an accountant's office doesn't put a GP surgery there. Coworking is kept for the diversity count."""
    f = places.copy()
    flags = f["flags"].fillna("").astype(str)
    use = f["sim_category"].fillna("").astype(str)
    use = use.where(use.isin(SIM_USES), "")
    use = use.mask((use == "") & (f["category"] == "coworking"), "coworking")
    keep = (use != "") & f["lat"].notna() & ~flags.str.contains("REGISTERED_OFFICE_ONLY|NOT_IN_SOUTHAMPTON")
    if "excluded_reason" in f:
        keep &= f["excluded_reason"].fillna("") == ""
    # where an official register exists, it decides: GP and pharmacy sites must be on the NHS register
    # (the map also tags MRI units, counsellors and clinics as "doctors")
    srcs = f["sources"].fillna("").astype(str)
    if srcs.str.contains("NHS ODS").any():
        keep &= ~use.isin(["gp", "pharmacy"]) | srcs.str.contains("NHS ODS")
    if bbox:
        s_, w_, n_, e_ = bbox
        keep &= f["lat"].between(s_, n_) & f["lon"].between(w_, e_)
    out = pd.DataFrame({"category": use[keep], "name": f.loc[keep, "name"], "lat": f.loc[keep, "lat"],
                        "lon": f.loc[keep, "lon"], "osm_id": f.loc[keep, "place_id"],
                        "source": "places:" + f.loc[keep, "sources"].astype(str),
                        "confidence": f.loc[keep, "confidence"], "flags": flags[keep]})
    return out.reset_index(drop=True)


# ------------------------------------------------------------------ optional Google Places cross-check
def google_check(places: pd.DataFrame, key: str, limit: int) -> pd.DataFrame:
    """Places API (New) text search near each place. Stores only Google's place_id and our comparison.
    Google's terms limit caching their content, so the file is gitignored and should be refreshed, not shipped."""
    print(f"[Google] cross-checking up to {limit} places (billed by Google per request)")
    url = "https://places.googleapis.com/v1/places:searchText"
    hdr = {"X-Goog-Api-Key": key, "Content-Type": "application/json",
           "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.primaryType,places.businessStatus"}
    todo = places[places["lat"].notna()].sort_values("confidence").head(limit)  # check the weakest first
    out = []
    for _, p in todo.iterrows():
        body = {"textQuery": f"{p['name']} {p['postcode']}".strip(), "maxResultCount": 1,
                "locationBias": {"circle": {"center": {"latitude": p["lat"], "longitude": p["lon"]}, "radius": 300.0}}}
        try:
            r = requests.post(url, headers=hdr, json=body, timeout=30)
            r.raise_for_status()
            res = (r.json().get("places") or [None])[0]
        except Exception as ex:
            out.append({"place_id": p["place_id"], "google_status": f"error: {ex}"[:120]})
            continue
        if not res:
            out.append({"place_id": p["place_id"], "google_status": "not_found", "google_flags": "GOOGLE_NOT_FOUND"})
            continue
        d = metres(p["lat"], p["lon"], res["location"]["latitude"], res["location"]["longitude"])
        s = name_sim(p["name"], res.get("displayName", {}).get("text", ""))
        fl = []
        if d > GOOGLE_FLAG_M:
            fl.append("GOOGLE_LOCATION_DIFFERS")
        if s < 0.6:
            fl.append("GOOGLE_NAME_DIFFERS")
        if res.get("businessStatus") in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
            fl.append("GOOGLE_" + res["businessStatus"])
        out.append({"place_id": p["place_id"], "google_place_id": res["id"], "google_distance_m": round(d),
                    "google_name_similarity": round(s, 2), "google_type": res.get("primaryType", ""),
                    "google_status": "found", "google_flags": ";".join(fl),
                    "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        time.sleep(0.05)
    return pd.DataFrame(out)


# ------------------------------------------------------------------ Companies House: who runs each place
CH_API = "https://api.company-information.service.gov.uk"
# Public services and partnerships rarely trade as a company under the shop's name: don't search them.
CH_SKIP = {"gp", "hospital", "education", "library", "community", "post_office", "other"}
SIC_TEXT = {  # the SIC codes we expect for each category (any 2-digit prefix match counts as consistent)
    "restaurant_cafe": ("56",), "takeaway": ("56",), "pub_bar": ("56",), "other_catering": ("56",),
    "nursery": ("88", "85"), "pharmacy": ("47", "86"), "supermarket": ("47",), "shop_food": ("47", "10"),
    "shop_other": ("47",), "dentist": ("86",), "hotel": ("55",), "leisure": ("93", "96"), "coworking": ("68", "82"),
}


def _district(pc: str) -> str:
    return pc.split(" ")[0] if isinstance(pc, str) else ""


def ch_candidates_api(name: str, key: str) -> list[dict]:
    r = requests.get(f"{CH_API}/search/companies", params={"q": name, "items_per_page": 10},
                     auth=(key, ""), headers=UA, timeout=30)
    if r.status_code == 429:
        time.sleep(60)
        return ch_candidates_api(name, key)
    r.raise_for_status()
    return [{"company_number": i["company_number"], "company_name": i.get("title", ""),
             "company_status": i.get("company_status", ""), "postcode": norm_postcode((i.get("address") or {}).get("postal_code"))}
            for i in r.json().get("items", [])]


def ch_profile(num: str, key: str) -> dict:
    r = requests.get(f"{CH_API}/company/{num}", auth=(key, ""), headers=UA, timeout=30)
    if r.status_code == 429:
        time.sleep(60)
        return ch_profile(num, key)
    r.raise_for_status()
    p = r.json()
    la = (p.get("accounts") or {}).get("last_accounts") or {}
    return {"company_type": p.get("type", ""), "incorporated": p.get("date_of_creation", ""),
            "sic_codes": "|".join(p.get("sic_codes", []) or []), "accounts_type": la.get("type", ""),
            "last_accounts_made_up_to": la.get("made_up_to", ""),
            "registered_postcode": norm_postcode((p.get("registered_office_address") or {}).get("postal_code"))}


def fetch_ch_advanced(key: str, location: str = LA_NAME) -> pd.DataFrame:
    """Every ACTIVE company whose registered office is in `location`, via the API's advanced search
    (the same search as the website's Advanced search page). Each call returns at most 5,000, so the
    incorporation dates are split into windows until each window fits."""
    print(f"[Companies House] advanced search: active companies registered in {location}")
    url = f"{CH_API}/advanced-search/companies"
    items: dict[str, dict] = {}

    def call(start: str, end: str) -> dict:
        for _ in range(5):
            r = requests.get(url, auth=(key, ""), headers=UA, timeout=60,
                             params={"location": location, "company_status": "active", "incorporated_from": start,
                                     "incorporated_to": end, "size": 5000})
            if r.status_code == 429:
                time.sleep(60)
                continue
            if r.status_code == 404:  # no results in this window
                return {"hits": 0, "items": []}
            r.raise_for_status()
            time.sleep(0.5)
            return r.json()
        raise RuntimeError("Companies House rate limit kept failing")

    def window(start: datetime, end: datetime):
        d = call(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if d.get("hits", 0) > len(d.get("items", [])) and (end - start).days > 1:
            mid = start + (end - start) / 2
            window(start, mid)
            window(mid + pd.Timedelta(days=1), end)
            return
        for i in d.get("items", []):
            items[i["company_number"]] = i

    window(datetime(1850, 1, 1), datetime.now())
    rows = []
    for i in items.values():
        a = i.get("registered_office_address") or {}
        rows.append({"company_number": i["company_number"], "company_name": i.get("company_name", ""),
                     "company_status": i.get("company_status", ""), "company_type": i.get("company_type", ""),
                     "incorporated": i.get("date_of_creation", ""), "sic_codes": "|".join(i.get("sic_codes") or []),
                     "address": ", ".join(filter(None, [a.get("address_line_1"), a.get("address_line_2"), a.get("locality")])),
                     "postcode": norm_postcode(a.get("postal_code")), "registered_postcode": norm_postcode(a.get("postal_code")),
                     "accounts_type": "", "last_accounts_made_up_to": ""})
    df = pd.DataFrame(rows)
    df.to_csv(DB / "companies_register.csv", index=False)
    note("ch_advanced", f"Companies House advanced search: active companies with a registered office in {location}",
         url, "Companies House public register; company-level facts only", len(df))
    print(f"   {len(df)} active companies")
    return df


# UK SIC 2007 divisions (first two digits), for readable industry labels
SIC_DIVISIONS = {
    "01": "Agriculture", "02": "Forestry", "03": "Fishing", "05": "Coal mining", "06": "Oil and gas extraction",
    "07": "Metal ore mining", "08": "Other mining and quarrying", "09": "Mining support", "10": "Food manufacturing",
    "11": "Beverage manufacturing", "12": "Tobacco", "13": "Textiles", "14": "Clothing manufacturing", "15": "Leather goods",
    "16": "Wood products", "17": "Paper products", "18": "Printing", "19": "Coke and refined petroleum", "20": "Chemicals",
    "21": "Pharmaceutical manufacturing", "22": "Rubber and plastics", "23": "Non-metallic mineral products",
    "24": "Basic metals", "25": "Fabricated metal products", "26": "Computer and electronic products",
    "27": "Electrical equipment", "28": "Machinery", "29": "Motor vehicles", "30": "Other transport equipment",
    "31": "Furniture", "32": "Other manufacturing", "33": "Repair and installation of machinery",
    "35": "Electricity and gas", "36": "Water supply", "37": "Sewerage", "38": "Waste", "39": "Remediation",
    "41": "Building construction", "42": "Civil engineering", "43": "Specialised construction trades",
    "45": "Motor trade and repair", "46": "Wholesale", "47": "Retail", "49": "Land transport", "50": "Water transport",
    "51": "Air transport", "52": "Warehousing and transport support", "53": "Postal and courier",
    "55": "Accommodation", "56": "Food and drink service (cafés, restaurants, pubs, takeaways)", "58": "Publishing",
    "59": "Film, video and music", "60": "Broadcasting", "61": "Telecommunications", "62": "Computer programming and IT",
    "63": "Information services", "64": "Financial services", "65": "Insurance and pensions", "66": "Auxiliary finance",
    "68": "Real estate", "69": "Legal and accounting", "70": "Head offices and management consultancy",
    "71": "Architecture and engineering", "72": "Scientific research", "73": "Advertising and market research",
    "74": "Other professional, scientific and technical", "75": "Veterinary", "77": "Rental and leasing",
    "78": "Employment agencies", "79": "Travel agencies", "80": "Security", "81": "Building services and cleaning",
    "82": "Office and business support", "84": "Public administration", "85": "Education",
    "86": "Human health (GPs, dentists, clinics)", "87": "Residential care", "88": "Social work incl. childcare",
    "90": "Arts and entertainment", "91": "Libraries, museums and heritage", "92": "Gambling", "93": "Sport and recreation",
    "94": "Membership organisations", "95": "Repair of personal goods", "96": "Other personal services (hairdressing etc.)",
    "97": "Households as employers", "98": "Households producing for own use", "99": "Extraterritorial / dormant",
}
# Divisions where a member of the public would normally visit the business (shop-front or service site)
CUSTOMER_FACING = {"47", "55", "56", "75", "85", "86", "87", "88", "91", "93", "95", "96"}
PC_RE = re.compile(r"([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\s*$")
CITY_DISTRICTS = {"SO14", "SO15", "SO16", "SO17", "SO18", "SO19"}  # Southampton city; SO30/31/40 are mostly outside


def parse_ch_search_csv(path: str) -> pd.DataFrame:
    """The CSV downloaded from Companies House 'Advanced search' (max 5,000 rows). Its nature_of_business column
    holds unquoted lists like [56101, 56102], so it can't be read as plain CSV."""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    row_re = re.compile(r'^(?P<name>.*?),(?P<num>[A-Z0-9]{8}),(?P<status>[a-z\-]+),(?P<ctype>[a-z\-]*),(?P<sub>[a-z\-]*),'
                        r'(?P<diss>[\d\-]*),(?P<inc>[\d\-]*),(?P<rem>[\d\-]*),(?P<reg>[\d\-]*),(?P<sic>\[[^\]]*\]|),(?P<addr>.*)$')
    rows, bad = [], 0
    for line in lines[1:]:
        if not line.strip():
            continue
        m = row_re.match(line)
        if not m:  # company names can contain unquoted commas; the fixed-format fields after them anchor the parse
            bad += 1
            continue
        name = m["name"]
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('""', '"')
        num, status, ctype, inc, sic, addr = m["num"], m["status"], m["ctype"], m["inc"], m["sic"].strip("[]"), m["addr"]
        addr = addr.strip().strip('"')
        m = PC_RE.search(addr.upper())
        pc = f"{m.group(1)} {m.group(2)}" if m else ""
        codes = [c.strip() for c in sic.split(",") if c.strip()]
        rows.append({"company_number": num, "company_name": name, "company_status": status, "company_type": ctype,
                     "incorporated": inc, "sic_codes": "|".join(codes),
                     "industry": "; ".join(dict.fromkeys(SIC_DIVISIONS.get(c[:2], c) for c in codes)),
                     "customer_facing": any(c[:2] in CUSTOMER_FACING for c in codes),
                     "address": PC_RE.sub("", addr).strip().rstrip(","), "postcode": pc, "registered_postcode": pc,
                     "accounts_type": "", "last_accounts_made_up_to": ""})
    df = pd.DataFrame(rows).drop_duplicates(subset=["company_number"])
    print(f"[Companies House file] {len(df)} companies read" + (f", {bad} lines couldn't be parsed" if bad else ""))
    note("ch_file", f"Companies House advanced search download ({len(df)} rows; the website caps downloads at 5,000)",
         "https://find-and-update.company-information.service.gov.uk/advanced-search", "Companies House public register", len(df))
    return df


def company_tables(reg: pd.DataFrame, pcs: dict, polys, links: pd.DataFrame | None):
    """companies: every company with coordinates (postcode centre), industry and flags.
    company_addresses: one row per distinct registered address, so companies sharing an address
    become ONE map point instead of a stack of duplicates on the same coordinates."""
    c = reg.copy()
    c["lat"] = c["postcode"].map(lambda p: (pcs.get(p) or {}).get("lat"))
    c["lon"] = c["postcode"].map(lambda p: (pcs.get(p) or {}).get("lon"))
    c["postcode_status"] = c["postcode"].map(lambda p: (pcs.get(p) or {}).get("status", "missing" if not p else "not_found"))
    c["addr_key"] = (c["address"].str.upper().str.replace(r"[^A-Z0-9]", "", regex=True) + "|" + c["postcode"])
    sizes = c.groupby("addr_key")["company_number"].transform("count")
    pc_sizes = c.groupby("postcode")["company_number"].transform("count")
    c["inside_city"] = [bool(pd.notna(a) and in_city(a, b, polys)) for a, b in zip(c["lat"], c["lon"])]
    flags = []
    for i, r in c.iterrows():
        f = ["REGISTERED_OFFICE_ONLY"]  # the legal address, not necessarily where it trades
        if not r["postcode"]:
            f.append("NO_POSTCODE")
        elif pd.isna(r["lat"]):
            f.append("POSTCODE_NOT_FOUND")
        if r["postcode_status"] == "approx_2017":
            f.append("COORDS_FROM_2017_POSTCODE_FILE")
        if r["postcode"] and r["postcode"].split(" ")[0] not in CITY_DISTRICTS and not r["postcode"].startswith("SO"):
            f.append("NOT_IN_SOUTHAMPTON")  # e.g. Southampton Row, London
        elif pd.notna(r["lat"]) and not r["inside_city"]:
            f.append("OUTSIDE_CITY")
        if sizes[i] >= 5:
            f.append("SHARED_ADDRESS_5PLUS")  # accountant, formation agent or virtual office
        elif pc_sizes[i] >= 10:
            f.append("BUSY_POSTCODE")
        if "99999" in r["sic_codes"].split("|") or "74990" in r["sic_codes"].split("|"):
            f.append("DORMANT_OR_NON_TRADING")
        flags.append(";".join(f))
    c["flags"] = flags
    addrs = []
    for aid, (k, g) in enumerate(c.groupby("addr_key", sort=False), start=1):
        r = g.iloc[0]
        addrs.append({"address_id": f"A{aid:05d}", "address": r["address"], "postcode": r["postcode"],
                      "lat": r["lat"], "lon": r["lon"], "n_companies": len(g), "inside_city": r["inside_city"],
                      "n_customer_facing": int(g["customer_facing"].sum()),
                      "industries": "; ".join(pd.Series([x for s in g["industry"] for x in s.split("; ") if x]).value_counts().head(3).index),
                      "flags": ";".join(sorted({f for s in g["flags"] for f in s.split(";")} - {"REGISTERED_OFFICE_ONLY"}))})
        c.loc[g.index, "address_id"] = f"A{aid:05d}"
    addrs = pd.DataFrame(addrs)
    if links is not None and len(links) and "company_number" in links:
        m = links[links["ch_status"] == "matched"].set_index("company_number")["place_id"]
        c["linked_place_id"] = c["company_number"].map(m)
    else:
        c["linked_place_id"] = None
    return c.drop(columns=["addr_key"]), addrs


def load_ch_bulk(path: str) -> pd.DataFrame:
    """Companies House free company data product (BasicCompanyData CSV, or several parts in a folder).
    Kept to companies registered in Southampton-area postcode districts to save memory."""
    files = sorted(Path(path).glob("*.csv")) if Path(path).is_dir() else [Path(path)]
    keep = []
    for f in files:
        for chunk in pd.read_csv(f, chunksize=200_000, dtype=str, low_memory=False):
            chunk.columns = [c.strip() for c in chunk.columns]
            pc = chunk["RegAddress.PostCode"].fillna("").str.upper()
            keep.append(chunk[pc.str.match(r"^SO(1[4-9]|30|31|40|45|5[0-3])\s")])
    df = pd.concat(keep, ignore_index=True)
    sic = [c for c in df.columns if c.startswith("SICCode.SicText")]
    return pd.DataFrame({
        "company_number": df["CompanyNumber"], "company_name": df["CompanyName"], "company_status": df["CompanyStatus"],
        "postcode": df["RegAddress.PostCode"].map(norm_postcode), "company_type": df.get("CompanyCategory", ""),
        "incorporated": df.get("IncorporationDate", ""),
        "sic_codes": df[sic].apply(lambda r: "|".join(str(v).split(" - ")[0] for v in r if isinstance(v, str) and v.strip()), axis=1),
        "accounts_type": df.get("Accounts.AccountCategory", ""), "last_accounts_made_up_to": df.get("Accounts.LastMadeUpDate", ""),
        "registered_postcode": df["RegAddress.PostCode"].map(norm_postcode)})


def companies_house(places: pd.DataFrame, key: str | None, bulk: str | None, limit: int,
                    mode: str = "advanced", register: pd.DataFrame | None = None) -> pd.DataFrame:
    """Link places to the company that most likely runs them. A link needs a strong name match; the registered
    office being in the same postcode district raises confidence. No match is recorded as no match, never guessed.
    Stores company-level facts only (no officers, no people's addresses)."""
    todo = places[~places["category"].isin(CH_SKIP) & (places["name"].str.len() > 2)]
    bulk_df = None
    if register is not None:
        bulk_df = register[register["company_status"].str.lower() == "active"].copy()
        print(f"[Companies House] matching places against {len(bulk_df)} active companies from the register file")
    elif bulk:
        bulk_df = load_ch_bulk(bulk)
        bulk_df = bulk_df[bulk_df["company_status"].str.lower() == "active"]
        print(f"[Companies House] bulk file: {len(bulk_df)} active companies registered in SO districts")
    elif mode == "advanced":
        if not key:
            raise ValueError("Companies House advanced search needs --ch-key (free from developer.company-information.service.gov.uk)")
        bulk_df = fetch_ch_advanced(key)
    if bulk_df is not None:  # local matching: check every place, no request limit
        bulk_df = bulk_df.reset_index(drop=True)
        bulk_df["_n"] = bulk_df["company_name"].map(norm_name)
        index: dict[str, list[int]] = {}
        for i, nm in enumerate(bulk_df["_n"]):
            for t in set(nm.split()):
                if len(t) > 2:
                    index.setdefault(t, []).append(i)
    else:
        todo = todo.sort_values("n_sources", ascending=False).head(limit)
        print(f"[Companies House] name search API: up to {limit} places (600 requests per 5 minutes)")
    out = []
    for _, p in todo.iterrows():
        try:
            if bulk_df is not None:
                toks = [t for t in set(norm_name(p["name"]).split()) if len(t) > 2]
                ids = sorted({i for t in toks for i in index.get(t, [])})
                cands = bulk_df.iloc[ids].to_dict("records") if ids else []
            else:
                cands = ch_candidates_api(p["name"], key)
                time.sleep(0.5)
        except Exception as ex:
            out.append({"place_id": p["place_id"], "ch_status": f"error: {ex}"[:120]})
            continue
        best, best_score = None, 0.0
        for c in cands:
            if str(c.get("company_status", "")).lower() != "active":
                continue  # active companies only
            s = name_sim(p["name"], c["company_name"])
            if s < 0.85:
                continue
            score = s + (0.2 if _district(c["postcode"]) == _district(p["postcode"]) and c["postcode"] else 0)
            score += 0.05 if str(c.get("company_status", "")).lower() == "active" else 0
            if score > best_score:
                best, best_score = c, score
        if not best:
            out.append({"place_id": p["place_id"], "ch_status": "no_match"})
            continue
        prof = {k: best.get(k, "") for k in ("company_type", "incorporated", "sic_codes", "accounts_type",
                                             "last_accounts_made_up_to", "registered_postcode")}
        if key:  # full profile (accounts dates and type) only for companies we actually matched
            try:
                prof = ch_profile(best["company_number"], key)
                time.sleep(0.5)
            except Exception:
                pass
        reg_d, place_d = _district(prof.get("registered_postcode") or best["postcode"]), _district(p["postcode"])
        same_area = (reg_d == place_d) if (reg_d and place_d) else None  # None = place has no postcode to compare
        expect = SIC_TEXT.get(p["category"])
        sic_ok = (not expect) or any(code.startswith(expect) for code in str(prof.get("sic_codes", "")).split("|") if code)
        conf = round(min(1.0, 0.5 + 0.3 * (best_score >= 1.0) + 0.2 * bool(same_area) - 0.3 * (not sic_ok)), 2)
        fl = []
        if same_area is False:
            fl.append("COMPANY_REGISTERED_ELSEWHERE")
        if not sic_ok:
            fl.append("COMPANY_SIC_DOESNT_FIT_TYPE")
        if str(best.get("company_status", "")).lower() not in ("active", ""):
            fl.append("COMPANY_NOT_ACTIVE")
        out.append({"place_id": p["place_id"], "ch_status": "matched", "company_number": best["company_number"],
                    "company_name": best["company_name"], "company_status": best.get("company_status", ""),
                    **prof, "match_confidence": conf, "company_flags": ";".join(fl),
                    "companies_house_url": f"https://find-and-update.company-information.service.gov.uk/company/{best['company_number']}",
                    "filed_accounts_url": f"https://find-and-update.company-information.service.gov.uk/company/{best['company_number']}/filing-history?category=accounts"})
    note("companies_house", "Companies House " + ("free company data product (bulk)" if bulk else
                                                  "advanced search (active, registered in Southampton)" if mode == "advanced"
                                                  else "name search API"),
         bulk or CH_API, "Companies House public register; company-level facts only, no personal data stored", len(out))
    return pd.DataFrame(out)


# ------------------------------------------------------------------ main
def save(places: pd.DataFrame, recs: pd.DataFrame, extra_sources: dict | None = None,
         companies: pd.DataFrame | None = None):
    DB.mkdir(parents=True, exist_ok=True)
    excluded = places[places.get("excluded_reason", pd.Series("", index=places.index)).fillna("") != ""]
    places = places.drop(excluded.index)
    excluded.to_csv(DB / "excluded_places.csv", index=False)
    places.to_csv(DB / "places.csv", index=False)
    recs.to_csv(DB / "source_records.csv", index=False)
    srcs = {**(extra_sources or {}), **SOURCES}
    with sqlite3.connect(DB / "places.sqlite") as con:
        places.to_sql("places", con, if_exists="replace", index=False)
        excluded.to_sql("excluded_places", con, if_exists="replace", index=False)
        recs.to_sql("source_records", con, if_exists="replace", index=False)
        pd.DataFrame([{"key": k, **v} for k, v in srcs.items()]).to_sql("sources", con, if_exists="replace", index=False)
        if companies is not None and len(companies):
            companies.to_sql("company_links", con, if_exists="replace", index=False)
        for t in ("companies", "company_addresses"):
            if (DB / f"{t}.csv").exists():
                pd.read_csv(DB / f"{t}.csv", dtype=str).to_sql(t, con, if_exists="replace", index=False)
        if (DB / "companies_register.csv").exists():
            pd.read_csv(DB / "companies_register.csv", dtype=str).to_sql("companies_register", con, if_exists="replace", index=False)
    if companies is not None and len(companies):
        companies.to_csv(DB / "company_links.csv", index=False)
    flag_counts = pd.Series([f for fs in places["flags"] for f in fs.split(";") if f]).value_counts().to_dict()
    summary = {"built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "places": len(places),
               "source_records": len(recs), "records_by_source": recs["source"].value_counts().to_dict(),
               "places_by_category": places["category"].value_counts().to_dict(),
               "places_by_n_sources": places["n_sources"].value_counts().sort_index().to_dict(),
               "flags": flag_counts, "inside_city": int(places["inside_city"].sum()),
               "excluded": excluded["excluded_reason"].value_counts().to_dict(),
               "company_links": (companies["ch_status"].value_counts().to_dict() if companies is not None and len(companies) else {}),
               "sources": srcs}
    (DB / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use files already in data/db/raw")
    ap.add_argument("--skip", nargs="*", default=[], choices=["fsa", "osm", "nhs", "ofsted"])
    ap.add_argument("--ofsted-file", help="path to a downloaded Ofsted provider CSV")
    ap.add_argument("--fsa-file", help="path to a downloaded FSA open-data XML, e.g. FHRS877en-GB.xml (Southampton)")
    ap.add_argument("--osm-file", help="path to a saved Overpass JSON")
    ap.add_argument("--google-key", help="Google Maps Platform key for the optional cross-check")
    ap.add_argument("--google-limit", type=int, default=200)
    ap.add_argument("--ch-key", help="Companies House API key (free) to link places to companies")
    ap.add_argument("--ch-bulk", help="path to the Companies House free company data CSV (file or folder); no key needed")
    ap.add_argument("--ch-file", help="CSV downloaded from Companies House Advanced search (website)")
    ap.add_argument("--ch-limit", type=int, default=400, help="max places for --ch-mode search")
    ap.add_argument("--ch-mode", choices=["advanced", "search"], default="advanced",
                    help="advanced = pull every active Southampton-registered company, then match locally (default); "
                         "search = one name search per place (finds companies registered elsewhere, e.g. chains)")
    a = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)
    polys, bbox = load_city()
    s, w, n, e = bbox
    bbox = (s - 0.02, w - 0.02, n + 0.02, e + 0.02)  # ~2 km, as fetch_data: sites just over the boundary still count

    parts = []
    steps = [("fsa", lambda: parse_fsa(read_fsa_xml(a.fsa_file)) if a.fsa_file else
              parse_fsa(json.loads((RAW / "fsa.json").read_text())) if a.offline else fetch_fsa()),
             ("osm", lambda: parse_osm(json.loads(Path(a.osm_file or RAW / "osm.json").read_text()))
              if (a.offline or a.osm_file) else fetch_osm(bbox)),
             ("nhs", lambda: parse_nhs(pd.read_csv(RAW / "nhs_ods.csv")) if a.offline else fetch_nhs()),
             ("ofsted", lambda: parse_ofsted(pd.read_csv(RAW / "ofsted.csv", encoding="latin-1", low_memory=False))
              if a.offline else fetch_ofsted(a.ofsted_file))]
    for key, fn in steps:
        if key in a.skip:
            continue
        try:
            df = fn()
            print(f"   {key}: {len(df)} records")
            parts.append(df)
        except Exception as ex:  # one failing source shouldn't stop the others
            print(f"   {key} FAILED: {ex}. Continuing without it.")
    if not parts:
        sys.exit("No source loaded.")
    register = None
    if a.ch_file:
        register = parse_ch_search_csv(a.ch_file)
    elif a.ch_key and a.ch_mode == "advanced":
        try:
            register = fetch_ch_advanced(a.ch_key)
        except Exception as ex:
            print(f"   Companies House FAILED: {ex}. Continuing without it.")
    if register is not None:
        parts.append(ch_records(register))
        print(f"   companies: {len(register)} records")
    recs = pd.concat(parts, ignore_index=True)
    # keep only records near the city (bbox), plus register records that only have a postcode
    recs = recs[recs["lat"].isna() | (recs["lat"].between(bbox[0], bbox[2]) & recs["lon"].between(bbox[1], bbox[3]))]
    pcs = postcode_lookup(recs["postcode"].dropna().tolist(), a.offline)
    places, recs = build(recs, pcs, polys)
    if a.google_key:
        gc = google_check(places, a.google_key, a.google_limit)
        gc.to_csv(DB / "google_check.csv", index=False)
        if "google_flags" in gc:
            gf = gc.set_index("place_id")["google_flags"].fillna("")
            places["flags"] = [";".join(sorted(set(filter(None, (f + ";" + gf.get(pid, "")).split(";")))))
                               for f, pid in zip(places["flags"], places["place_id"])]
            places["google_checked"] = places["place_id"].isin(gc["place_id"])
    companies = None
    if a.ch_bulk or (a.ch_key and a.ch_mode == "search"):  # extra links for companies registered elsewhere (chains)
        companies = companies_house(places, a.ch_key, a.ch_bulk, a.ch_limit, a.ch_mode)
        if len(companies) and "company_number" in companies:
            m = companies[companies["ch_status"] == "matched"].set_index("place_id")
            for col in ("company_number", "company_name", "company_status", "sic_codes", "accounts_type",
                        "last_accounts_made_up_to", "match_confidence", "companies_house_url", "filed_accounts_url"):
                places[col] = places["place_id"].map(m[col]) if col in m else None
            cf = m["company_flags"].fillna("") if "company_flags" in m else pd.Series(dtype=str)
            places["flags"] = [";".join(sorted(set(filter(None, (f + ";" + cf.get(pid, "")).split(";")))))
                               for f, pid in zip(places["flags"], places["place_id"])]
    summary = save(places, recs, companies=companies)
    fac = export_facilities(places, bbox)
    fac.to_csv(PROC / "facilities_places.csv", index=False)
    print(f"Simulator sites from the database: {fac['category'].value_counts().to_dict()} -> data/processed/facilities_places.csv")
    print(json.dumps({k: v for k, v in summary.items() if k != "sources"}, indent=1, default=str))
    print(f"Saved data/db/places.csv ({len(places)} places), source_records.csv, places.sqlite, summary.json")


if __name__ == "__main__":
    main()
