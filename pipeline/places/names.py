"""Names, postcodes and place types: normalising names, name similarity, display names, and mapping each
source's own type codes (FSA, OSM) onto our categories."""
from __future__ import annotations

import difflib
import re


STOP = {"the", "ltd", "limited", "plc", "llp", "co", "and", "of", "uk", "southampton", "t/a", "ta"}


def norm_name(s) -> str:
    s = str(s or "").lower().replace("&", " and ").replace("'", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in STOP)


GENERIC = {"surgery", "practice", "pharmacy", "chemist", "chemists", "gp", "health", "centre", "center", "medical",
           "doctors", "group", "partnership", "clinic", "cafe", "coffee", "shop", "nursery", "nurseries", "day",
           "pre", "school", "preschool", "library", "store"}


def name_sim(a, b, same_type: bool = True) -> float:
    """0-1. Generic words ("surgery", "pharmacy"...) are ignored only when both records are the same type of
    business, so "Bitterne Pharmacy" never matches "Bitterne Surgery"."""
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return 0.0
    if a == b or (len(a) > 4 and a in b) or (len(b) > 4 and b in a):
        return 1.0 if same_type or a == b else 0.6
    ca, cb = set(a.split()) - GENERIC, set(b.split()) - GENERIC
    if same_type and ca and ca == cb:  # same distinctive words, e.g. "Portswood Solent Surgery" / "Solent GP Surgery Portswood"
        return 0.9
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / len(ta | tb)
    return max(jac, difflib.SequenceMatcher(None, a, b).ratio())


def norm_postcode(p) -> str:
    p = re.sub(r"\s+", "", str(p or "").upper())
    return f"{p[:-3]} {p[-3:]}" if len(p) >= 5 else ""


# One shared taxonomy. `sim` = the simulator category the engine uses (None = context only).
TYPE_MAP = {
    # (source, raw type) -> (category, sim)
    ("fsa", "Restaurant/Cafe/Canteen"): ("restaurant_cafe", None),
    ("fsa", "Takeaway/sandwich shop"): ("takeaway", None),
    ("fsa", "Pub/bar/nightclub"): ("pub_bar", None),
    ("fsa", "Retailers - supermarkets/hypermarkets"): ("supermarket", None),
    ("fsa", "Retailers - other"): ("shop_food", None),
    ("fsa", "Hotel/bed & breakfast/guest house"): ("hotel", None),
    ("fsa", "School/college/university"): ("education", None),
    ("fsa", "Hospitals/Childcare/Caring Premises"): ("care_childcare_health", None),
    ("fsa", "Mobile caterer"): ("mobile_caterer", None),
    ("fsa", "Other catering premises"): ("other_catering", None),
    ("fsa", "Manufacturers/packers"): ("food_manufacturer", None),
    ("fsa", "Distributors/Transporters"): ("food_distributor", None),
    ("fsa", "Importers/Exporters"): ("food_distributor", None),
    ("fsa", "Farmers/growers"): ("food_producer", None),
}
OSM_MAP = {
    "amenity=cafe": ("restaurant_cafe", "cafe"), "amenity=restaurant": ("restaurant_cafe", None),
    "amenity=fast_food": ("takeaway", None), "amenity=pub": ("pub_bar", None), "amenity=bar": ("pub_bar", None),
    "amenity=nightclub": ("pub_bar", None), "amenity=kindergarten": ("nursery", "nursery"),
    "amenity=childcare": ("nursery", "nursery"), "amenity=doctors": ("gp", "gp"), "healthcare=doctor": ("gp", "gp"),
    "amenity=pharmacy": ("pharmacy", "pharmacy"), "healthcare=pharmacy": ("pharmacy", "pharmacy"),
    "amenity=dentist": ("dentist", None), "amenity=library": ("library", "library"),
    "amenity=school": ("education", None), "amenity=college": ("education", None),
    "amenity=university": ("education", None), "amenity=coworking_space": ("coworking", None),
    "office=coworking": ("coworking", None), "shop=supermarket": ("supermarket", None),
    "shop=convenience": ("shop_food", None), "shop=bakery": ("shop_food", None), "shop=butcher": ("shop_food", None),
    "amenity=community_centre": ("community", None), "amenity=place_of_worship": ("community", None),
    "leisure=sports_centre": ("leisure", None), "leisure=fitness_centre": ("leisure", None),
    "tourism=hotel": ("hotel", None), "tourism=guest_house": ("hotel", None), "amenity=bank": ("finance", None),
    "amenity=post_office": ("post_office", None), "amenity=social_facility": ("care_childcare_health", None),
    "healthcare=hospital": ("hospital", None), "amenity=hospital": ("hospital", None),
}
# Which categories can plausibly be the same place (for TYPE_CONFLICT)
COMPATIBLE = [
    {"restaurant_cafe", "takeaway", "pub_bar", "other_catering", "hotel", "shop_food", "supermarket"},
    {"nursery", "care_childcare_health", "education"},
    {"gp", "care_childcare_health", "hospital", "pharmacy"},
    {"pharmacy", "shop_food", "supermarket"},
    {"library", "community", "education", "other_catering"},
    {"leisure", "other_catering", "restaurant_cafe", "education"},
]


def compatible(cats: set[str]) -> bool:
    cats = {c for c in cats if c and c != "other"}
    return len(cats) <= 1 or any(cats <= g for g in COMPATIBLE)


def osm_type(t: dict) -> tuple[str, str, str | None]:
    for k in ("amenity", "healthcare", "shop", "office", "leisure", "tourism", "craft"):
        if k in t:
            kv = f"{k}={t[k]}"
            cat, sim = OSM_MAP.get(kv, (f"shop_other" if k == "shop" else "other", None))
            return kv, cat, sim
    return "", "other", None


_KEEP_UPPER = {"UK", "GP", "NHS", "IT", "TV", "BBC", "BMW", "PC", "CIC", "LLP", "PLC", "HR", "UKCC", "SO"}


def display_name(name: str, source: str) -> str:
    """Companies House names are in capitals; show them in title case (keeping known acronyms)."""
    name = str(name or "").strip()
    if source != "ch" or not name.isupper():
        return name
    words = []
    for w in name.split():
        core = re.sub(r"[^A-Z]", "", w)
        keep = core in _KEEP_UPPER or (len(core) <= 3 and "." in w)
        words.append(w if keep else re.sub(r"[a-z]", lambda m: m.group().upper(), w.lower(), count=1))
    return " ".join(words).replace("Limited", "Ltd").replace("Ltd.", "Ltd")
