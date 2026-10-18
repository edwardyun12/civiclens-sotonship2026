"""Detailed business types for the advanced filter (cuisine, shop specialty, SIC-based subtype), industry
groups, and the SIC code -> category table."""
from __future__ import annotations

import json
import re

import pandas as pd


SIC_SUBTYPE = {
    "56101": "Restaurant (licensed)", "56102": "Restaurant or café", "56103": "Takeaway", "56210": "Event catering",
    "56290": "Canteen or contract catering", "56301": "Licensed club", "56302": "Pub or bar",
    "47110": "Supermarket or convenience store", "47210": "Greengrocer", "47220": "Butcher", "47230": "Fishmonger",
    "47240": "Bakery or cake shop", "47250": "Off-licence", "47260": "Tobacconist or vape shop", "47290": "Other food shop",
    "47300": "Petrol station", "47410": "Computer shop", "47421": "Mobile phone shop", "47710": "Clothing shop",
    "47721": "Shoe shop", "47730": "Pharmacy", "47741": "Hearing aids", "47749": "Medical and mobility goods",
    "47750": "Cosmetics and toiletries", "47760": "Florist, garden or pet shop", "47770": "Jeweller",
    "47782": "Optician", "47910": "Online retailer",
    "86101": "Hospital", "86210": "GP practice", "86220": "Specialist medical practice", "86230": "Dental practice",
    "86900": "Other health (physio, therapy, clinic)", "75000": "Veterinary practice",
    "87100": "Nursing home", "87300": "Care home", "88100": "Home care", "88910": "Day nursery or childcare",
    "85100": "Pre-school", "85200": "Primary school", "85310": "Secondary school", "85510": "Sports or recreation tuition",
    "85520": "Arts and music tuition", "85530": "Driving school", "85590": "Tutoring or other education",
    "96010": "Laundry or dry cleaner", "96020": "Hairdresser or beauty salon", "96030": "Funeral services",
    "96040": "Spa, massage or wellbeing", "96090": "Other personal services (e.g. tattoo)",
    "93110": "Sports facility", "93130": "Gym or fitness centre", "93199": "Other sports activity",
    "93290": "Other recreation", "55100": "Hotel", "55201": "Holiday centre", "55202": "Hostel", "55209": "Holiday lets",
    "55900": "Other accommodation", "95210": "Electronics repair", "95230": "Shoe and leather repair",
    "95250": "Watch and jewellery repair", "95290": "Other repairs", "45200": "Car repair or garage",
    "45111": "Car dealer", "45320": "Car parts shop",
}
OSM_SUBTYPE = {
    "amenity=fast_food": "Fast food", "amenity=restaurant": "Restaurant", "amenity=cafe": "Café", "amenity=pub": "Pub",
    "amenity=bar": "Bar", "amenity=ice_cream": "Ice cream or dessert", "amenity=dentist": "Dental practice",
    "amenity=doctors": "GP or clinic", "amenity=pharmacy": "Pharmacy", "amenity=clinic": "Clinic",
    "amenity=veterinary": "Veterinary practice", "amenity=kindergarten": "Pre-school or nursery",
    "amenity=childcare": "Day nursery or childcare", "healthcare=dentist": "Dental practice",
    "healthcare=doctor": "GP or clinic", "healthcare=physiotherapist": "Physiotherapist", "healthcare=optometrist": "Optician",
    "healthcare=psychotherapist": "Counselling or therapy", "healthcare=podiatrist": "Podiatrist",
    "shop=hairdresser": "Hairdresser or barber", "shop=beauty": "Beauty salon", "shop=massage": "Spa, massage or wellbeing",
    "shop=tattoo": "Tattoo studio", "shop=supermarket": "Supermarket", "shop=convenience": "Convenience store",
    "shop=bakery": "Bakery or cake shop", "shop=butcher": "Butcher", "shop=optician": "Optician",
    "shop=clothes": "Clothing shop", "shop=mobile_phone": "Mobile phone shop", "shop=laundry": "Laundry or dry cleaner",
    "shop=dry_cleaning": "Laundry or dry cleaner", "leisure=fitness_centre": "Gym or fitness centre",
    "leisure=sports_centre": "Sports facility", "amenity=spa": "Spa, massage or wellbeing", "leisure=spa": "Spa, massage or wellbeing",
}
CUISINE = {  # OSM cuisine values and name keywords -> (cuisine, family); first match wins, so specific before general
    "bubble_tea": ("Bubble tea", "Café"), "bubble tea": ("Bubble tea", "Café"), "boba": ("Bubble tea", "Café"),
    "茶": ("Bubble tea", "Café"),  # Chinese "tea" in a café name: almost always a bubble tea shop in Southampton
    "korean": ("Korean", "Asian"), "bulgogi": ("Korean", "Asian"),
    "japan": ("Japanese", "Asian"), "bento": ("Japanese", "Asian"), "katsu": ("Japanese", "Asian"),
    "teriyaki": ("Japanese", "Asian"), "izakaya": ("Japanese", "Asian"), "udon": ("Japanese", "Asian"),
    "taiwan": ("Taiwanese", "Asian"), "hotpot": ("Chinese", "Asian"), "hot pot": ("Chinese", "Asian"),
    "filipino": ("Filipino", "Asian"), "indonesia": ("Indonesian", "Asian"), "mediterranean": ("Mediterranean", "Western"), "kimchi": ("Korean", "Asian"), "seoul": ("Korean", "Asian"), "bibimbap": ("Korean", "Asian"),
    "korea": ("Korean", "Asian"), "kimbap": ("Korean", "Asian"), "gimbap": ("Korean", "Asian"), "k bap": ("Korean", "Asian"),
    "yakitori": ("Japanese", "Asian"), "tempura": ("Japanese", "Asian"), "gyoza": ("Japanese", "Asian"), "onigiri": ("Japanese", "Asian"),
    "vietnam": ("Vietnamese", "Asian"), "saigon": ("Vietnamese", "Asian"), "hanoi": ("Vietnamese", "Asian"), "banh mi": ("Vietnamese", "Asian"),
    "siam": ("Thai", "Asian"), "maithai": ("Thai", "Asian"), "malaysia": ("Malaysian", "Asian"),
    "china": ("Chinese", "Asian"), "peking": ("Chinese", "Asian"), "beijing": ("Chinese", "Asian"), "shanghai": ("Chinese", "Asian"),
    "lanzhou": ("Chinese", "Asian"), "chopstick": ("Chinese", "Asian"), "oriental": ("Pan-Asian", "Asian"), "asian": ("Pan-Asian", "Asian"),
    "wok": ("Chinese", "Asian"), "dragon": ("Chinese", "Asian"), "canton": ("Chinese", "Asian"), "hong kong": ("Chinese", "Asian"),
    "szechuan": ("Chinese", "Asian"), "sichuan": ("Chinese", "Asian"), "noodle": ("Noodles", "Asian"),
    "india": ("Indian", "South Asian"), "bengal": ("Indian", "South Asian"), "punjab": ("Indian", "South Asian"),
    "himalaya": ("Nepalese", "South Asian"), "nepal": ("Nepalese", "South Asian"), "bangkok": ("Thai", "Asian"),
    "tokyo": ("Japanese", "Asian"), "sakura": ("Japanese", "Asian"), "istanbul": ("Turkish", "Middle Eastern"), "japanese": ("Japanese", "Asian"), "sushi": ("Japanese", "Asian"),
    "ramen": ("Japanese", "Asian"), "chinese": ("Chinese", "Asian"), "dim sum": ("Chinese", "Asian"),
    "thai": ("Thai", "Asian"), "vietnamese": ("Vietnamese", "Asian"), "pho": ("Vietnamese", "Asian"),
    "malaysian": ("Malaysian", "Asian"), "indian": ("Indian", "South Asian"), "curry": ("Indian", "South Asian"),
    "tandoori": ("Indian", "South Asian"), "masala": ("Indian", "South Asian"), "balti": ("Indian", "South Asian"),
    "nepalese": ("Nepalese", "South Asian"), "bangladeshi": ("Bangladeshi", "South Asian"),
    "pakistani": ("Pakistani", "South Asian"), "sri lankan": ("Sri Lankan", "South Asian"),
    "turkish": ("Turkish", "Middle Eastern"), "kebab": ("Kebab", "Middle Eastern"), "lebanese": ("Lebanese", "Middle Eastern"),
    "persian": ("Persian", "Middle Eastern"), "shawarma": ("Shawarma", "Middle Eastern"), "falafel": ("Falafel", "Middle Eastern"),
    "italian": ("Italian", "Western"), "pizza": ("Pizza", "Western"), "pasta": ("Italian", "Western"),
    "british": ("British", "Western"), "fish_and_chips": ("Fish and chips", "Western"), "fish and chips": ("Fish and chips", "Western"),
    "fish bar": ("Fish and chips", "Western"), "chippy": ("Fish and chips", "Western"), "burger": ("Burgers", "Western"),
    "american": ("American", "Western"), "steak": ("Steakhouse", "Western"), "french": ("French", "Western"),
    "spanish": ("Spanish", "Western"), "tapas": ("Spanish", "Western"), "greek": ("Greek", "Western"),
    "portuguese": ("Portuguese", "Western"), "peri": ("Peri-peri chicken", "Western"), "chicken": ("Fried chicken", "Western"),
    "mexican": ("Mexican", "Latin American"), "caribbean": ("Caribbean", "Latin American"), "jamaican": ("Caribbean", "Latin American"),
    "brazilian": ("Brazilian", "Latin American"), "african": ("African", "African"), "ethiopian": ("Ethiopian", "African"),
    "coffee_shop": ("Coffee", "Café"), "coffee": ("Coffee", "Café"), "espresso": ("Coffee", "Café"),
    "tea": ("Tea room", "Café"),
    "cake": ("Bakery and cakes", "Café"), "bakery": ("Bakery and cakes", "Café"), "dessert": ("Desserts", "Café"),
    "ice_cream": ("Desserts", "Café"), "gelato": ("Desserts", "Café"), "waffle": ("Desserts", "Café"),
    "sandwich": ("Sandwiches", "Café"), "breakfast": ("Breakfast", "Café"), "vegan": ("Vegan", "Other"),
}
CHAIN_CUISINE = {  # well-known brands whose names don't say the cuisine
    "costa": "coffee", "starbucks": "coffee", "caffe nero": "coffee", "caffè nero": "coffee", "pret": "sandwich",
    "greggs": "bakery", "subway": "sandwich", "mcdonald": "burger", "burger king": "burger", "five guys": "burger",
    "kfc": "chicken", "popeyes": "chicken", "nando": "peri", "domino": "pizza", "papa john": "pizza", "pizza hut": "pizza",
    "wagamama": "japanese", "itsu": "japanese", "yo sushi": "japanese", "wasabi": "japanese", "bubbleology": "bubble_tea",
    "chatime": "bubble_tea", "gong cha": "bubble_tea", "mooboo": "bubble_tea", "tiger sugar": "bubble_tea",
    "yi fang": "bubble_tea", "coco fresh": "bubble_tea", "ding tea": "bubble_tea", "sushi daily": "japanese", "kokoro": "japanese",
    "taco bell": "mexican", "chipotle": "mexican", "wildwood": "italian", "zizzi": "italian", "ask italian": "italian",
    "prezzo": "italian", "bella italia": "italian", "pizza express": "pizza", "turtle bay": "caribbean", "tortilla": "mexican",
}
NAME_SUBTYPE = [  # (keywords in the name, subtype) for non-food places
    (("dental", "dentist", "orthodont", "smile"), "Dental practice"), (("surgery", "medical centre", "health centre", "gp "), "GP or clinic"),
    (("physio", "chiropract", "osteopath"), "Physiotherapist"), (("optician", "optometr", "eye care", "specsavers", "vision express"), "Optician"),
    (("spa", "massage", "wellness", "wellbeing", "sauna"), "Spa, massage or wellbeing"), (("nail",), "Nail salon"),
    (("barber",), "Hairdresser or barber"), (("hair", "hairdress", "salon", "stylist"), "Hairdresser or barber"),
    (("beauty", "lash", "lashes", "brow", "aesthetic", "tanning"), "Beauty salon"), (("tattoo", "ink "), "Tattoo studio"),
    (("gym", "fitness", "crossfit", "pilates", "yoga"), "Gym or fitness centre"), (("nursery", "pre-school", "preschool", "playgroup"), "Day nursery or childcare"),
    (("vet", "veterinary"), "Veterinary practice"), (("laundr", "dry clean", "launderette"), "Laundry or dry cleaner"),
]
FOOD_CATS = {"restaurant_cafe", "takeaway", "pub_bar", "other_catering", "mobile_caterer"}


