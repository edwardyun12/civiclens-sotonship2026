"""Match records from different sources that describe the same real place, merge them into one row with the
best coordinates and name, and flag disagreements and low-confidence places."""
from __future__ import annotations

import json
import re
from datetime import datetime

import pandas as pd
import requests

from .business_types import CUSTOMER_FACING_GROUPS, INDUSTRY_GROUP, detailed_type, specialty_of
from .common import (
    MATCH_FAR_M, MATCH_FAR_SIM, MATCH_NEAR_M, MATCH_NEAR_SIM, POSTCODE_FLAG_M, SPREAD_FLAG_M, STALE_FSA_YEARS,
    STALE_OSM_YEARS, TODAY, in_city, metres, ward_of,
)
from .names import compatible, display_name, name_sim, norm_name


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
    # "same type" = same simulator use, or same category; companies (SIC-based) count as compatible with anything
    typ = recs["category"].fillna("").astype(str).to_numpy()
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
                if (src[a] in DEDUP_SOURCES and d <= DUP_M and typ[a] == typ[b]
                        and name_sim(names[a], names[b]) >= 0.9):
                    dups.append((a, b))
                continue
            if d > MATCH_FAR_M:
                continue
            same_type = typ[a] == typ[b] or "ch" in (src[a], src[b])
            s = name_sim(names[a], names[b], same_type)
            same_pc = pcs[a] and pcs[a] == pcs[b]
            # loose name match only for the same type of business; different types need near-identical names
            near_ok = d <= MATCH_NEAR_M and s >= MATCH_NEAR_SIM and "ch" not in (src[a], src[b]) and typ[a] == typ[b]
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
# Which source's name is used when sources disagree (lower = more reliable for the name people see).
# Statutory registers first: the regulator holds the current registered name and must be told of changes
# (NHS ODS for GPs and pharmacies, Ofsted for childcare, the council's food hygiene register for food businesses).
# OpenStreetMap is volunteer-edited and can lag a rebrand or closure (e.g. old "Lloyds Pharmacy" names).
# Companies House is the legal entity's name ("X LIMITED"), not the name over the door, so it is used only
# when nothing else names the place; it is always kept in company_name.
NAME_PRIORITY = {"nhs_ods": 0, "ofsted": 0, "fsa": 1, "osm": 2, "ch": 3}
# Confidence penalty per flag (points off a 0-100 score). Every problem flag costs something.
PENALTY = {
    "NOT_IN_SOUTHAMPTON": 25, "DORMANT_OR_NON_TRADING": 25, "NO_COORDINATES": 20,
    "SOURCES_DISAGREE_ON_LOCATION": 15, "TYPE_CONFLICT": 15, "FAR_FROM_OWN_POSTCODE": 15, "POSTCODE_INVALID": 15,
    "NAME_DIFFERS_BETWEEN_SOURCES": 5,  # resolved by NAME_PRIORITY; the small penalty marks a possible rebrand
    "POSTCODE_TERMINATED": 10, "POSSIBLE_DUPLICATE": 10, "OSM_NOT_CHECKED_3Y": 10,
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
        name_src = min((r for _, r in g.iterrows()), key=lambda r: NAME_PRIORITY.get(r["source"], 9))
        # a bare brand from a register ("Well") gives way to a fuller name that contains it ("Well Pharmacy")
        if len(norm_name(name_src["name"]).split()) == 1:
            fuller = [r for _, r in g.iterrows() if r["source"] != "ch" and len(norm_name(r["name"])) > len(norm_name(name_src["name"]))
                      and norm_name(name_src["name"]) in norm_name(r["name"]).split()]
            if fuller:
                name_src = fuller[0]
        rows.append({
            "place_id": f"P{pid:05d}", "name": display_name(name_src["name"], name_src["source"]),
            "name_source": SRC_LABEL[name_src["source"]], "category": cats[0], "all_categories": "|".join(cats),
            "sim_category": sims[0] if sims else "", "lat": None if pd.isna(best["lat"]) else round(float(best["lat"]), 6),
            "lon": None if pd.isna(best["lon"]) else round(float(best["lon"]), 6), "coord_source": SRC_LABEL[best["source"]],
            "coord_method": best["coord_method"], "location_spread_m": round(spread), "address": pick("address"),
            "postcode": pick("postcode"), "brand": pick("brand"), "opening_hours": pick("opening_hours"),
            "website": pick("website"), "phone": pick("phone"), "quality": " | ".join(v for v in g["quality"] if v),
            "sources": "|".join(SRC_LABEL[s] for s in srcs), "n_sources": len(srcs),
            "names_seen": " | ".join(dict.fromkeys(g["name"])), "inside_city": inside,
            "confidence": max(0, min(100, conf)), "flags": ";".join(flags),
            "excluded_reason": exclusion_reason(flags, srcs),
            "ward": ward_of(best["lat"], best["lon"]) if inside else "",
            **{k: v for k, v in detailed_type(g, cats[0], name_src["name"], chx.get("sic_codes", "")).items()},
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
    if len(places):
        sp = places.apply(specialty_of, axis=1)
        places["specialty"], places["specialty_from"] = sp.str[0], sp.str[1]
    recs = recs.drop(columns=["place_idx"])
    return places, recs
