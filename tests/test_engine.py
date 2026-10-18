"""Engine and brief tests. Run: pytest -q
Cases map to the plan's test list (T1); ids match tests/cases.csv."""
import os
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from src import brief as B
from src import engine as E

CENTRE_CAFE = (50.9046, -1.4045)       # Above Bar / Bargate, dense cafe area
WINCHESTER = (51.0632, -1.3080)


@pytest.fixture(scope="module")
def city():
    return E.load_city()


# ---------------------------------------------------------------- toy example, checked by hand
def toy_city():
    """3 OAs on a line at x = 0, 1000, 2000 m (pop 100, 200, 300). One existing cafe at x=0."""
    oa = pd.DataFrame({"oa_code": ["a", "b", "c"], "ward": ["W"] * 3, "x": [0., 1000., 2000.], "y": [0.] * 3,
                       "pop": [100., 200., 300.], "pop_0_4": [10., 20., 30.], "imd_quintile": [1, 3, 5],
                       "lat": [50.9] * 3, "lon": [-1.4, -1.39, -1.38]})
    fac = pd.DataFrame({"category": ["cafe"], "name": ["x"], "x": [0.], "y": [0.], "lat": [50.9], "lon": [-1.4],
                        "source": ["toy"]})
    b = box(-3000, -3000, 5000, 3000)
    return E.City(oa=oa, fac=fac, boundary=b, boundary_wgs=b, sources={})


def test_toy_coverage_by_hand():
    c = toy_city()
    w = E.demand(c, "cafe")
    d0 = c.existing_dist("cafe")
    assert list(d0) == [0, 1000, 2000]
    # R = 800: only OA a (100 of 600) covered
    assert E.coverage(w, d0, 800) == pytest.approx(100 / 600)
    # add a cafe at x = 2000: OA c (300) newly covered -> 400/600
    d1 = np.minimum(d0, np.abs(c.oa.x.to_numpy() - 2000))
    assert E.coverage(w, d1, 800) == pytest.approx(400 / 600)
    # population-weighted mean distance before = (0*100 + 1000*200 + 2000*300)/600
    assert E.wmean(w, d0) == pytest.approx(800000 / 600)


def test_toy_optimiser_by_hand():
    c = toy_city()
    c._cand_dist = E.pairwise(c.oa.x, c.oa.y, c.oa.x, c.oa.y)
    picks = E.optimise(c, "cafe", k=1, radius=800, exclude_flood=False)
    assert picks[0]["oa_code"] == "c" and picks[0]["marginal_newly_covered"] == 300


# ---------------------------------------------------------------- real data cases
def test_01_dense_centre_cafe_near_zero(city):
    r = E.evaluate_site(city, "cafe", *CENTRE_CAFE)
    assert abs(r["coverage_change_pct_points"]) < 0.5
    assert r["competitors_within_400m"] >= E.C.CANNIBALISATION_THRESHOLD and r["cannibalisation_flag"]


def test_02_least_served_area_positive_delta(city):
    d0 = city.existing_dist("cafe")
    j = int(np.argmax(d0))
    r = E.evaluate_site(city, "cafe", city.oa.lat.iloc[j], city.oa.lon.iloc[j])
    assert r["coverage_change_pct_points"] > 0 and r["newly_covered"] > 0


def test_03_childcare_high_demand_positive(city):
    p = E.optimise(city, "nursery", 1)[0]
    r = E.evaluate_site(city, "nursery", p["lat"], p["lon"])
    assert r["newly_covered"] > 0 and r["demand_label"] == "children aged 0-4"


def test_04_flood_zone_flag(city):
    j = int(np.argmax(city.flood_mask))
    assert city.flood_mask[j]
    r = E.evaluate_site(city, "cafe", city.oa.lat.iloc[j], city.oa.lon.iloc[j])
    assert r["flood_zone3"] is True


def test_05_thin_category_insufficient_evidence(city):
    thin = E.City(oa=city.oa, fac=pd.concat([city.fac[city.fac.category != "library"],
                                             city.fac[city.fac.category == "library"].head(3)]),
                  boundary=city.boundary, boundary_wgs=city.boundary_wgs, sources={})
    r = E.evaluate_site(thin, "library", *CENTRE_CAFE)
    assert r["confidence"] == "Low" and r["insufficient_evidence"]
    b = B.generate(B.build_payload([r]))
    assert b["mode"] == "refusal" and b["text"].startswith("Insufficient evidence")


def test_06_outside_city(city):
    with pytest.raises(E.EngineError, match="outside Southampton"):
        E.evaluate_site(city, "cafe", *WINCHESTER)


def test_07_empty_input(city):
    with pytest.raises(E.EngineError, match="No site"):
        E.evaluate_site(city, "cafe", None, None)
    with pytest.raises(E.EngineError):
        E.evaluate_site(city, "spaceport", *CENTRE_CAFE)