def has_word(text: str, key: str) -> bool:
    """Key found at the start of a word in text. Short keys (4 letters or fewer) must be the whole word or its
    plural: 'pho' is not in 'Phoenix', 'spa' not in 'Sparky', 'tea' not in 'Team'. Longer keys may start a word:
    'india' in 'Indian', 'dental' in 'Dentalcare' but not 'Incidental'."""
    k = key.strip().replace("_", " ")
    tail = r"s?(?![a-z])" if len(k) <= 4 else ""
    return re.search(r"(?<![a-z])" + re.escape(k) + tail, text) is not None


def cuisine_from(text: str):
    t = " " + str(text or "").lower().replace(";", " ").replace("-", " ") + " "
    for brand, key in CHAIN_CUISINE.items():
        if has_word(t, brand):
            return CUISINE[key]
    for key, val in CUISINE.items():
        if has_word(t, key):
            return val
    return None


# One clear label per place for the advanced search ("Bubble tea", "Korean", "Barber", "Asian supermarket"),
# built from the detailed type, cuisine and, failing those, words in the name or the company's SIC division.
CUISINE_SPECIALTY = {"Coffee": "Coffee shop", "Bakery and cakes": "Bakery or cake shop", "Desserts": "Desserts or ice cream",
                     "Sandwiches": "Sandwich shop", "Breakfast": "Breakfast or brunch", "Noodles": "Noodle bar"}
