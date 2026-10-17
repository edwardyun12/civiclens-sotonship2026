"""Tests for the places database pipeline (offline, synthetic records). Run: pytest -q tests/test_build_places.py"""
import pandas as pd

from src import build_places as BP

POLYS, _ = BP.load_city()
CENTRE = (50.9046, -1.4045)          # inside the city
PCS = {"SO14 7DU": {"lat": 50.9046, "lon": -1.4045, "status": "live"},
       "SO15 2AA": {"lat": 50.9100, "lon": -1.4200, "status": "live"},
       "SO14 0XX": {"lat": 50.9000, "lon": -1.4000, "status": "terminated"}}


def rec(source, sid, name, cat, lat, lon, pc="SO14 7DU", method=None, date="2026-09-01", sim=None):
    return {"source": source, "source_id": sid, "name": name, "raw_type": cat, "category": cat, "sim_category": sim,
            "lat": lat, "lon": lon, "coord_method": method or {"osm": "osm_mapped", "fsa": "fsa_geocode"}.get(source, "postcode_centre"),
            "address": "", "postcode": pc, "brand": "", "opening_hours": "", "website": "", "phone": "",
            "quality": "", "record_date": date, "extra": "{}"}


def run(rows):
    return BP.build(pd.DataFrame(rows), PCS, POLYS)


def flags(places, name):
    return set(places.loc[places["name"] == name, "flags"].iloc[0].split(";")) - {""}


def test_name_normalising():
    assert BP.norm_name("The Coffee & Co Ltd") == "coffee"
    assert BP.name_sim("Costa Coffee", "COSTA COFFEE LTD") == 1.0
    assert BP.name_sim("Costa Coffee", "Greggs") < 0.5
    assert BP.norm_postcode("so147du") == "SO14 7DU"


def test_same_cafe_in_two_sources_becomes_one_place():
    p, r = run([rec("fsa", "1", "Bean There Cafe", "restaurant_cafe", 50.9046, -1.4045),
                rec("osm", "node/1", "Bean There", "restaurant_cafe", 50.90475, -1.40445, sim="cafe")])
    assert len(p) == 1
    row = p.iloc[0]
    assert row["n_sources"] == 2 and row["coord_source"] == "OSM"  # surveyed point preferred
    assert "SINGLE_SOURCE" not in row["flags"]
    assert r["place_id"].nunique() == 1


def test_different_businesses_next_door_stay_separate():
    p, _ = run([rec("fsa", "1", "Bean There Cafe", "restaurant_cafe", 50.9046, -1.4045),
                rec("osm", "node/2", "Golden Dragon Takeaway", "takeaway", 50.90462, -1.40452)])
    assert len(p) == 2
    assert all("SINGLE_SOURCE" in f for f in p["flags"])


def test_location_disagreement_and_type_conflict_are_flagged():
    p, _ = run([rec("fsa", "1", "Riverside Store", "restaurant_cafe", 50.9046, -1.4045),
                rec("osm", "node/3", "Riverside Store", "nursery", 50.9055, -1.4045)])  # ~100 m apart, same name
    f = flags(p, "Riverside Store")
    assert "SOURCES_DISAGREE_ON_LOCATION" in f and "TYPE_CONFLICT" in f


def test_postcode_checks():
    p, _ = run([rec("fsa", "1", "Far Away Deli", "shop_food", 50.9046, -1.4045, pc="SO15 2AA"),
                rec("ofsted", "EY1", "Little Acorns", "nursery", None, None, pc="SO14 0XX")])
    assert "FAR_FROM_OWN_POSTCODE" in flags(p, "Far Away Deli")
    f = flags(p, "Little Acorns")
    assert "POSTCODE_TERMINATED" in f and "COORDS_FROM_POSTCODE_ONLY" in f


def test_missing_coordinates_and_outside_city():
    p, _ = run([rec("ofsted", "EY2", "No Postcode Nursery", "nursery", None, None, pc=""),
                rec("osm", "node/4", "Isle of Wight Cafe", "restaurant_cafe", 50.70, -1.30)])
    assert "NO_COORDINATES" in flags(p, "No Postcode Nursery")
    assert "OUTSIDE_CITY" in flags(p, "Isle of Wight Cafe")


