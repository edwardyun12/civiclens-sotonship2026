"""The LLM business classifier only returns types, sectors and age groups that exist in the data (no Ollama needed)."""
import json

from rag import classify as K

TYPES = [{"label": "Café", "cat": "restaurant_cafe", "grp": "Food and drink", "n": 35},
         {"label": "Restaurant (cuisine not known)", "cat": "restaurant_cafe", "grp": "Food and drink", "n": 40},
         {"label": "Chinese", "cat": "restaurant_cafe", "grp": "Food and drink", "n": 12},
         {"label": "Pharmacy", "cat": "pharmacy", "grp": "Health", "n": 42}]
SECTORS = ["Food and drink", "Health"]


def fake(reply):
    return lambda path, payload: {"message": {"content": json.dumps(reply)}}


def test_classifier_keeps_only_real_types_and_same_sector(monkeypatch):
    monkeypatch.setattr(K, "request", fake({
        "business": "Thai restaurant", "sector": "food and drink", "niche": "Thai cuisine",
        "direct_types": ["Restaurant (cuisine not known)", "Thai", "café"], "related_types": ["Pharmacy", "Made up type"], "similar_types": ["Chinese", "Pharmacy", "Restaurant (cuisine not known)"],
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
    monkeypatch.setattr(K, "request", lambda path, payload: {"message": {"content": "not json"}})
    try:
        K.classify_business("x shop", TYPES, SECTORS)
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError")