SHOP_SPECIALTY = [  # (words in the name, label) for shops; checked before the generic detailed type
    (("oriental", "asian supermarket", "asian food", "asian grocer", "chinese supermarket", "korean", "japanese",
      "oseyo", "wing yip", "hiep hoa"), "Asian supermarket"),
    (("polski", "polish", "polskie", "eastern european", "baltic"), "Polish or Eastern European shop"),
    (("african", "caribbean", "afro"), "African or Caribbean shop"), (("halal",), "Halal food shop"),
    (("vape", "vaping"), "Vape shop"),
]


def specialty_of(p) -> tuple[str, str]:
    """(label, where it came from) for one place row. 'name' means guessed from words in the name."""
    cat, sub, cui = (str(p.get(k) or "") if pd.notna(p.get(k)) else "" for k in ("category", "subtype", "cuisine"))
    text = " ".join(str(p.get(k) or "") for k in ("name", "names_seen", "brand") if pd.notna(p.get(k)))
    low = " " + text.lower() + " "
    sub_from = str(p.get("subtype_from") or "") if pd.notna(p.get("subtype_from")) else ""
    if cat in FOOD_CATS:
        guess = cuisine_from(text)
        if cui == "Tea and bubble tea":  # older builds lumped these together
            cui = guess[0] if guess and guess[0] in ("Bubble tea", "Tea room") else "Tea room"
        if cui:
            return CUISINE_SPECIALTY.get(cui, cui), "name" if p.get("cuisine_from") == "name" else "map tag"
        if guess:
            return CUISINE_SPECIALTY.get(guess[0], guess[0]), "name"
        if cat == "pub_bar":
            return (sub if sub in ("Pub", "Bar", "Licensed club") else "Pub or bar"), sub_from or "business type"
        if cat == "restaurant_cafe":
            if "caf" in sub.lower() or any(has_word(low, w) for w in ("cafe", "café", "caffe", "caff")):
                return "Café", sub_from or "name"
            return "Restaurant (cuisine not known)", sub_from or "business type"
        if cat == "takeaway":
            return "Takeaway (food not known)", sub_from or "business type"
    if cat in ("shop_food", "shop_other", "supermarket"):
        for words, label in SHOP_SPECIALTY:
            if any(has_word(low, w) for w in words):
                return label, "name"
    if sub.startswith("Hairdresser") and has_word(low, "barber"):
        return "Barber", "name"
    if sub.startswith("Hairdresser") and has_word(low, "nail"):
        return "Nail salon", "name"
    if sub_from == "name":  # re-check guesses from older builds, which matched parts of words ("Sparky" -> spa)
        sub = "" if cat in FOOD_CATS else next((s for words, s in NAME_SUBTYPE if any(has_word(low, w) for w in words)), "")
    if sub:
        return sub, sub_from
    ind = str(p.get("industry") or "") if pd.notna(p.get("industry")) else ""
    if ind:  # companies: the SIC division, e.g. "Real estate", "Computer programming and IT"
        return ind.split("; ")[0], "SIC code"
    return "", ""


