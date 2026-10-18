"""Run the whole places build: load sources, merge, optional Google / Companies House checks, save the
database (CSV + SQLite + summary) and hand the simulator its site list."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path

import pandas as pd

from .common import DB, PROC, RAW, SOURCES, load_city
from .companies import ch_records, companies_house, fetch_ch_advanced, parse_ch_search_csv
from .merge import build
from .sources import (
    fetch_fsa, fetch_nhs, fetch_ofsted, fetch_osm, google_check, parse_fsa, parse_nhs, parse_ofsted, parse_osm,
    postcode_lookup, read_fsa_xml,
)


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
