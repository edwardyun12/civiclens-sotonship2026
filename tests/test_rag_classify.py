"""The LLM business classifier only returns types, sectors and age groups that exist in the data (no model needed)."""
import json

from rag import classify as K
from rag.generator import build_retrieval_query
from rag.templates import answer_template

TYPES = [{"label": "Café", "cat": "restaurant_cafe", "grp": "Food and drink", "n": 35},
         {"label": "Restaurant (cuisine not known)", "cat": "restaurant_cafe", "grp": "Food and drink", "n": 40},
         {"label": "Chinese", "cat": "restaurant_cafe", "grp": "Food and drink", "n": 12},
         {"label": "Pharmacy", "cat": "pharmacy", "grp": "Health", "n": 42}]
SECTORS = ["Food and drink", "Health"]


def fake(reply):
    return lambda prompt, *a, **k: json.dumps(reply)


def test_classifier_keeps_only_real_types_and_same_sector(monkeypatch):
    monkeypatch.setattr(K, "complete", fake({
        "business": "Thai restaurant", "sector": "food and drink", "niche": "Thai cuisine",
        "direct_types": ["Restaurant (cuisine not known)", "Thai", "café"], "related_types": ["Pharmacy", "Made up type"], "similar_types": ["Chinese | restaurant_cafe | 12", "Pharmacy", "Restaurant (cuisine not known)"],
        "name_keywords": ["Thai", "food", "Siam Kitchen"], "customers": ["25_44", "99"], "passing_trade": "very high",
        "reasoning": "ok", "setup_tips": ["Register as a food business"]}))
    out = K.classify_business("thai restaurant", TYPES, SECTORS)
    assert out["sector"] == "Food and drink"
    assert out["direct_types"] == ["Café"]                                   # vague and invented types dropped
    assert out["similar_types"] == ["Chinese"]                               # other cuisines; not vague, same sector
    assert out["related_types"] == ["Restaurant (cuisine not known)"]        # pharmacy is another sector
    assert out["name_keywords"] == ["thai", "siam"]                          # generic words dropped
    assert out["customers"] == ["25_44"] and out["passing_trade"] == "medium"


def test_classifier_rejects_bad_json(monkeypatch):
    monkeypatch.setattr(K, "complete", lambda prompt, *a, **k: "not json")
    try:
        K.classify_business("x shop", TYPES, SECTORS)
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")


def test_types_win_over_a_wrong_sector_and_direct_stays_narrow(monkeypatch):
    types = [{"label": "Barber", "cat": "hair_beauty", "grp": "Retail", "n": 38},
             {"label": "Japanese", "cat": "restaurant_cafe", "grp": "Food and drink", "n": 12},
             {"label": "Noodle bar", "cat": "restaurant_cafe", "grp": "Food and drink", "n": 6},
             {"label": "Korean", "cat": "restaurant_cafe", "grp": "Food and drink", "n": 5}]
    monkeypatch.setattr(K, "complete", fake({"business": "Barber shop", "sector": "Leisure and hospitality",
                                            "direct_types": ["Barber"], "customers": ["25_44"]}))
    out = K.classify_business("barber shop", types, ["Retail", "Food and drink", "Leisure and hospitality"])
    assert out["direct_types"] == ["Barber"] and out["sector"] == "Retail"   # not dropped for the sector label
    monkeypatch.setattr(K, "complete", fake({"business": "Sushi bar", "sector": "Food and drink",
                                            "direct_types": ["Japanese", "Noodle bar", "Korean"]}))
    out = K.classify_business("sushi bar", types, ["Retail", "Food and drink"])
    assert out["direct_types"] == ["Japanese", "Noodle bar"] and out["similar_types"] == ["Korean"]


def test_explicit_question_does_not_mix_in_previous_topic():
    history = [{"role": "user", "content": "Where is commercial vacancy highest?"}]
    question = "Compare Shirley and Portswood."
    assert build_retrieval_query(question, history) == question


def test_referential_follow_up_uses_previous_question():
    history = [{"role": "user", "content": "Compare Shirley and Portswood."}]
    query = build_retrieval_query("Which one has more shops?", history)
    assert "Compare Shirley and Portswood." in query
    assert "Which one has more shops?" in query


def test_builtin_place_question_is_deterministic():
    context = "Mapped trading places by ward: Bargate 1,060, Bevois 386, Millbrook 304."
    answer, sources = answer_template("Which areas have the most businesses?", context)
    assert "Bargate" in answer and "1,060" in answer and not sources


def test_builtin_competitor_question_uses_both_distances():
    context = "14,683 target customers; 7 direct competitors within 800 m (2 within 400 m); 10 related businesses."
    answer, sources = answer_template("How many competitors are near this site?", context)
    assert "7 direct competitors within 800 m" in answer
    assert "2 within 400 m" in answer
    assert not sources


def test_comparison_uses_latest_vacancy_year_and_stable_count_metric():
    context = (
        "Mapped trading places by ward: Portswood 255, Shirley 198.\n"
        "Popular-map metric: most overrepresented sector relative to its city-wide share.\n"
        "Largest sector by mapped-place count per area: Portswood: Food and drink; Shirley: Retail."
    )
    answer, sources = answer_template("Compare Shirley and Portswood.", context)
    assert "10.57%" in answer and "4.84%" in answer and "2024" in answer
    assert "Food and drink" in answer and "Retail" in answer
    assert sources[0]["url"].endswith("#page=6")
