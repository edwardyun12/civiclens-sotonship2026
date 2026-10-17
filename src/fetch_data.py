"""Download and clean all open datasets for Southampton.

Run once:  python -m src.fetch_data
Writes:    data/raw/*         (untouched API responses)
           data/processed/oa.csv           demand points (Output Area population-weighted centroids)
           data/processed/lsoa.geojson     LSOA 2021 boundaries (map + city outline)
           data/processed/facilities.csv   existing facilities by category (OpenStreetMap)
           data/raw/SOURCES.json           url, licence, download time for every dataset

Every step prints a row count so a human can sanity-check it.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
PROC.mkdir(parents=True, exist_ok=True)

LAD_CODE = "E06000045"  # Southampton unitary authority
LAD_NAME = "Southampton"
ONS = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
NOMIS = "https://www.nomisweb.co.uk/api/v01/dataset"
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
UA = {"User-Agent": "SotonShip2026-planning-simulator/0.1 (hackathon; open data)"}

SOURCES: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def note(key: str, title: str, url: str, licence: str, rows: int) -> None:
    SOURCES[key] = {"title": title, "url": url, "licence": licence, "downloaded": _now(), "rows": rows}
    print(f"  {key}: {rows} rows")


def arcgis_query(service: str, where: str, out_fields: str = "*", geometry: bool = False, layer: int = 0) -> list[dict]:
    """Page through an ONS ArcGIS FeatureServer query. Returns GeoJSON features (geometry) or attribute dicts."""
    url = f"{ONS}/{service}/FeatureServer/{layer}/query"
    out, offset = [], 0
    while True:
        params = {
            "where": where, "outFields": out_fields, "f": "geojson" if geometry else "json",
            "returnGeometry": "true" if geometry else "false", "outSR": 4326,
            "resultOffset": offset, "resultRecordCount": 1000,
        }
        r = requests.post(url, data=params, headers=UA, timeout=120)  # POST: IN-lists are long
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"{service}: {d['error']}")
        batch = d["features"]
        out += batch if geometry else [f["attributes"] for f in batch]
        if len(batch) < 1000 and not d.get("exceededTransferLimit") and not d.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(batch)
        if not batch:
            break
    return out


def in_list(field: str, codes: list[str]) -> list[str]:
    """Split a long IN (...) clause into chunks the server accepts."""
    return [f"{field} IN ({','.join(repr(c) for c in codes[i:i+200])})" for i in range(0, len(codes), 200)]


# ---------------------------------------------------------------- geography
def fetch_geography() -> tuple[pd.DataFrame, dict]:
    print("[1] OA -> LSOA lookup")
    lu = pd.DataFrame(arcgis_query("OA_LSOA_MSOA_EW_DEC_2021_LU_v3", f"LAD22CD='{LAD_CODE}'",
                                   "OA21CD,LSOA21CD,LSOA21NM,MSOA21CD,LAD22CD"))
    lu.to_csv(RAW / "oa_lsoa_lookup.csv", index=False)
    note("oa_lookup", "ONS Output Area to LSOA to MSOA to LAD (Dec 2021) lookup",
         f"{ONS}/OA_LSOA_MSOA_EW_DEC_2021_LU_v3", "OGL v3.0 (Source: Office for National Statistics)", len(lu))

    print("[2] LSOA -> ward lookup")
    wd = pd.DataFrame(arcgis_query("LSOA_2021_to_Ward_to_Lower_Tier_Local_Authority_May_2022_Lookup_for_England_2022",
                                   f"LTLA22CD='{LAD_CODE}'", "LSOA21CD,WD22CD,WD22NM"))
    wd.to_csv(RAW / "lsoa_ward_lookup.csv", index=False)
    note("ward_lookup", "ONS LSOA (2021) to Ward to LTLA (May 2022) lookup",
         f"{ONS}/LSOA_2021_to_Ward_to_Lower_Tier_Local_Authority_May_2022_Lookup_for_England_2022",
         "OGL v3.0 (Source: Office for National Statistics)", len(wd))

    print("[3] OA population-weighted centroids")
    oas = sorted(lu["OA21CD"].unique())
    feats = []
    for w in in_list("OA21CD", oas):
        feats += arcgis_query("OA_December_2021_EW_PWC_V4", w, "OA21CD", geometry=True)
    pwc = pd.DataFrame([{"oa": f["properties"]["OA21CD"], "lon": f["geometry"]["coordinates"][0],
                         "lat": f["geometry"]["coordinates"][1]} for f in feats])
    pwc.to_csv(RAW / "oa_pwc.csv", index=False)
    note("oa_pwc", "ONS Output Areas (Dec 2021) population-weighted centroids V4",
         f"{ONS}/OA_December_2021_EW_PWC_V4", "OGL v3.0 (Source: Office for National Statistics)", len(pwc))

    print("[4] LSOA boundaries (generalised)")
    lsoas = sorted(lu["LSOA21CD"].unique())
    gj = {"type": "FeatureCollection", "features": []}
    for w in in_list("LSOA21CD", lsoas):
        gj["features"] += arcgis_query("Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V5", w,
                                       "LSOA21CD,LSOA21NM", geometry=True)
    (RAW / "lsoa_bgc.geojson").write_text(json.dumps(gj))
    note("lsoa_bounds", "ONS LSOA (Dec 2021) boundaries EW BGC V5",
         f"{ONS}/Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V5",
         "OGL v3.0 (Source: Office for National Statistics; contains OS data (c) Crown copyright and database right)",
         len(gj["features"]))

    print("[5] IMD 2019 (LSOA 2011 codes)")
    imd = pd.DataFrame(arcgis_query("Index_of_Multiple_Deprivation_Dec_2019_Lookup_in_England_2022",
                                    f"LAD19NM='{LAD_NAME}'", "LSOA11CD,LSOA11NM,IMD19"))
    imd.to_csv(RAW / "imd2019.csv", index=False)
    note("imd", "English Indices of Deprivation 2019, IMD rank by LSOA (ONS lookup copy of MHCLG data)",
         f"{ONS}/Index_of_Multiple_Deprivation_Dec_2019_Lookup_in_England_2022",
         "OGL v3.0 (Source: MHCLG, English Indices of Deprivation 2019)", len(imd))

    m = lu.merge(pwc, left_on="OA21CD", right_on="oa").merge(wd, on="LSOA21CD", how="left")
    return m, gj, imd


# ---------------------------------------------------------------- population
def fetch_population(oas: list[str]) -> pd.DataFrame:
    print("[6] Census 2021 TS007A population by OA (total and aged 0-4)")
    rows = []
    for i in range(0, len(oas), 150):
        params = {"date": "latest", "geography": ",".join(oas[i:i+150]), "c2021_age_19": "0,1",
                  "measures": "20100", "select": "geography_code,c2021_age_19,obs_value"}
        r = requests.get(f"{NOMIS}/NM_2020_1.data.csv", params=params, headers=UA, timeout=120)
        r.raise_for_status()
        from io import StringIO
        rows.append(pd.read_csv(StringIO(r.text)))
        time.sleep(0.3)
    df = pd.concat(rows)
    df.to_csv(RAW / "census2021_ts007a_oa.csv", index=False)
    p = df.pivot_table(index="GEOGRAPHY_CODE", columns="C2021_AGE_19", values="OBS_VALUE").reset_index()
    p.columns = ["oa", "pop", "pop_0_4"]
    note("census", "Census 2021 TS007A Age by five-year age bands, Output Areas (Nomis)",
         f"{NOMIS}/NM_2020_1", "OGL v3.0 (Source: Office for National Statistics, Census 2021)", len(p))
    return p


# ---------------------------------------------------------------- facilities
# OSM tags per category. Keep these in sync with src/config.py CATEGORIES.
OSM_QUERIES = {
    "nursery": ['nwr["amenity"="kindergarten"]', 'nwr["amenity"="childcare"]'],
    "gp": ['nwr["amenity"="doctors"]', 'nwr["healthcare"="doctor"]'],
    "pharmacy": ['nwr["amenity"="pharmacy"]', 'nwr["healthcare"="pharmacy"]'],
    "cafe": ['nwr["amenity"="cafe"]'],
    "library": ['nwr["amenity"="library"]'],
    "coworking": ['nwr["amenity"="coworking_space"]', 'nwr["office"="coworking"]'],
}


def fetch_facilities(bbox: tuple[float, float, float, float]) -> pd.DataFrame:
    """bbox = (south, west, north, east), already buffered so we see facilities just over the city edge."""
    print("[7] OpenStreetMap facilities via Overpass")
    s, w, n, e = bbox
    parts = []
    for cat, qs in OSM_QUERIES.items():
        for q in qs:
            parts.append(f'{q}({s},{w},{n},{e});')
    query = f"[out:json][timeout:120];({''.join(parts)});out center tags;"
    last = None
    for url in OVERPASS_MIRRORS:
        try:
            r = requests.post(url, data={"data": query}, headers=UA, timeout=180)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as ex:  # try the next mirror
            last = ex
            print(f"   {url} failed: {ex}")
    else:
        raise RuntimeError(f"All Overpass mirrors failed: {last}")
    (RAW / "osm_facilities.json").write_text(json.dumps(data))
    return parse_osm(data, url)


def parse_osm(data: dict, url: str = "https://overpass-api.de/api/interpreter") -> pd.DataFrame:
    rows = []
    for el in data["elements"]:
        t = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        cat = classify(t)
        if cat:
            rows.append({"category": cat, "name": t.get("name", ""), "lat": lat, "lon": lon,
                         "osm_id": f"{el['type']}/{el['id']}", "source": "OSM"})
    df = pd.DataFrame(rows).drop_duplicates(subset=["category", "osm_id"])
    note("osm", f"OpenStreetMap facilities (Overpass API, OSM data as of {data.get('osm3s', {}).get('timestamp_osm_base', '?')})",
         url, "ODbL 1.0 (c) OpenStreetMap contributors", len(df))
    return df


def classify(t: dict) -> str | None:
    a, h, o = t.get("amenity"), t.get("healthcare"), t.get("office")
    if a in ("kindergarten", "childcare"):
        return "nursery"
    if a == "doctors" or h == "doctor":
        return "gp"
    if a == "pharmacy" or h == "pharmacy":
        return "pharmacy"
    if a == "cafe":
        return "cafe"
    if a == "library":
        return "library"
    if a == "coworking_space" or o == "coworking":
        return "coworking"
    return None


# ---------------------------------------------------------------- NHS registers (D1b)
ODS = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
# Southampton plus neighbouring districts, so sites just over the boundary count.
DISTRICTS = ["SO14", "SO15", "SO16", "SO17", "SO18", "SO19", "SO30", "SO31", "SO40", "SO45", "SO50", "SO52", "SO53"]
NHS_ROLES = {  # category -> list of (param, role id, label)
    "gp": [("NonPrimaryRoleId", "RO76", "GP practice"), ("PrimaryRoleId", "RO96", "Branch surgery")],
    "pharmacy": [("PrimaryRoleId", "RO182", "Pharmacy")],
}


def geocode(postcodes: list[str]) -> dict[str, tuple[float, float]]:
    out = {}
    pcs = sorted(set(postcodes))
    for i in range(0, len(pcs), 100):
        r = requests.post("https://api.postcodes.io/postcodes", json={"postcodes": pcs[i:i+100]}, headers=UA, timeout=60)
        r.raise_for_status()
        for res in r.json()["result"]:
            if res["result"]:
                out[res["query"]] = (res["result"]["latitude"], res["result"]["longitude"])
    return out


def fetch_nhs(bbox: tuple[float, float, float, float]) -> pd.DataFrame:
    print("[8] NHS ODS registers (GP practices, branch surgeries, pharmacies)")
    rows = []
    for cat, roles in NHS_ROLES.items():
        for param, role, label in roles:
            for d in DISTRICTS:
                r = requests.get(ODS, params={param: role, "Status": "Active", "PostCode": d, "Limit": 1000},
                                 headers=UA, timeout=60)
                r.raise_for_status()
                for o in r.json().get("Organisations", []):
                    rows.append({"category": cat, "name": o["Name"].title(), "postcode": o["PostCode"],
                                 "osm_id": f"ods/{o['OrgId']}", "source": f"NHS ODS ({label})"})
    df = pd.DataFrame(rows).drop_duplicates(subset=["category", "osm_id"])
    df.to_csv(RAW / "nhs_ods.csv", index=False)
    ll = geocode(df["postcode"].tolist())
    df["lat"] = df["postcode"].map(lambda p: ll.get(p, (None, None))[0])
    df["lon"] = df["postcode"].map(lambda p: ll.get(p, (None, None))[1])
    s, w, n, e = bbox
    df = df.dropna(subset=["lat"])
    df = df[(df.lat.between(s, n)) & (df.lon.between(w, e))]
    note("nhs_ods", "NHS Organisation Data Service: active GP practices, branch surgeries, pharmacies",
         ODS, "OGL v3.0 (NHS England, Organisation Data Service)", len(df))
    note("postcodes_io", "postcodes.io (ONS Postcode Directory) for geocoding register postcodes",
         "https://api.postcodes.io", "OGL v3.0; contains OS data (c) Crown copyright; Royal Mail data (c) Royal Mail copyright",
         len(ll))
    return df[["category", "name", "lat", "lon", "osm_id", "source"]]


def merge_registers(osm: pd.DataFrame, nhs: pd.DataFrame) -> pd.DataFrame:
    """Official registers replace OSM for categories they cover; OSM stays for the rest."""
    keep = osm[~osm["category"].isin(nhs["category"].unique())]
    return pd.concat([keep, nhs], ignore_index=True)


# ---------------------------------------------------------------- flood zones (D6)
EA_WFS = "https://environment.data.gov.uk/spatialdata/flood-map-for-planning-flood-zones/wfs"
EA_LAYER = "dataset-04532375-a198-476e-985e-0579a0a11b47:Flood_Zones_2_3_Rivers_and_Sea"


def fetch_flood(bbox: tuple[float, float, float, float], raw_file: Path | None = None) -> int:
    """Flood Zone 3 (rivers and sea) polygons, clipped to the city box and simplified (~5 m)."""
    from shapely.geometry import box, mapping, shape
    from shapely.ops import unary_union
    print("[9] Environment Agency Flood Map for Planning, Flood Zone 3")
    s, w, n, e = bbox
    if raw_file and raw_file.exists():
        d = json.loads(raw_file.read_text())
    else:
        params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": EA_LAYER,
                  "outputFormat": "application/json", "srsName": "EPSG:4326",
                  "bbox": f"{s},{w},{n},{e},urn:ogc:def:crs:EPSG::4326", "count": 10000}
        r = requests.get(EA_WFS, params=params, headers=UA, timeout=300)
        r.raise_for_status()
        d = r.json()
        (RAW / "ea_flood_zones.json").write_text(json.dumps(d))  # large; gitignored
    geoms = [shape(f["geometry"]) for f in d["features"] if f["properties"].get("flood_zone") == "FZ3"]
    g = unary_union(geoms).intersection(box(w, s, e, n)).simplify(0.00005, preserve_topology=True)
    out = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"flood_zone": "FZ3"},
                                                       "geometry": mapping(g)}]}
    (PROC / "flood_zone3.geojson").write_text(json.dumps(out))
    note("flood", "Environment Agency Flood Map for Planning: Flood Zones 2 and 3 (rivers and sea); Zone 3 used",
         EA_WFS, "OGL v3.0 (Environment Agency; contains OS data (c) Crown copyright)", len(geoms))
    return len(geoms)


# ---------------------------------------------------------------- main
def main(skip_osm: bool = False, osm_file: str | None = None) -> None:
    if osm_file:  # Overpass blocks some cloud IPs: download on a laptop, then process here
        data = json.loads(Path(osm_file).read_text())
        (RAW / "osm_facilities.json").write_text(json.dumps(data))
        fac = parse_osm(data)
        fac.to_csv(PROC / "facilities_osm.csv", index=False)
        oa = pd.read_csv(PROC / "oa.csv")
        pad = 0.02
        bbox = (oa.lat.min() - pad, oa.lon.min() - pad, oa.lat.max() + pad, oa.lon.max() + pad)
        try:
            fac = merge_registers(fac, fetch_nhs(bbox))
        except Exception as ex:
            print(f"   NHS registers failed, keeping OSM only: {ex}")
        fac.to_csv(PROC / "facilities.csv", index=False)
        print(fac["category"].value_counts().to_string())
        old = json.loads((RAW / "SOURCES.json").read_text()) if (RAW / "SOURCES.json").exists() else {}
        old.update(SOURCES)
        (RAW / "SOURCES.json").write_text(json.dumps(old, indent=2))
        return
    geo, gj, imd = fetch_geography()
    pop = fetch_population(sorted(geo["OA21CD"].unique()))
    oa = geo.merge(pop, on="oa", how="left")

    # IMD 2019 is published on 2011 LSOAs. Most Southampton codes are unchanged in 2021.
    # For OAs whose 2021 LSOA code is new (splits/merges), place the OA's population-weighted
    # centroid inside the official 2011 LSOA boundary and take that LSOA's IMD rank.
    oa = oa.merge(imd[["LSOA11CD", "IMD19"]], left_on="LSOA21CD", right_on="LSOA11CD", how="left")
    oa["imd_match"] = oa["IMD19"].notna().map({True: "code", False: "spatial"})
    miss = oa["IMD19"].isna()
    if miss.any():
        from shapely.geometry import Point, shape
        print("[5b] LSOA 2011 boundaries for spatial IMD match")
        b11 = []
        for w in in_list("LSOA11CD", sorted(imd["LSOA11CD"])):
            b11 += arcgis_query("LSOA_2011_Boundaries_Super_Generalised_Clipped_BSC_EW_V4", w, "LSOA11CD", geometry=True)
        note("lsoa11_bounds", "ONS LSOA (Dec 2011) boundaries BSC V4 (used only to place 2021 OAs in 2011 LSOAs for IMD)",
             f"{ONS}/LSOA_2011_Boundaries_Super_Generalised_Clipped_BSC_EW_V4",
             "OGL v3.0 (Source: Office for National Statistics; contains OS data (c) Crown copyright and database right)", len(b11))
        polys = [(f["properties"]["LSOA11CD"], shape(f["geometry"])) for f in b11]
        rank = imd.set_index("LSOA11CD")["IMD19"]

        def lookup(row):
            p = Point(row["lon"], row["lat"])
            hit = [c for c, g in polys if g.contains(p)]
            if not hit:  # generalised boundary: take nearest polygon
                hit = [min(polys, key=lambda cg: cg[1].distance(p))[0]]
            return rank[hit[0]]
        oa.loc[miss, "IMD19"] = oa[miss].apply(lookup, axis=1)

    # IMD19 is the national rank (1 = most deprived of 32,844 LSOAs). Convert to decile/quintile.
    N_LSOA_ENGLAND = 32844
    oa["imd_rank"] = oa["IMD19"].astype(int)
    oa["imd_decile"] = ((oa["imd_rank"] - 1) * 10 // N_LSOA_ENGLAND + 1).clip(1, 10)
    oa["imd_quintile"] = ((oa["imd_decile"] + 1) // 2).astype(int)

    out = oa.rename(columns={"OA21CD": "oa_code", "LSOA21CD": "lsoa", "LSOA21NM": "lsoa_name",
                             "WD22CD": "ward_code", "WD22NM": "ward"})[
        ["oa_code", "lsoa", "lsoa_name", "ward_code", "ward", "lat", "lon", "pop", "pop_0_4",
         "imd_rank", "imd_decile", "imd_quintile", "imd_match"]]
    out.to_csv(PROC / "oa.csv", index=False)
    (PROC / "lsoa.geojson").write_text(json.dumps(gj))
    print(f"OA rows: {len(out)}, population: {int(out['pop'].sum()):,}, aged 0-4: {int(out['pop_0_4'].sum()):,}")
    print(f"IMD matches: {out['imd_match'].value_counts().to_dict()}")

    if not skip_osm:
        pad = 0.02  # ~2 km so facilities just outside the boundary still count
        bbox = (out.lat.min() - pad, out.lon.min() - pad, out.lat.max() + pad, out.lon.max() + pad)
        fac = fetch_facilities(bbox)
        fac.to_csv(PROC / "facilities_osm.csv", index=False)
        try:
            fac = merge_registers(fac, fetch_nhs(bbox))
        except Exception as ex:
            print(f"   NHS registers failed, keeping OSM only: {ex}")
        fac.to_csv(PROC / "facilities.csv", index=False)
        print(fac["category"].value_counts().to_string())

    old = json.loads((RAW / "SOURCES.json").read_text()) if (RAW / "SOURCES.json").exists() else {}
    old.update(SOURCES)
    (RAW / "SOURCES.json").write_text(json.dumps(old, indent=2))


if __name__ == "__main__":
    f = sys.argv[sys.argv.index("--osm-file") + 1] if "--osm-file" in sys.argv else None
    main(skip_osm="--skip-osm" in sys.argv, osm_file=f)
