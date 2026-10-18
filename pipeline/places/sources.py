"""Download and parse each open register: FSA food hygiene, OpenStreetMap, NHS ODS, Ofsted, postcodes.io,
and the optional Google Places cross-check."""
from __future__ import annotations

import io
import json
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path

import pandas as pd
import requests

from .common import GOOGLE_FLAG_M, LA_NAME, RAW, UA, metres, note
from .names import TYPE_MAP, name_sim, norm_postcode, osm_type


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
                    "extra": json.dumps({"brand_wikidata": t.get("brand:wikidata"), "operator": t.get("operator"),
                                         "cuisine": t.get("cuisine"), "healthcare": t.get("healthcare"),
                                         "shop": t.get("shop"), "amenity": t.get("amenity"), "leisure": t.get("leisure"),
                                         "beauty": t.get("beauty"), "diet": t.get("diet:vegan")})})
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