def detailed_type(g: pd.DataFrame, category: str, name: str, sic: str) -> dict:
    """subtype (e.g. 'Dental practice', 'Fast food'), cuisine and cuisine family for food places, and where it came
    from: 'map tag' and 'SIC code' are recorded facts; 'name' means guessed from words in the name."""
    out = {"subtype": "", "cuisine": "", "cuisine_family": "", "subtype_from": ""}
    tags = [json.loads(e) for e in g.loc[g["source"] == "osm", "extra"]] if (g["source"] == "osm").any() else []
    for t in tags:  # 1. the map's own tags
        for k in ("healthcare", "amenity", "shop", "leisure"):
            v = t.get(k)
            if v and f"{k}={v}" in OSM_SUBTYPE and not out["subtype"]:
                out.update(subtype=OSM_SUBTYPE[f"{k}={v}"], subtype_from="map tag")
        if t.get("cuisine") and not out["cuisine"]:
            c = cuisine_from(t["cuisine"])
            if c:
                out.update(cuisine=c[0], cuisine_family=c[1])
    if not out["subtype"]:  # 2. official registers
        for _, r in g.iterrows():
            if r["source"] == "nhs_ods":
                out.update(subtype="Pharmacy" if r["category"] == "pharmacy" else "GP practice", subtype_from="register")
            elif r["source"] == "ofsted":
                out.update(subtype=f"Childcare: {r['raw_type']}" if r["raw_type"] else "Day nursery or childcare", subtype_from="register")
            elif r["source"] == "fsa" and r["raw_type"]:
                out.update(subtype=str(r["raw_type"]), subtype_from="register")
            if out["subtype"]:
                break
    if not out["subtype"] and sic:  # 3. the company's SIC code
        main = sic.split("|")[0]
        if main in SIC_SUBTYPE:
            out.update(subtype=SIC_SUBTYPE[main], subtype_from="SIC code")
    names = " ".join(g["name"].astype(str)) + " " + str(name)
    if category in FOOD_CATS and not out["cuisine"]:  # 4. words in the name (a guess, labelled as such)
        c = cuisine_from(names)
        if c:
            out.update(cuisine=c[0], cuisine_family=c[1])
            out["cuisine_from"] = "name"
    if not out["subtype"] and category not in FOOD_CATS:
        low = " " + names.lower() + " "
        for words, sub in NAME_SUBTYPE:
            if any(has_word(low, w) for w in words):
                out.update(subtype=sub, subtype_from="name")
                break
    if category in FOOD_CATS and out["cuisine_family"] in ("", None) and out["subtype"] in ("Fast food", "Takeaway"):
        out["cuisine_family"] = "Fast food (cuisine unknown)"
    return out