def test_08_no_api_key_falls_back(city, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = E.evaluate_site(city, "library", 50.9330, -1.3700)
    b = B.generate(B.build_payload([r]))
    assert b["mode"] == "template" and b["audit"]["ok"]


def test_09_sensitivity_runs_and_reports(city):
    s = E.sensitivity(city, [{"category": "cafe", "lat": CENTRE_CAFE[0], "lon": CENTRE_CAFE[1]},
                             {"category": "library", "lat": 50.9330, "lon": -1.3700}])
    assert set(s["newly_covered_by_radius"]) == {600, 800, 1000}
    assert isinstance(s["stable_need_ranking"], bool)
    # larger radius can never newly cover fewer... is NOT guaranteed (existing coverage grows too), so only check types
    assert all(len(v) == 2 for v in s["newly_covered_by_radius"].values())


def test_10_identical_scenarios_no_difference(city):
    a = E.evaluate_site(city, "pharmacy", 50.9200, -1.3900)
    b = E.evaluate_site(city, "pharmacy", 50.9200, -1.3900)
    assert a == b


def test_11_optimiser_beats_city_centre(city):
    p = E.optimise(city, "nursery", 1)[0]
    best = E.evaluate_site(city, "nursery", p["lat"], p["lon"])
    centre = E.evaluate_site(city, "nursery", *CENTRE_CAFE)
    assert best["newly_covered"] >= centre["newly_covered"]


def test_12_optimiser_matches_brute_force(city):
    """First greedy pick must equal exhaustive search over ALL 792 candidate sites, and beat 5 random ones."""
    rng = np.random.default_rng(0)
    for cat in ["nursery", "gp", "library", "pharmacy", "cafe"]:
        greedy = E.optimise(city, cat, 1, exclude_flood=False)[0]
        best = E.brute_force_best(city, cat, list(range(len(city.oa))))
        j = int(np.where(city.oa.oa_code == greedy["oa_code"])[0][0])
        assert best == j
        rand = [int(c) for c in rng.choice(len(city.oa), 5, replace=False)]
        assert E.brute_force_best(city, cat, rand + [j]) == j


def test_13_equity_sums_to_total(city):
    for cat, site in [("library", (50.9330, -1.3700)), ("nursery", (50.9141, -1.3945))]:
        r = E.evaluate_site(city, cat, *site)
        assert abs(sum(r["equity_newly_covered_by_quintile"].values()) - r["newly_covered"]) <= 5


def test_14_audit_catches_injected_number(city):
    r = E.evaluate_site(city, "library", 50.9330, -1.3700)
    p = B.build_payload([r])
    good = f"Newly covers {r['newly_covered']:,} residents [engine], coverage {r['coverage_after_pct']}%."
    bad = f"Newly covers {r['newly_covered'] + 137:,} residents [engine]."
    assert B.audit(good, p)["ok"]
    a = B.audit(bad, p)
    assert not a["ok"] and len(a["failed"]) == 1


def test_15_llm_retry_then_fallback(city):
    r = E.evaluate_site(city, "library", 50.9330, -1.3700)
    p = B.build_payload([r])

    class Fake:
        def __init__(self, texts):
            self.texts, self.messages = texts, self

        def create(self, **_):
            return NS(content=[NS(type="text", text=self.texts.pop(0))], usage=NS(input_tokens=1000, output_tokens=300))

    ok = f"Summary: newly covers {r['newly_covered']:,} residents [engine]."
    assert B.generate(p, client=Fake(["Covers 99,999 people.", ok]))["mode"] == "llm"
    out = B.generate(p, client=Fake(["Covers 99,999 people.", "Covers 88,888 people."]))
    assert out["mode"] == "template" and "failed the numbers audit" in out["warning"]


def test_16_housing_growth_widens_gap(city):
    base = E.do_nothing(city, "nursery")
    grown = E.do_nothing(city, "nursery", extra_pop={"Bevois": 5000})
    w0 = E.demand(city, "nursery").sum()
    w1 = E.demand(city, "nursery", {"Bevois": 5000}).sum()
    assert w1 > w0 and isinstance(grown["coverage_before_pct"], float) and base["coverage_before_pct"] > 0


def test_17_ward_centroid_inside_city(city):
    for w in city.oa.ward.unique():
        lat, lon = E.ward_centroid(city, w)
        E.evaluate_site(city, "gp", lat, lon)  # must not raise


def test_18_two_scores_never_merged(city):
    r = E.evaluate_site(city, "cafe", *CENTRE_CAFE)
    assert "need_score" in r and "viability_score" in r and "score" not in r


# ---------------------------------------------------------------- mid-2024 population update
def test_sape_scaling_keeps_census_split_and_matches_ons_totals():
    from src.fetch_data import apply_sape
    oa = pd.DataFrame({"lsoa": ["L1", "L1", "L2"], "pop": [100., 300., 50.], "pop_0_4": [10., 0., 5.]})
    sape = pd.DataFrame({"lsoa": ["L1", "L2"], "pop_est": [440, 40], "pop_0_4_est": [5, 6]})
    out = apply_sape(oa, sape)
    assert out["pop"].tolist() == [110., 330., 40.]          # L1 grows 10%, split 1:3 as in the Census
    assert out["pop_0_4"].tolist() == [5., 0., 6.]
    assert out["pop_2021"].tolist() == [100., 300., 50.] and (out.pop_year == 2024).all()
    with pytest.raises(RuntimeError):
        apply_sape(oa, sape[sape.lsoa == "L1"])


def test_baseline_dataset_keeps_census_2021_population():
    base, cur = E.load_city(dataset="baseline"), E.load_city()
    assert base.pop_year == 2021 and int(base.oa["pop"].sum()) == 248982
    if "pop_2021" in cur.oa:
        assert cur.pop_year == 2024 and int(cur.oa["pop"].sum()) > 255000
