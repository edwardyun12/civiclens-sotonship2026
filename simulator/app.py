"""Southampton planning scenario simulator (Streamlit). Run:  python run.py app"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulator import brief as B  # noqa: E402
from simulator import config as C  # noqa: E402
from simulator import engine as E  # noqa: E402
from simulator.paths import CACHE, PROC  # noqa: E402

DEMO = CACHE / "demo"
PC_CACHE = CACHE / "postcodes.json"
CITY_CENTRE = (50.9097, -1.4044)
RESIDENTS_PER_HOME = 2.3  # ASSUMPTION: rough average household size, shown in the UI

st.set_page_config(page_title="Southampton Planning Simulator", page_icon="🗺️", layout="wide")


# ------------------------------------------------------------------ data
@st.cache_resource(show_spinner="Loading Southampton data...")
def city(dataset: str) -> E.City:
    c = E.load_city(dataset=dataset)
    _ = c.cand_dist  # build the distance cache once
    return c


DATASET_LABELS = {"places": "Places database (merged registers)", "baseline": "17 Oct baseline (published test numbers)"}
dataset = st.sidebar.radio("Existing sites from", list(DATASET_LABELS), format_func=DATASET_LABELS.get)
CITY = city(dataset)
if CITY.dataset != dataset:
    st.sidebar.warning("No places database built yet (run python run.py places); using the 17 Oct baseline.")
st.sidebar.caption("Sites: " + ", ".join(f"{len(CITY.facilities(k))} {v['label'].lower()}"
                                         for k, v in C.CATEGORIES.items()))
CATS = {k: v["label"] for k, v in C.CATEGORIES.items() if len(CITY.facilities(k)) >= 1}
WARDS = sorted(CITY.oa.ward.unique())


# ------------------------------------------------------------------ helpers
def postcode_lookup(pc: str) -> tuple[float, float]:
    pc = pc.strip().upper()
    if not pc:
        raise E.EngineError("Enter a postcode.")
    cache = json.loads(PC_CACHE.read_text()) if PC_CACHE.exists() else {}
    key = pc.replace(" ", "")
    try:
        r = requests.get(f"https://api.postcodes.io/postcodes/{key}", timeout=8)
        if r.status_code == 404:
            raise E.EngineError(f"'{pc}' is not a valid UK postcode.")
        r.raise_for_status()
        res = r.json()["result"]
        lat, lon = res["latitude"], res["longitude"]
        if lat is None:
            raise E.EngineError(f"'{pc}' has no location on record.")
        cache[key] = [lat, lon]
        PC_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PC_CACHE.write_text(json.dumps(cache))
        return lat, lon
    except E.EngineError:
        raise
    except Exception:
        if key in cache:
            return tuple(cache[key])
        raise E.EngineError("Postcode lookup is offline. Click the map or pick a ward instead.")


def cached_brief(payload: dict, demo: bool) -> dict:
    """Live brief, cached to disk on success. In demo mode, serve the cache (clearly labelled)."""
    key = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    f = DEMO / f"{key}.json"
    if demo:
        if f.exists():
            d = json.loads(f.read_text())
            d["cached_at"] = d.get("cached_at", "earlier")
            return d
        b = B.generate(payload, client=_NoNetwork())
        b["warning"] = "Demo mode: no cached brief for this exact scenario, so this is the plain template."
        return b
    b = B.generate(payload)
    if b["mode"] == "llm":
        DEMO.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(b | {"cached_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}))
    return b


class _NoNetwork:
    class messages:
        @staticmethod
        def create(**_):
            raise ConnectionError("demo mode")


def base_map(center, zoom=13) -> folium.Map:
    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)
    folium.GeoJson({"type": "Feature", "properties": {}, "geometry": CITY.boundary_wgs.__geo_interface__},
                   name="Southampton boundary",
                   style_function=lambda _: {"color": "#555", "weight": 1.5, "fill": False}).add_to(m)
    if CITY.flood is not None:
        fl = json.loads((PROC / "flood_zone3.geojson").read_text())
        folium.GeoJson(fl, name="Flood Zone 3", show=False,
                       style_function=lambda _: {"color": "#2b6cb0", "weight": 0, "fillOpacity": 0.25}).add_to(m)
    return m


def add_facilities(m, category):
    fg = folium.FeatureGroup(name=f"Existing: {C.CATEGORIES[category]['label']}")
    for _, f in CITY.facilities(category).iterrows():
        folium.CircleMarker([f.lat, f.lon], radius=4, color="#444", weight=1, fill=True, fill_color="#888",
                            fill_opacity=0.9, tooltip=f"{f['name'] if isinstance(f['name'], str) else 'Unnamed'} ({f.source})"
                            ).add_to(fg)
    fg.add_to(m)


def fmt_flood(v):
    return {True: "⚠️ Yes", False: "No", None: "Not checked"}[v]


def conf_badge(c: str) -> str:
    return {"High": "🟢 High", "Medium": "🟠 Medium", "Low": "🔴 Low"}[c]


def show_brief(payload: dict, demo: bool, results: list[dict]):
    st.subheader("Planning brief")
    with st.spinner("Writing the brief and checking every number..."):
        b = cached_brief(payload, demo)
    a = b["audit"]
    if b["mode"] == "refusal":
        st.error("Insufficient evidence: no recommendation")
    if b.get("cached_at"):
        st.info(f"CACHED brief (demo mode), generated {b['cached_at']}. Not a live result.")
    if b.get("warning"):
        st.warning(b["warning"])
    st.markdown(b["text"])
    if a["ok"]:
        st.success(f"✅ All {a['checked']} numbers verified against source data")
    else:
        st.error(f"❌ {len(a['failed'])} of {a['checked']} numbers could not be verified: {', '.join(a['failed'])}")
    cols = st.columns(3)
    cols[0].caption(f"Mode: {b['mode']}  ·  model: {B.MODEL if b['mode'] == 'llm' else 'none'}")
    cols[1].caption(f"Tokens: {b['tokens_in']} in / {b['tokens_out']} out")
    cols[2].caption(f"Cost: {b['cost_gbp'] * 100:.3f}p")
    st.download_button("⬇️ Export brief (Markdown)", B.export_markdown(payload, b, CITY.sources),
                       file_name="planning_brief.md", mime="text/markdown")
    with st.expander("What the AI was given (the only numbers it may use)"):
        st.json(payload)


def equity_chart(r: dict):
    q = r["equity_newly_covered_by_quintile"]
    df = pd.DataFrame({"Deprivation quintile": ["1 most deprived", "2", "3", "4", "5 least deprived"],
                       "Newly covered": [q[1], q[2], q[3], q[4], q[5]]}).set_index("Deprivation quintile")
    st.bar_chart(df, color="#3b6ea5", horizontal=False, height=220)


# ------------------------------------------------------------------ sidebar
st.sidebar.title("Planning simulator")
st.sidebar.caption("Southampton · where should the next facility go, and who benefits?")
mode = st.sidebar.radio("Mode", ["Test a site", "Find best sites"])
category = st.sidebar.selectbox("Use", list(CATS), format_func=CATS.get)
radius = st.sidebar.select_slider("Walking radius (straight line)", options=[600, 700, 800, 900, 1000],
                                  value=C.DEFAULT_RADIUS_M, format_func=lambda r: f"{r} m (~{round(r / 80)} min)")
with st.sidebar.expander("Housing growth scenario (optional)"):
    g_ward = st.selectbox("Ward", ["None"] + WARDS)
    g_homes = st.slider("New homes", 0, 5000, 0, 250, disabled=g_ward == "None")
    st.caption(f"Assumes {RESIDENTS_PER_HOME} residents per home (ASSUMPTION).")
extra = {g_ward: g_homes * RESIDENTS_PER_HOME} if g_ward != "None" and g_homes else None
demo = st.sidebar.toggle("Demo mode (cached briefs, no network)", value=False)
if demo:
    st.sidebar.warning("DEMO MODE: briefs come from cache and are labelled as cached.")

st.sidebar.divider()
st.sidebar.caption(
    "Data: ONS mid-2024 population estimates spread over Census 2021 Output Areas, IMD 2019, ONS geography, "
    "NHS ODS, OpenStreetMap (ODbL), EA Flood Map. "
    "Straight-line distances from Output Area centroids. Scores are unvalidated design choices. "
    "Decision support only.")

ss = st.session_state
ss.setdefault("site", None)

# ------------------------------------------------------------------ Mode 1: test a site
if mode == "Test a site":
    st.header(f"Test a site: {CATS[category]}")
    how = st.radio("Choose the site by", ["Clicking the map", "Postcode", "Ward"], horizontal=True)
    try:
        if how == "Postcode":
            c1, c2 = st.columns([3, 1])
            pc = c1.text_input("Postcode", placeholder="e.g. SO14 7DU")
            if c2.button("Use postcode", width="stretch") and pc:
                ss.site = postcode_lookup(pc)
        elif how == "Ward":
            w = st.selectbox("Ward (site = population-weighted centre)", WARDS)
            if st.button("Use ward centre"):
                ss.site = E.ward_centroid(CITY, w)
    except E.EngineError as ex:
        st.error(str(ex))

    alts = st.multiselect("Compare against other uses at the same site (up to 2)",
                          [k for k in CATS if k != category], format_func=CATS.get, max_selections=2)

    left, right = st.columns([3, 2])
    with left:
        m = base_map(ss.site or CITY_CENTRE)
        add_facilities(m, category)
        if ss.site:
            folium.Marker(ss.site, tooltip="Proposed site", icon=folium.Icon(color="red", icon="star")).add_to(m)
            folium.Circle(ss.site, radius=radius, color="#c0392b", weight=2, fill=True, fill_opacity=0.08,
                          tooltip=f"{radius} m catchment").add_to(m)
        folium.LayerControl(collapsed=True).add_to(m)
        out = st_folium(m, height=520, use_container_width=True, returned_objects=["last_clicked"], key="map1")
        if how == "Clicking the map" and out and out.get("last_clicked"):
            clk = (out["last_clicked"]["lat"], out["last_clicked"]["lng"])
            if clk != ss.site:
                ss.site = clk
                st.rerun()
        st.caption("Grey dots: existing sites. Toggle the Flood Zone 3 layer with the map's layer control.")

    with right:
        if not ss.site:
            st.info("Pick a site: click the map, enter a postcode, or choose a ward.")
            st.stop()
        try:
            results = [E.evaluate_site(CITY, k, ss.site[0], ss.site[1], radius, extra) for k in [category] + alts]
        except E.EngineError as ex:
            st.error(str(ex))
            st.stop()
        r = results[0]
        st.markdown(f"**Site:** {r['site']['lat']}, {r['site']['lon']} · {r['site']['ward']} ward  \n"
                    f"**Confidence:** {conf_badge(r['confidence'])}")
        if r["confidence_reasons"]:
            st.caption("Why: " + "; ".join(r["confidence_reasons"]))
        if r["insufficient_evidence"]:
            st.error("Insufficient evidence for this use: too few existing sites in the data.")
        c1, c2 = st.columns(2)
        c1.metric(f"{r['demand_label'].capitalize()} within {r['walk_minutes']} min",
                  f"{r['coverage_after_pct']}%", f"{r['coverage_change_pct_points']:+} pts from {r['coverage_before_pct']}%")
        c2.metric("Newly covered", f"{r['newly_covered']:,}",
                  f"{r['equity_most_deprived_40pct_share']}% in most deprived 40%", delta_color="off")
        c1.metric("Mean distance to nearest", f"{r['mean_distance_after_m']} m",
                  f"{r['mean_distance_after_m'] - r['mean_distance_before_m']} m", delta_color="inverse")
        c2.metric("Competitors within 400 m", r["competitors_within_400m"],
                  "cannibalisation risk" if r["cannibalisation_flag"] else "low overlap", delta_color="off")
        c1.metric("Community need", f"{r['need_score']}/100")
        c2.metric("Commercial viability", f"{r['viability_score']}/100")
        st.caption(f"Jobs (assumption): ~{r['jobs_estimate']} ({r['jobs_range'][0]}-{r['jobs_range'][1]}) · "
                   f"Flood Zone 3: {fmt_flood(r['flood_zone3'])} · Mix of uses within 400 m: "
                   f"{r['diversity_before']} → {r['diversity_after']} categories")

    st.divider()
    t1, t2, t3, t4 = st.tabs(["Compare scenarios", "Who benefits", "Uncertainty", "Score inputs"])
    with t1:
        rows = {f"{chr(65 + i)}: {x['category_label']}": x for i, x in enumerate(results)}
        rows["Do nothing"] = E.do_nothing(CITY, category, radius, extra)
        keys = [("Coverage before (%)", "coverage_before_pct"), ("Coverage after (%)", "coverage_after_pct"),
                ("Change (pts)", "coverage_change_pct_points"), ("Newly covered (people)", "newly_covered"),
                ("Most deprived 40% newly covered", "equity_most_deprived_40pct"),
                ("Community need (0-100)", "need_score"), ("Commercial viability (0-100)", "viability_score"),
                ("Competitors within 400 m", "competitors_within_400m"), ("Jobs (assumption)", "jobs_estimate"),
                ("Confidence", "confidence")]
        st.dataframe(pd.DataFrame({n: [v.get(k, "-") for _, k in keys] for n, v in rows.items()},
                                  index=[l for l, _ in keys]).astype(str), width="stretch")
        st.caption("Coverage is measured against each use's own demand (children 0-4 for nurseries, all residents otherwise).")
        # Named existing sites near the chosen site, from the places database (or the 17 Oct baseline)
        sx, sy = E.to_bng(ss.site[0], ss.site[1])
        near = CITY.facilities(category).copy()
        near["Distance (m)"] = ((near["x"] - float(sx)) ** 2 + (near["y"] - float(sy)) ** 2) ** 0.5
        near = near[near["Distance (m)"] <= max(radius, 400)].sort_values("Distance (m)")
        st.markdown(f"**Existing {C.CATEGORIES[category]['label'].lower()} sites within {max(radius, 400)} m: {len(near)}**")
        if len(near):
            cols = {"name": "Name", "Distance (m)": "Distance (m)", "source": "Seen in", "confidence": "Confidence",
                    "flags": "Flags"}
            show = near[[c for c in cols if c in near.columns]].rename(columns=cols)
            show["Distance (m)"] = show["Distance (m)"].round().astype(int)
            if "Seen in" in show:
                show["Seen in"] = show["Seen in"].astype(str).str.replace("places:", "").str.replace("|", " + ")
            st.dataframe(show.head(30), width="stretch", hide_index=True)
    with t2:
        st.markdown(f"**{r['newly_covered']:,} more {r['demand_label']}** within a {r['walk_minutes']} minute walk, "
                    f"**{r['equity_most_deprived_40pct_share']}%** of them in the most deprived 40% of areas nationally.")
        equity_chart(r)
        st.caption("Deprivation quintile from the English Indices of Deprivation 2019 (national rank).")
    with t3:
        scen = [{"category": k, "lat": ss.site[0], "lon": ss.site[1]} for k in [category] + alts]
        sens = E.sensitivity(CITY, scen, extra)
        st.dataframe(pd.DataFrame(sens["newly_covered_by_radius"], index=[x["category_label"] for x in results])
                     .rename(columns=lambda c: f"Newly covered at {c} m"), width="stretch")
        rng = sens["need_score_range"]
        st.write("Community need score range across radii and ±20% weights: " +
                 ", ".join(f"{x['category_label']} {lo}-{hi}" for x, (lo, hi) in zip(results, rng)))
        if len(results) > 1:
            if sens["stable_need_ranking"] and sens["stable_coverage_ranking"]:
                st.success("Ranking is stable across 600/800/1000 m and ±20% weights.")
            else:
                st.warning("Ranking changes under some assumptions. Treat the comparison as close.")
    with t4:
        st.write("Each input is a percentile against every possible site in the city (792 Output Area centres).")
        st.json({"Community need inputs": r["need_inputs_pct"], "Need weights": C.NEED_WEIGHTS,
                 "Commercial viability inputs": r["viability_inputs_pct"], "Viability weights": C.VIABILITY_WEIGHTS})

    st.divider()
    show_brief(B.build_payload(results, sens), demo, results)

# ------------------------------------------------------------------ Mode 2: find best sites
else:
    st.header(f"Find best sites: {CATS[category]}")
    k = st.slider("How many new facilities?", 1, 3, 3)
    try:
        picks = E.optimise(CITY, category, k, radius, extra)
    except E.EngineError as ex:
        st.error(str(ex))
        st.stop()
    if not picks:
        st.info("No site would newly cover anyone at this radius: existing coverage is already complete.")
        st.stop()
    results = [E.evaluate_site(CITY, category, p["lat"], p["lon"], radius, extra) for p in picks]
    left, right = st.columns([3, 2])
    with left:
        m = base_map(CITY_CENTRE)
        add_facilities(m, category)
        for p in picks:
            folium.Circle([p["lat"], p["lon"]], radius=radius, color="#c0392b", weight=1.5, fill=True,
                          fill_opacity=0.06).add_to(m)
            folium.Marker([p["lat"], p["lon"]], tooltip=f"#{p['rank']}: {p['ward']} (+{p['marginal_newly_covered']:,})",
                          icon=folium.DivIcon(html=f"<div style='background:#c0392b;color:#fff;border-radius:50%;"
                                                   f"width:26px;height:26px;text-align:center;line-height:26px;"
                                                   f"font-weight:700;border:2px solid #fff'>{p['rank']}</div>")).add_to(m)
        folium.LayerControl(collapsed=True).add_to(m)
        lats = [p["lat"] for p in picks]
        lons = [p["lon"] for p in picks]
        pad = radius / 111_000 + 0.004
        m.fit_bounds([[min(lats) - pad, min(lons) - pad * 1.6], [max(lats) + pad, max(lons) + pad * 1.6]])
        st_folium(m, height=520, use_container_width=True, returned_objects=[], key="map2")
    with right:
        st.metric(f"{C.CATEGORIES[category]['demand_label'].capitalize()} within {round(radius / 80)} min",
                  f"{picks[0]['coverage_after_all_pct']}%",
                  f"{picks[0]['coverage_after_all_pct'] - picks[0]['coverage_before_pct']:+.1f} pts from {picks[0]['coverage_before_pct']}%")
        tbl = pd.DataFrame([{"Rank": p["rank"], "Ward": p["ward"], "Newly covered (marginal)": p["marginal_newly_covered"],
                             "Need": r["need_score"], "Viability": r["viability_score"],
                             "Competitors 400 m": r["competitors_within_400m"], "Flood Zone 3": fmt_flood(r["flood_zone3"]),
                             "Confidence": r["confidence"]} for p, r in zip(picks, results)]).set_index("Rank")
        st.dataframe(tbl, width="stretch")
        st.caption("Greedy optimiser over all 792 Output Area centres: pick the site that newly covers the most "
                   "people, add it, repeat. Sites in Flood Zone 3 are excluded. It proposes locations, not "
                   "available premises.")
        if st.button("Test the #1 site in detail"):
            ss.site = (picks[0]["lat"], picks[0]["lon"])
            st.info("Switch Mode to 'Test a site' in the sidebar to see it.")
    st.divider()
    st.subheader("Who benefits from the #1 site")
    equity_chart(results[0])
    show_brief(B.build_payload(results, extra={"optimiser": {"method": "greedy maximum coverage",
                                                             "candidate_sites": len(CITY.oa),
                                                             "coverage_before_pct": picks[0]["coverage_before_pct"],
                                                             "coverage_after_all_pct": picks[0]["coverage_after_all_pct"]}}),
               demo, results)