# SIC 2007 code prefix -> our category (longest prefix wins). Lets companies sit in the same taxonomy as places.
SIC_CATEGORY = {
    "56101": "restaurant_cafe", "56102": "restaurant_cafe", "56103": "takeaway", "5621": "other_catering",
    "5629": "other_catering", "5630": "pub_bar", "4711": "supermarket", "4719": "shop_other", "472": "shop_food",
    "47730": "pharmacy", "47": "shop_other", "88910": "nursery", "85100": "nursery", "85": "education",
    "86210": "gp", "86230": "dentist", "86": "health_other", "87": "care_childcare_health", "88": "care_childcare_health",
    "55": "hotel", "93": "leisure", "96020": "hair_beauty", "96": "personal_services", "91011": "library",
    "91": "community", "94": "community", "90": "leisure", "68": "property", "41": "construction", "42": "construction",
    "43": "construction", "62": "it_tech", "63": "it_tech", "58": "it_tech", "61": "it_tech", "64": "finance",
    "65": "finance", "66": "finance", "69": "professional", "70": "professional", "71": "professional",
    "72": "professional", "73": "professional", "74": "professional", "75": "health_other", "77": "business_services",
    "78": "business_services", "79": "business_services", "80": "business_services", "81": "business_services",
    "82": "business_services", "45": "motor", "46": "wholesale", "49": "transport_logistics", "50": "transport_logistics",
    "51": "transport_logistics", "52": "transport_logistics", "53": "transport_logistics", "10": "food_manufacturer",
    "11": "food_manufacturer", "95": "personal_services", "59": "it_tech", "60": "it_tech", "84": "community",
    "99999": "dormant", "74990": "dormant",
}


