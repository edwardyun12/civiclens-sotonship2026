"""Companies House: link places to the companies that run them (advanced search, name search, bulk file,
or a CSV from the website) and build the company tables."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from .business_types import SIM_FROM_CATEGORY, sic_category
from .common import DB, LA_NAME, UA, in_city, note
from .names import name_sim, norm_name, norm_postcode


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