def test_stale_and_duplicate_flags():
    p, _ = run([rec("osm", "node/5", "Old Corner Shop", "shop_food", 50.9046, -1.4045, date="2019-01-01"),
                rec("osm", "node/6", "Old Corner Shop", "shop_food", 50.90461, -1.40451, date="2019-01-01")])
    assert len(p) == 1  # the same shop entered twice on the map is merged into one place
    assert "OSM_NOT_CHECKED_3Y" in p.iloc[0]["flags"] and "MERGED_DUPLICATE" in p.iloc[0]["flags"]


def test_out_of_scope_companies_are_excluded_with_a_reason():
    reg = pd.DataFrame([
        {"company_number": "1", "company_name": "LONDON ROW LTD", "company_type": "ltd", "incorporated": "", "sic_codes": "68209",
         "address": "1 Southampton Row London", "postcode": "WC1B 5HA"},
        {"company_number": "2", "company_name": "SLEEPY LTD", "company_type": "ltd", "incorporated": "", "sic_codes": "99999",
         "address": "1 High St Southampton", "postcode": "SO14 7DU"}])
    p, _ = run(BP.ch_records(reg).to_dict("records"))
    r = p.set_index("company_number")["excluded_reason"]
    assert "Not in Southampton" in r["1"] and "Dormant" in r["2"]
    assert (p["confidence"] < 40).all()


def test_confidence_rewards_agreement():
    p, _ = run([rec("fsa", "1", "Bean There Cafe", "restaurant_cafe", 50.9046, -1.4045),
                rec("osm", "node/1", "Bean There", "restaurant_cafe", 50.90475, -1.40445),
                rec("ofsted", "EY3", "Tiny Steps", "nursery", None, None, pc="SO15 2AA")])
    assert p.set_index("name").loc["Bean There Cafe", "confidence"] > p.set_index("name").loc["Tiny Steps", "confidence"]


def test_companies_house_match_and_no_guessing():
    places = pd.DataFrame([
        {"place_id": "P1", "name": "Bean There Cafe", "category": "restaurant_cafe", "postcode": "SO14 7DU", "n_sources": 2},
        {"place_id": "P2", "name": "Unknown Sole Trader", "category": "restaurant_cafe", "postcode": "SO14 7DU", "n_sources": 1}])
    fake = {"Bean There Cafe": [{"company_number": "01234567", "company_name": "BEAN THERE CAFE LTD",
                                 "company_status": "active", "postcode": "SO14 1AA"}],
            "Unknown Sole Trader": [{"company_number": "07654321", "company_name": "SOMETHING ELSE LIMITED",
                                     "company_status": "active", "postcode": "SO14 1AA"}]}
    orig = BP.ch_candidates_api, BP.ch_profile, BP.time.sleep
    BP.ch_candidates_api = lambda name, key: fake[name]
    BP.ch_profile = lambda num, key: {"company_type": "ltd", "incorporated": "2015-01-01", "sic_codes": "56102",
                                      "accounts_type": "micro-entity", "last_accounts_made_up_to": "2025-03-31",
                                      "registered_postcode": "SO14 1AA"}
    BP.time.sleep = lambda s: None
    try:
        out = BP.companies_house(places, "key", None, 10, mode="search").set_index("place_id")
    finally:
        BP.ch_candidates_api, BP.ch_profile, BP.time.sleep = orig
    assert out.loc["P1", "company_number"] == "01234567"
    assert out.loc["P1", "match_confidence"] == 1.0  # exact name, same district, SIC 56 fits a cafe
    assert out.loc["P2", "ch_status"] == "no_match"


def test_companies_house_flags_wrong_industry():
    places = pd.DataFrame([{"place_id": "P1", "name": "Sunshine Nursery", "category": "nursery",
                            "postcode": "SO15 2AA", "n_sources": 1}])
    orig = BP.ch_candidates_api, BP.ch_profile, BP.time.sleep
    BP.ch_candidates_api = lambda name, key: [{"company_number": "1", "company_name": "SUNSHINE NURSERY LIMITED",
                                               "company_status": "active", "postcode": "BH1 1AA"}]
    BP.ch_profile = lambda num, key: {"sic_codes": "01300", "registered_postcode": "BH1 1AA"}  # plant nursery
    BP.time.sleep = lambda s: None
    try:
        out = BP.companies_house(places, "key", None, 10, mode="search").iloc[0]
    finally:
        BP.ch_candidates_api, BP.ch_profile, BP.time.sleep = orig
    assert "COMPANY_SIC_DOESNT_FIT_TYPE" in out["company_flags"]
    assert "COMPANY_REGISTERED_ELSEWHERE" in out["company_flags"]
    assert out["match_confidence"] < 0.6


