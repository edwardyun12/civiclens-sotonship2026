"""Classify a business idea with the local LLM, for the business simulator.

The model is given the idea plus the sectors and detailed business types that actually exist in the places data,
and must answer in JSON. Everything it returns is checked against those lists, so it can only pick real types; it
never produces numbers. The simulator's own model (frontend/src/simulator/opportunity.js) does all the scoring.
"""

from __future__ import annotations

import json
import re

from rag.config import CHAT_MODEL
from rag.ollama import request

AGE_KEYS = ["0_4", "5_15", "16_24", "25_44", "45_64", "65"]
PASSING = {"high", "medium", "low"}
# words too general to identify a competitor by name
GENERIC = {"restaurant", "restaurants", "shop", "shops", "store", "food", "kitchen", "cafe", "café", "ltd", "limited",
           "the", "and", "southampton", "takeaway", "services", "service", "company", "uk", "house", "bar", "co",
           "care", "club", "style", "clean", "learn", "program", "tech", "best", "new", "city", "group", "studio",
           "centre", "center", "rice", "local", "family", "home", "express", "plus", "world", "star", "royal"}
VAGUE = re.compile(r"not known|no detail", re.IGNORECASE)

PROMPT = """You help someone plan a new business in Southampton, UK. Classify their idea for a market analysis.

Business idea: "{idea}"

Sectors (pick exactly one): {sectors}

Detailed business types that exist in our data, as "type | category | count":
{types}

Customer age groups: 0_4, 5_15, 16_24, 25_44, 45_64, 65

Reply with JSON only, in this exact shape:
{{
  "business": "short clean name of the business, e.g. Thai restaurant",
  "sector": "one sector from the list",
  "niche": "what makes it specific, e.g. Thai cuisine, sit-down dining",
  "direct_types": ["types from the list that are the SAME niche (true like-for-like competitors); [] if none fit"],
  "similar_types": ["types from the list that are the same kind of business but a different niche, e.g. for a Japanese restaurant: Chinese, Thai or Korean restaurants; at most 8; [] if none"],
  "related_types": ["other types from the list in the same sector that compete for the same customers or spending, at most 6"],
  "name_keywords": ["lowercase words specific to this niche that appear in competitors' names, e.g. thai, siam, bangkok; at most 6"],
  "customers": ["age groups who are the main customers"],
  "passing_trade": "high, medium or low: how much the business depends on people walking past",
  "reasoning": "one or two sentences on how you classified it",
  "setup_tips": ["up to 3 short practical points to check before opening this kind of business in England"]
}}

Rules:
- Only use type names exactly as written in the list. Do not invent statistics or numbers.
- Direct competitors must be the same niche: for a Thai restaurant a "Thai" type is direct, but a café, bakery or
  restaurant with unknown cuisine is only related. If no listed type is the same niche, direct_types is [].
- Similar types are other niches of the same kind (other cuisines for a restaurant, other sports for a gym), never the same niche.
- Related and similar types must be in the same sector as the business (a pharmacy is never related to a restaurant).
- Name keywords must be specific (thai, sushi, barber, yoga), not generic words like care, club, food, style."""


def _clean_list(values, allowed: dict[str, str] | None = None, limit: int = 6) -> list[str]:
    out: list[str] = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, str):
            continue
        key = value.strip().lower()
        item = allowed.get(key) if allowed is not None else value.strip()
        if item and item not in out:
            out.append(item)
        if len(out) == limit:
            break
    return out


def classify_business(idea: str, types: list[dict], sectors: list[str]) -> dict:
    """Return the validated classification. Raises RuntimeError if the model is unavailable or replies badly."""
    shown = sorted(types, key=lambda t: -int(t.get("n", 0)))[:180]
    type_lines = "\n".join(f"{t['label']} | {t.get('cat', '')} | {t.get('n', 0)}" for t in shown)
    prompt = PROMPT.format(idea=idea.strip()[:200], sectors=", ".join(sectors), types=type_lines)
    reply = request("/api/chat", {
        "model": CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json",
        "think": False,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 550},
    })
    text = reply.get("message", {}).get("content", "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("The model did not return valid JSON.") from exc

    type_names = {t["label"].lower(): t["label"] for t in types}
    sector_names = {s.lower(): s for s in sectors}
    sector = sector_names.get(str(data.get("sector", "")).strip().lower())
    grp = {t["label"]: t.get("grp") for t in types}
    # direct = same niche only (never a vague "cuisine not known" type); related = same sector as the business
    picked = _clean_list(data.get("direct_types"), type_names, 12)
    direct = [t for t in picked if not VAGUE.search(t) and (not sector or grp.get(t) == sector)][:6]
    # similar = a different niche of the same kind (other cuisines); it shows demand for this kind of business
    similar = [t for t in _clean_list(data.get("similar_types"), type_names, 12)
               if t not in direct and not VAGUE.search(t) and (not sector or grp.get(t) == sector)][:8]
    related = [t for t in _clean_list(data.get("related_types"), type_names, 12) + picked
               if t not in direct and t not in similar and (not sector or grp.get(t) == sector)]
    related = list(dict.fromkeys(related))[:6]
    keywords = []
    for word in _clean_list(data.get("name_keywords"), None, 12):
        for w in re.findall(r"[a-z]{3,}", word.lower()):
            if w not in GENERIC and w not in keywords:
                keywords.append(w)
    if not sector and (direct or similar or related):  # fall back to the sector of the chosen types
        first = next(t for t in types if t["label"] in (direct or similar or related))
        sector = first.get("grp")
    customers = [k for k in AGE_KEYS if k in (data.get("customers") or [])] or AGE_KEYS
    passing = str(data.get("passing_trade", "")).strip().lower()
    return {
        "business": str(data.get("business") or idea).strip()[:80],
        "sector": sector,
        "niche": str(data.get("niche") or "").strip()[:160],
        "direct_types": direct,
        "similar_types": similar,
        "related_types": related,
        "name_keywords": keywords[:6],
        "customers": customers,
        "passing_trade": passing if passing in PASSING else "medium",
        "reasoning": str(data.get("reasoning") or "").strip()[:400],
        "setup_tips": [str(t).strip()[:200] for t in (data.get("setup_tips") or []) if isinstance(t, str)][:3],
        "model": CHAT_MODEL,
    }