for _d in range(5, 34):  # remaining manufacturing and mining divisions
    SIC_CATEGORY.setdefault(f"{_d:02d}", "manufacturing")


for _d in ("01", "02", "03", "35", "36", "37", "38", "39"):
    SIC_CATEGORY.setdefault(_d, "utilities_primary")


SIM_FROM_CATEGORY = {"nursery": "nursery", "gp": "gp", "pharmacy": "pharmacy", "library": "library"}
# Broad industry groups for sorting and reporting (one per category)
INDUSTRY_GROUP = {
    **dict.fromkeys(["restaurant_cafe", "takeaway", "pub_bar", "other_catering", "mobile_caterer"], "Food and drink"),
    **dict.fromkeys(["supermarket", "shop_food", "shop_other"], "Retail"),
    **dict.fromkeys(["gp", "dentist", "pharmacy", "hospital", "health_other"], "Health"),
    **dict.fromkeys(["nursery", "education", "care_childcare_health"], "Childcare, education and care"),
    **dict.fromkeys(["library", "community"], "Community and culture"),
    **dict.fromkeys(["hotel", "leisure"], "Leisure and hospitality"),
    **dict.fromkeys(["hair_beauty", "personal_services"], "Personal services"),
    **dict.fromkeys(["professional", "finance", "property", "it_tech", "business_services", "coworking", "wholesale"],
                    "Business and professional"),
    **dict.fromkeys(["construction", "manufacturing", "food_manufacturer", "food_distributor", "food_producer",
                     "transport_logistics", "motor", "utilities_primary"], "Industry, construction and transport"),
    **dict.fromkeys(["finance_bank", "post_office"], "Business and professional"),
    "dormant": "Dormant or non-trading", "other": "Other",
}
CUSTOMER_FACING_GROUPS = {"Food and drink", "Retail", "Health", "Childcare, education and care", "Community and culture",
                          "Leisure and hospitality", "Personal services"}


def sic_category(codes: list[str]) -> str:
    for code in codes:  # the first listed SIC code is the main activity
        for n in (5, 4, 3, 2):
            if code[:n] in SIC_CATEGORY:
                return SIC_CATEGORY[code[:n]]
    return "other"