def test_advanced_search_splits_windows_and_matches_locally(tmp_path=None):
    """Fake API: 12 active companies; each call returns at most 5, so the date range must be split."""
    import datetime as dt
    companies = [{"company_number": f"{i:08d}", "company_name": f"Company {i} Ltd", "company_status": "active",
                  "company_type": "ltd", "date_of_creation": f"{2000 + i}-06-01", "sic_codes": ["56102"],
                  "registered_office_address": {"address_line_1": "1 High St", "locality": "Southampton",
                                                "postal_code": "SO14 7DU"}} for i in range(12)]
    companies.append({**companies[0], "company_number": "99999999", "company_name": "Bean There Cafe Limited",
                      "date_of_creation": "2018-03-01"})

    class R:
        def __init__(self, d): self.d, self.status_code = d, 200
        def json(self): return self.d
        def raise_for_status(self): pass

    def fake_get(url, params=None, **kw):
        a, b = params["incorporated_from"], params["incorporated_to"]
        hit = [c for c in companies if a <= c["date_of_creation"] <= b]
        return R({"hits": len(hit), "items": hit[:5]})

    orig = BP.requests.get, BP.time.sleep, BP.DB
    import tempfile, pathlib
    BP.requests.get, BP.time.sleep = fake_get, (lambda s: None)
    BP.DB = pathlib.Path(tempfile.mkdtemp())
    try:
        reg = BP.fetch_ch_advanced("key")
        places = pd.DataFrame([{"place_id": "P1", "name": "Bean There Cafe", "category": "restaurant_cafe",
                                "postcode": "SO14 7DU", "n_sources": 2}])
        BP.fetch_ch_advanced = lambda key: reg
        BP.ch_profile = lambda num, key: {"sic_codes": "56102", "registered_postcode": "SO14 7DU",
                                          "accounts_type": "micro-entity", "last_accounts_made_up_to": "2025-12-31"}
        out = BP.companies_house(places, "key", None, 10, mode="advanced")
    finally:
        BP.requests.get, BP.time.sleep, BP.DB = orig
        import importlib; importlib.reload(BP)
    assert len(reg) == 13 and set(reg["company_status"]) == {"active"}
    assert out.iloc[0]["company_number"] == "99999999"


def test_companies_house_website_csv_parses_commas_and_brackets(tmp_path=None):
    import tempfile, pathlib
    f = pathlib.Path(tempfile.mkdtemp()) / "ch.csv"
    f.write_text(
        "company_name,company_number,company_status,company_type,company_subtype,dissolution_date,incorporation_date,"
        "removed_date,registered_date,nature_of_business,registered_office_address\n"
        "H, B, C CONSULTANCY LTD,15803999,active,ltd,,,2024-06-26,,2024-06-26,[70229],60 Winchester Road Southampton England SO16 6UL\n"
        '"THE FIRST" GALLERY LTD,13784047,active,ltd,,,2021-12-06,,2021-12-06,[47781, 47910, 58110],1 Burnham Chase Southampton England SO18 5DG\n'
        "NO SIC LTD,00000001,active,ltd,,,2020-01-01,,2020-01-01,,One Southampton Row, London WC1B 5HA\n")
    df = BP.parse_ch_search_csv(str(f)).set_index("company_number")
    assert df.loc["15803999", "company_name"] == "H, B, C CONSULTANCY LTD"
    assert df.loc["13784047", "company_name"] == '"THE FIRST" GALLERY LTD'
    assert df.loc["13784047", "sic_codes"] == "47781|47910|58110" and df.loc["13784047", "customer_facing"]
    assert df.loc["00000001", "postcode"] == "WC1B 5HA"


def test_company_tables_one_point_per_address():
    reg = pd.DataFrame([
        {"company_number": str(i), "company_name": f"Co {i}", "company_status": "active", "company_type": "ltd",
         "incorporated": "", "sic_codes": "56102", "industry": "Food", "customer_facing": True,
         "address": "Tagus House Southampton", "postcode": "SO14 7DU", "registered_postcode": "SO14 7DU"} for i in range(6)]
        + [{"company_number": "99", "company_name": "London Co", "company_status": "active", "company_type": "ltd",
            "incorporated": "", "sic_codes": "99999", "industry": "", "customer_facing": False,
            "address": "One Southampton Row London", "postcode": "WC1B 5HA", "registered_postcode": "WC1B 5HA"}])
    comp, addrs = BP.company_tables(reg, PCS, POLYS, None)
    assert len(addrs) == 2 and addrs.set_index("postcode").loc["SO14 7DU", "n_companies"] == 6
    assert comp["address_id"].nunique() == 2
    f = comp.set_index("company_number")["flags"]
    assert "SHARED_ADDRESS_5PLUS" in f["0"] and "NOT_IN_SOUTHAMPTON" in f["99"] and "DORMANT_OR_NON_TRADING" in f["99"]


def test_company_merges_into_matching_place_and_others_stay_separate():
    reg = pd.DataFrame([
        {"company_number": "1", "company_name": "BEAN THERE CAFE LIMITED", "company_type": "ltd", "incorporated": "2018-01-01",
         "sic_codes": "56102", "address": "1 High St Southampton", "postcode": "SO14 7DU"},
        {"company_number": "2", "company_name": "ACME PROPERTY LTD", "company_type": "ltd", "incorporated": "2019-01-01",
         "sic_codes": "68209", "address": "1 High St Southampton", "postcode": "SO14 7DU"}])
    rows = [rec("osm", "node/1", "Bean There", "restaurant_cafe", 50.90475, -1.40445)] + \
        BP.ch_records(reg).to_dict("records")
    p, r = run(rows)
    cafe = p[p["names_seen"].str.contains("Bean There")].iloc[0]
    assert cafe["n_sources"] == 2 and cafe["company_number"] == "1" and cafe["name"] == "Bean There"
    assert cafe["industry_group"] == "Food and drink" and cafe["customer_facing"]
    prop = p[p["company_number"] == "2"].iloc[0]
    assert prop["category"] == "property" and "REGISTERED_OFFICE_ONLY" in prop["flags"]
    assert prop["industry_group"] == "Business and professional" and not prop["customer_facing"]
    assert len(p) == 2


def test_sic_category():
    assert BP.sic_category(["56103"]) == "takeaway"
    assert BP.sic_category(["47730"]) == "pharmacy"
    assert BP.sic_category(["88910"]) == "nursery"
    assert BP.sic_category(["99999"]) == "dormant"
    assert BP.sic_category([]) == "other"


def test_pharmacy_and_surgery_with_same_place_name_stay_separate():
    p, _ = run([rec("nhs_ods", "FA1", "Bitterne Pharmacy", "pharmacy", 50.9174, -1.3587, sim="pharmacy"),
                rec("osm", "node/8", "Bitterne Pharmacy", "pharmacy", 50.91751, -1.35884, sim="pharmacy"),
                rec("osm", "node/9", "Bitterne Surgery", "gp", 50.91743, -1.35871, sim="gp")])
    assert len(p) == 2 and sorted(p["category"]) == ["gp", "pharmacy"]


def test_register_name_wins_but_bare_brand_gives_way():
    p, _ = run([rec("nhs_ods", "FA2", "Sholing Pharmacy", "pharmacy", 50.9046, -1.4045, sim="pharmacy"),
                rec("osm", "node/10", "Day Lewis Pharmacy", "pharmacy", 50.90462, -1.40452, sim="pharmacy")])
    assert len(p) == 1 and p.iloc[0]["name"] == "Sholing Pharmacy" and p.iloc[0]["name_source"] == "NHS ODS"
    p, _ = run([rec("nhs_ods", "FA3", "Well", "pharmacy", 50.9046, -1.4045, sim="pharmacy"),
                rec("osm", "node/11", "Well Pharmacy", "pharmacy", 50.90462, -1.40452, sim="pharmacy")])
    assert p.iloc[0]["name"] == "Well Pharmacy"
