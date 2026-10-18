# Codebase guide

What every file and function is for, how the pieces connect, and the rules that keep the numbers honest.
Read this with `HANDOVER.md` (status, deadline, to-do) before changing anything.

## 1. What the product is

**SotonShip 2026, Module C: planning simulator.** A planner (or a business) asks "where should the next nursery /
GP / pharmacy / café / library go in Southampton?" or tests a site. The tool shows before/after walking coverage,
who benefits (deprivation), competition, jobs, flood constraint, alternatives vs "do nothing", uncertainty, and a
short AI brief in which every number is automatically checked against the computed data.

Since Sat 17 Oct evening it also has a **places database**: every named shop, service and active company in the
city, merged across official registers, with flags and confidence, which the simulator now reads its existing
sites from, plus browser map views with an advanced filter, an area view and an opportunity finder.

## 2. How the pieces connect

```
 open data (ONS, Census, IMD, EA flood)            open registers (FSA, OSM, NHS ODS, Ofsted, Companies House)
   pipeline/city_data.py + pipeline/population.py     pipeline/places/
            ▼                                                 ▼
 data/processed/oa.csv, lsoa.geojson,          data/db/places.csv (+ source_records, excluded, sqlite)
 flood_zone3.geojson, facilities.csv           data/processed/facilities_places.csv  ◄── export_facilities()
            │                                                 │
            └───────────────┬─────────────────────────────────┘
                            ▼
                 simulator/engine.py  (deterministic: coverage, scores, optimiser; no AI, no UI)
                            │
        ┌───────────────────┼──────────────────────┬──────────────────────────────┐
        ▼                   ▼                      ▼                              ▼
 simulator/brief.py   simulator/app.py     viewer/ (browser pages,         frontend/ (React app; reads
 (AI brief + audit)   (Streamlit UI)       JS port: viewer/src/engine.js)  viewer/src/engine.js + public/data)

 rag/ (separate feature): reads documents in data/raw/official|project → data/processed/index.json → answers
 questions through rag/api.py (used by frontend/) or rag/web.py (Streamlit chat).
```

All commands go through `run.py` (`python run.py` lists them). All folders are defined once in
`simulator/paths.py`.

## Where to change what

| I want to… | Edit | Then run |
|---|---|---|
| Change a radius, score weight, jobs figure or use category | `simulator/config.py` (+ `CATEGORIES` in `viewer/src/engine.js`) | `python run.py test`, `python run.py viewers` |
| Change how coverage / scores / the optimiser work | `simulator/engine.py` **and** `viewer/src/engine.js` | `python run.py test`, `python run.py viewers` |
| Change what the AI brief says or checks | `simulator/brief.py` | `python run.py test` |
| Change the Streamlit app | `simulator/app.py` | `python run.py app` |
| Update residents to a newer ONS estimate | `SAPE_URL`, `SAPE_YEAR` in `pipeline/population.py` | `python run.py population`, then `viewers`, `eval` |
| Re-download geography, Census, IMD, flood, OSM/NHS sites | `pipeline/city_data.py` | `python run.py city-data` |
| Add or fix a places source (FSA, OSM, NHS, Ofsted) | `pipeline/places/sources.py` | `python run.py places`, `viewers` |
| Change how records merge into one place, flags, confidence | `pipeline/places/merge.py` (thresholds in `common.py`) | `python run.py test`, `places` |
| Change detailed types, cuisines, industry groups | `pipeline/places/business_types.py` | `python run.py places`, `viewers` |
| Change Companies House linking | `pipeline/places/companies.py` | `python run.py places --ch-key KEY` |
| Change the browser pages | `viewer/src/*.template.html` (never the built `viewer/*.html`) | `python run.py viewers` |
| Change the React app | `frontend/src/` (Places map: `places/PlacesView.jsx`, heat maps: `lib/HeatLayer.jsx`) | `python run.py frontend` |
| Change the RAG assistant | `rag/` (models and paths in `rag/config.py`) | `python run.py rag index`, `python run.py api` |
| Move a data folder | `simulator/paths.py` only | `python run.py test` |

**Golden rule:** `engine.py` has no AI and no UI. Every number shown anywhere comes from it (or its verified JS
port), so numbers are deterministic and testable. The AI only writes words around numbers it is given, and an
audit rejects any number not in the data.

## 3. Folder map

| Path | What it is | Edit by hand? |
|---|---|---|
| `run.py` | One entry point for every command | Yes |
| `simulator/` | The model: `config.py`, `engine.py`, `brief.py`, `app.py`, `paths.py` | Yes |
| `pipeline/` | Builds `data/`: `city_data.py`, `population.py`, `places/` | Yes |
| `rag/` | Local RAG assistant (Ollama): indexing, retrieval, answers, API, Streamlit chat | Yes |
| `frontend/` | React app (Vite): welcome, places map, simulator, RAG chat | `src/` yes, `public/data/` no (written by `run.py viewers`) |
| `tests/` | pytest tests only | Yes |
| `evaluation/` | Evidence scripts + `results/` (baseline comparison, live briefs) | Scripts yes, results no (regenerate) |
| `data/raw/` | Downloaded source files + `SOURCES.json` (URL, licence, date, rows) | No: written by `pipeline/` |
| `data/processed/` | Clean inputs the engine reads | No: written by `pipeline/` |
| `data/db/` | Places database from a full PC run (gitignored `raw/`, `google_check.csv`) | No |
| `data/db/sample/` | Small real build (17 Oct OSM + NHS + 5,000-row Companies House download) | No |
| `data/cache/` | Distance matrix `.npy` (gitignored), demo-mode briefs, postcode cache | No |
| `viewer/` | Two self-contained browser pages + their sources in `viewer/src/` | Sources yes, HTML no |
| `docs/` | `SIMULATOR.md` (method, results, limits), `DATA_PLAN.md` (sources, flags, names), `SUBMISSION.md`, this file | Yes |
| `HANDOVER.md` | Status, deadline, priorities | Yes |
| `CLAUDE.md` | Rules for AI assistants (git identity, branch) | Yes |
| `logs/` | `briefs.jsonl` cost/audit log (gitignored) | No |

## 4. `simulator/config.py`: every design choice in one place

Nothing here is a validated fact. Change values here, not inside functions.

| Name | Meaning |
|---|---|
| `CATEGORIES` | The 5 uses: label, demand column (`pop_0_4` for nurseries, `pop` otherwise), demand label, jobs (central, low, high) **assumption** |
| `MIN_FACILITIES` (5) | Fewer existing sites than this → confidence Low → the brief refuses |
| `LOW_CONFIDENCE_BELOW` (10) | Fewer than this → Medium |
| `DEFAULT_RADIUS_M` (800), `WALK_M_PER_MIN` (80) | 800 m ≈ 10-minute walk, straight line |
| `SENSITIVITY_RADII` | 600 / 800 / 1000 m for the uncertainty check |
| `COMPETITION_RADIUS_M` (400), `CANNIBALISATION_THRESHOLD` (3) | Competitors counted within 400 m; 3+ raises a flag |
| `EDGE_WARNING_M` (500) | Site this close to the city edge gets a caveat (outside residents not counted) |
| `NEED_WEIGHTS`, `VIABILITY_WEIGHTS` | Score weights; perturbed ±20% in the sensitivity check |
| `FLOOD_VIABILITY_PENALTY` (15) | Points off viability in Flood Zone 3 |

## 5. `simulator/engine.py`: the deterministic engine

All distances are metres on British National Grid (EPSG:27700). Demand points are the 792 Census 2021 Output Area
population-weighted centroids, weighted by ONS mid-2024 residents (`city.pop_year`; the baseline dataset swaps
in the Census 2021 counts). Candidate sites for the optimiser and for score percentiles are the same 792 points.

| Function / class | What it does | Why it exists |
|---|---|---|
| `EngineError` | A user-input problem shown as a plain message (never a stack trace) | Clean error handling (judging C3) |
| `to_bng`, `to_wgs` | lat/lon ↔ BNG metres (pyproj) | Real distances in metres |
| `pairwise(ax, ay, bx, by)` | Distance matrix between two point sets | Vectorised coverage maths |
| `City` (dataclass) | Holds `oa`, `fac`, boundary (BNG + WGS), `sources`, `flood`, `dataset` | One object passed everywhere |
| `City.cand_dist` | 792×792 OA-to-OA distances, cached to `data/cache/oa_oa_dist.npy` | Optimiser runs in milliseconds |
| `City.flood_mask` | Which OA centres are in Flood Zone 3 | Optimiser skips them |
| `City.facilities(cat)` | Existing sites of one use | |
| `City.existing_dist(cat)` | Each OA's distance to its nearest existing site (cached) | Coverage "before" |
| `DATASETS`, `dataset_file()` | `places` → `facilities_places.csv` (default), `baseline` → `facilities.csv` (17 Oct). Env `SIM_DATASET` or argument; falls back to baseline if no database built | Run on the new database but keep the published numbers reproducible |
| `load_city(proc, dataset)` | Reads OAs, sites, LSOA boundary, flood zones, sources; returns `City` | Entry point |
| `demand(city, cat, extra_pop)` | Demand weight per OA; `extra_pop={ward: residents}` adds housing growth spread by population | Housing-growth scenario |
| `check_category`, `resolve_site` | Validate use; reject sites outside the city (50 m buffer) | Error handling |
| `coverage(w, d, r)` | Share of demand within r metres | Core metric |
| `wmean`, `pct_rank` | Weighted mean; percentile of a value among all candidate sites | Scores are percentiles |
| `_candidate_inputs(city, cat, r)` | Raw score inputs for all 792 candidate sites (cached) | So a site's score means "better than X% of possible sites" |
| `scores(...)` | Community need and commercial viability, 0-100, **never merged**; flood penalty on viability | Two honest scores instead of one opaque one |
| `evaluate_site(city, cat, lat, lon, radius, extra_pop, need_w, via_w)` | Everything for one site: coverage before/after, newly covered, mean distance, competitors, diversity, flood, edge distance, equity by IMD quintile, scores, jobs, confidence + reasons | The main result dict used by app, brief, tests |
| `do_nothing(...)` | Baseline row with zero change | Always compared against doing nothing |
| `_perturb`, `sensitivity(city, scenarios)` | Re-run at 600/800/1000 m and each need weight ±20%; reports if the winner changes | Uncertainty display |
| `optimise(city, cat, k, radius, extra_pop)` | Greedy max coverage: pick the OA centre that newly covers most demand, add it, repeat k times; skips flood zone | "Find best sites" mode |
| `brute_force_best` | Exhaustive best single site over given candidates | Test that the optimiser is right |
| `baseline_rank` | "Fewest competitors within 400 m": the spreadsheet answer | Baseline for judging C2/C3 |
| `ward_centroid(city, ward)` | Population-weighted ward centre snapped to an OA centre | Ward picker, evaluation cases |

## 6. `simulator/brief.py`: the AI part

| Function / constant | What it does | Why |
|---|---|---|
| `MODEL` (`claude-haiku-5-5`, env `BRIEF_MODEL`), `PRICES`, `USD_TO_GBP` | Model and $/M-token prices for cost logging | Cost per brief for the business case |
| `SOURCE_TAGS`, `SYSTEM` | Allowed source tags; the system prompt (use only given numbers, tag each claim, four labelled sections, never say "vacant", keep need/viability separate) | Grounding |
| `build_payload(results, sens, extra)` | The **only** thing the LLM sees: a small JSON of numbers already computed | AI can't invent data |
| `_flatten_numbers`, `audit(text, payload)` | Extracts every number in the brief; each must equal a payload number at the precision written (numbers inside [tags] ignored) | Automatic hallucination check, shown as "All N numbers verified" |
| `refusal(payload)` | Rule-based "Insufficient evidence" when confidence is Low | Can't be talked out of it |
| `template(payload)` | Plain-sentence brief from the same numbers | Fallback with no key / network / failed audit |
| `generate(payload, client, model)` | Refusal → LLM call → audit → one retry naming bad numbers → template fallback; logs tokens/cost to `logs/briefs.jsonl` | The full AI pipeline |
| `cost_gbp`, `_log`, `_now` | Cost maths and logging | |
| `export_markdown(payload, brief, sources)` | One-page Markdown export | Planner can attach it to a report |

## 7. `simulator/app.py`: Streamlit app (the product judges see)

Run `python run.py app`. Sidebar: **Existing sites from** (places database / 17 Oct baseline), mode, use,
radius, housing growth, demo mode.

| Function | What it does |
|---|---|
| `city(dataset)` | Cached `load_city` per dataset |
| `postcode_lookup(pc)` | postcodes.io with a local cache; clear errors for invalid/offline |
| `cached_brief(payload, demo)` | Live brief, saved to `data/cache/demo/` on success; demo mode serves the cache, clearly labelled |
| `_NoNetwork` | Fake client that fails, used to force the template in demo mode |
| `base_map`, `add_facilities` | Folium map with boundary, optional flood layer, existing sites with names |
| `fmt_flood`, `conf_badge` | Display helpers |
| `show_brief(payload, demo, results)` | Brief panel: refusal/cached/warning banners, audit badge, export button, "what the AI was given" |
| `equity_chart(r)` | Newly covered by deprivation quintile |

Modes: **Test a site** (map click / postcode / ward; compare up to 2 other uses + do nothing; tabs Compare
(with named nearby sites from the database), Who benefits, Uncertainty, Score inputs; brief) and **Find best sites**
(greedy top 1-3, map, table, brief). Streamlit 1.66 gotchas: use `width="stretch"`, not `use_container_width`
(except `st_folium`); map tiles are `OpenStreetMap` (CartoDB needs a key).

## 8. `pipeline/city_data.py` and `pipeline/population.py`: city data (run rarely)

`python run.py city-data [--skip-osm] [--osm-file PATH]` rebuilds `data/processed/` and `data/raw/SOURCES.json`.
`python run.py population [--sape-file PATH]` only refreshes `oa.csv` to the latest ONS population estimate.

| Function | Source → output |
|---|---|
| `arcgis_query`, `in_list`, `fetch_geography` | ONS ArcGIS: OA centroids, OA→LSOA→ward lookups, LSOA boundaries, IMD 2019 |
| `fetch_population` | Census 2021 TS007A via Nomis: total and aged 0-4 per OA |
| `population.py`: `fetch_sape`, `apply_sape`, `update_population` | ONS mid-2024 LSOA estimates (83 MB xlsx; city rows cached in `data/raw/ons_sape_mid2024_lsoa.csv`). Scales each OA by its LSOA's growth → `pop`, `pop_0_4`, `pop_year`; Census counts kept as `pop_2021`, `pop_0_4_2021` |
| `fetch_facilities`, `parse_osm`, `classify` | Overpass: the 5 uses (+ coworking) → `facilities_osm.csv` |
| `geocode`, `fetch_nhs`, `merge_registers` | NHS ODS GPs/pharmacies geocoded by postcode; replace OSM for those uses → `facilities.csv` (**the 17 Oct baseline**) |
| `polygonal`, `fetch_flood` | Environment Agency Flood Zone 3 → `flood_zone3.geojson` |
| `note`, `_now`, `main` | Source log and orchestration |

Overpass is blocked from cloud workspaces: download on a PC and pass `--osm-file`.

## 9. `pipeline/places/`: the places database

`python run.py places [options]` → `data/db/` and `data/processed/facilities_places.csv`.

Options: `--ch-key KEY` (Companies House API: every active Southampton company, default `--ch-mode advanced`),
`--ch-file CSV` (website Advanced-search download, max 5,000 rows), `--ch-bulk FILE` (free bulk product),
`--fsa-file FHRS877en-GB.xml` (Southampton food hygiene file), `--ofsted-file CSV`, `--osm-file JSON`,
`--google-key KEY --google-limit N` (optional check, gitignored output), `--offline` (rebuild from `data/db/raw/`),
`--skip fsa osm nhs ofsted`. One failing source never stops the others.

**Pipeline:** fetch/parse each source into one record format → postcode lookup → `build()` (fill coordinates,
match records into places, flags, confidence, names, types) → optional Companies House name-search links and Google
check → `save()` → `export_facilities()`.

**Modules** (`from pipeline import places` still gives every name below):

| Module | Functions and constants |
|---|---|
| `common.py` | `note`, thresholds (`MATCH_*`, `SPREAD_FLAG_M`, …), `metres`, `load_city`, `in_city`, `ward_of` |
| `names.py` | `norm_name`, `name_sim`, `norm_postcode`, `TYPE_MAP`, `OSM_MAP`, `osm_type`, `compatible`, `display_name` |
| `sources.py` | `fetch_/parse_` FSA, OSM, NHS, Ofsted; `postcode_lookup`; `google_check` |
| `business_types.py` | `SIC_SUBTYPE` … `detailed_type`, `specialty_of`, `SIC_CATEGORY`, `INDUSTRY_GROUP`, `sic_category` |
| `merge.py` | `match`, `build`, `COORD_RANK`, `SRC_LABEL`, `NAME_PRIORITY`, `PENALTY`, `exclusion_reason` |
| `companies.py` | `ch_records`, `ch_candidates_api`, `ch_profile`, `fetch_ch_advanced`, `parse_ch_search_csv`, `company_tables`, `load_ch_bulk`, `companies_house` |
| `build.py` | `SIM_USES`, `export_facilities`, `save`, `main` |

**Record format** (every source produces these columns): `source, source_id, name, raw_type, category,
sim_category, lat, lon, coord_method, address, postcode, brand, opening_hours, website, phone, quality,
record_date, extra` (JSON with source-specific fields: OSM tags, FSA rating flags, company number/SIC…).

| Function / constant | What it does | Why |
|---|---|---|
| `note` | Records source URL, licence, date, rows | Data provenance (C5) |
| `metres`, `load_city`, `_in_ring`, `in_city` | Haversine distance; city outline from LSOA boundaries; point-in-polygon (no shapely needed) | Runs without heavy GIS libraries |
| `STOP`, `norm_name`, `GENERIC`, `name_sim(a, b, same_type)` | Name normalising and 0-1 similarity; generic words ("surgery", "pharmacy") are ignored **only for the same type of business** | Matching without false merges (e.g. Bitterne Pharmacy ≠ Bitterne Surgery) |
| `norm_postcode` | "so147du" → "SO14 7DU" | |
| `TYPE_MAP`, `OSM_MAP`, `osm_type` | Source types → our `category` and `sim_category` | One taxonomy |
| `COMPATIBLE`, `compatible` | Which categories may be the same place | `TYPE_CONFLICT` flag |
| `fetch_fsa`, `read_fsa_xml`, `parse_fsa` | FSA API v2 (or the per-council XML file) → records with name, type, address, postcode, coordinates, hygiene rating | Every food business, official |
| `OVERPASS`, `fetch_osm`, `parse_osm` | All named shops/amenities/healthcare/offices/leisure/tourism + the 5 uses even if unnamed; keeps cuisine, brand, hours, website, last edit | Map detail and exact pins |
| `ODS`, `DISTRICTS`, `NHS_ROLES`, `fetch_nhs`, `parse_nhs` | Active GPs, branch surgeries, pharmacies (pin = postcode centre) | Official health register |
| `OFSTED_PAGE`, `fetch_ofsted`, `_col`, `parse_ofsted` | Latest Ofsted provider CSV (found via the GOV.UK content API); columns found by keyword; Southampton only; childminders excluded (redacted at source) | Official childcare register with places |
| `postcode_lookup(pcs, offline)` | postcodes.io bulk lookup + terminated postcodes; cached in `data/db/raw/postcodes.json` | Fills missing pins, checks given pins |
| `match(recs)` | Union-find: two records are one place if close and similar names (rules below); same-register duplicates (OSM/FSA, same type, ≤30 m, ≥0.9) merged; at most one record per register per place otherwise | Entity resolution |
| `DEDUP_SOURCES`, `DUP_M`, `COORD_RANK`, `SRC_LABEL` | Which registers can have internal duplicates; pin precision order (mapped point > building > FSA geocode > postcode centre) | Best pin wins |
| `NAME_PRIORITY`, `display_name` | Name taken from NHS ODS / Ofsted, then FSA, then OSM, then Companies House (title-cased); a bare brand ("Well") gives way to a fuller name containing it | Final, most reliable names (`name_source`, `names_seen`) |
| `SIC_SUBTYPE`, `OSM_SUBTYPE`, `CUISINE`, `CHAIN_CUISINE`, `NAME_SUBTYPE`, `FOOD_CATS`, `cuisine_from`, `detailed_type` | Detailed type (e.g. Dental practice, Spa, Fast food) and cuisine/cuisine family; source order: map tag → register → SIC code → words in the name (`subtype_from` / `cuisine_from = "name"` marks guesses) | Advanced filter ("Korean restaurants", "dentists") |
| `has_word` | Name keyword at the start of a word; keys of 4 letters or fewer only as whole words ("spa" not in "Sparky") | Stops false guesses |
| `CUISINE_SPECIALTY`, `SHOP_SPECIALTY`, `specialty_of(row)` | One clear label per place for the advanced search: cuisine for food (Bubble tea, Japanese, Korean, Coffee shop…), shop words (Asian supermarket, Polish shop…), Barber / Nail salon, else the detailed type, else the company's SIC division; `specialty_from` says where it came from ("name" = a guess) | Industry → detailed type search. `build_viewers.py` adds it to older files |
| `PENALTY`, `exclusion_reason` | Points off confidence per flag; out-of-scope records (not in Southampton, dormant, registered outside the city, unlocatable) go to `excluded_places.csv` with the reason | Every flag costs something; nothing silently dropped |
| `SIC_CATEGORY`, `SIM_FROM_CATEGORY`, `INDUSTRY_GROUP`, `CUSTOMER_FACING_GROUPS`, `sic_category` | SIC code → category → one of 11 industry groups; customer-facing yes/no | Sort and classify industries |
| `ch_records(reg)` | Companies House register rows → standard records (pin = registered-office postcode) | Companies merge like any other source |
| `ward_of(lat, lon)` | Ward of the nearest OA centre | Area view |
| `build(recs, pcs, polys)` | The core: coordinates, matching, flags, confidence, names, types, industry group, ward, exclusion; returns (places, records with `place_id`) | One row per real-world place |
| `SIM_USES`, `export_facilities(places, bbox)` | Simulator sites from the database: the 5 uses; GP and pharmacy must be on the NHS register; registered-office-only, excluded and out-of-area records never count | Simulator runs on the database |
| `google_check(places, key, limit)` | Optional Google Places text search near each low-confidence place: distance, name, closed status flags; stores only Google place IDs | Spot-check pins (Google's terms limit caching; file gitignored) |
| `CH_API`, `CH_SKIP`, `SIC_TEXT`, `_district`, `ch_candidates_api`, `ch_profile` | Companies House name search and company profile (accounts dates/type) | Links for companies registered elsewhere (chains) |
| `fetch_ch_advanced(key)` | API advanced search: all **active** companies registered in Southampton; incorporation dates split into windows to get past the 5,000-per-request cap → `companies_register.csv` | Latest, complete company list |
| `SIC_DIVISIONS`, `CUSTOMER_FACING`, `PC_RE`, `CITY_DISTRICTS`, `parse_ch_search_csv` | Reads the website download (unquoted commas in names and SIC lists handled) | Use the CSV the team downloaded |
| `company_tables`, `load_ch_bulk`, `companies_house` | Older company-table builder (address grouping), bulk-file reader, and name-search linking (active only, no guessing) | Kept for `--ch-bulk` / `--ch-mode search` |
| `save(...)` | Writes `places.csv`, `excluded_places.csv`, `source_records.csv`, `company_links.csv`, `places.sqlite` (tables places, excluded_places, source_records, sources, companies_register…), `summary.json` | Outputs |
| `main(argv)` | CLI orchestration | |

**Matching rules:** same type + ≤100 m + name similarity ≥0.55, or name similarity ≥0.85 + (≤300 m or same
postcode). Companies House (postcode-centre pins) only joins on the strict rule. Thresholds are design choices.

**Confidence (0-100):** 40 + 20 per extra register + pin precision (mapped +20, building +15, FSA +10, postcode 0)
− `PENALTY` per flag. Company known only by its registered office ≈ 25-40; place confirmed by 2-3 registers 60-100.

**`places.csv` columns:** `place_id, name, name_source, category, all_categories, sim_category, lat, lon,
coord_source, coord_method, location_spread_m, address, postcode, brand, opening_hours, website, phone, quality,
sources, n_sources, names_seen, inside_city, confidence, flags, excluded_reason, ward, subtype, cuisine,
cuisine_family, subtype_from, specialty, specialty_from, industry_group, customer_facing, company_number, company_name, company_type,
sic_codes, industry, incorporated, google_maps_url, google_maps_search`.

**Flags** (meaning in `docs/DATA_PLAN.md` §7): SINGLE_SOURCE, NO_COORDINATES, SOURCES_DISAGREE_ON_LOCATION,
COORDS_FROM_POSTCODE_ONLY, FAR_FROM_OWN_POSTCODE, POSTCODE_TERMINATED, POSTCODE_INVALID,
NAME_DIFFERS_BETWEEN_SOURCES, TYPE_CONFLICT, MERGED_DUPLICATE, POSSIBLE_DUPLICATE, OSM_NOT_CHECKED_3Y,
FSA_INSPECTION_OVER_4Y, FSA_RATING_PENDING, OUTSIDE_CITY, REGISTERED_OFFICE_ONLY, SHARED_ADDRESS_5PLUS,
DORMANT_OR_NON_TRADING, NOT_IN_SOUTHAMPTON, COORDS_FROM_2017_POSTCODE_FILE, COMPANY_*, GOOGLE_*.

## 10. `viewer/`: browser pages

Open `viewer/places_register.html` or `viewer/site_simulator.html` by double-click. Rebuild after data changes:
`python run.py viewers` (uses `data/db/` if a full build exists, else `data/db/sample/`).

| File | What it is |
|---|---|
| `src/engine.js` | JS port of `engine.py` (coverage, scores, sensitivity, optimiser, payload, template brief, audit) incl. a WGS84→OSGB36→BNG projection. **Must stay in step with engine.py.** |
| `src/verify_engine.js` | Checks the JS port against the Python engine's saved results (49 checks; run by `build_viewers.py` when node exists) |
| `src/eval_places.js` | Evaluation on the places dataset with the JS engine (writes `evaluation/results/*_places.*`) |
| `src/pack_city.py` | Packs OAs, sites, LSOA shapes (simplified), city edge, flood shapes into one JSON |
| `src/site_simulator.template.html` | Simulator page: modes, dataset switch (database / baseline / load a newer `places.csv`), named nearby sites, "What's nearby" tab, map tooltips |
| `src/places_register.template.html` | Register page: table + map, advanced search (industry group → tickable, searchable detailed types grouped by business type; everyday words like "boba" or "sushi" also match), flags filter, map views: Places, **Heatmap** (density of the filtered places, one-hue ramp), **People** (where residents live: ONS mid-2024 residents at the 792 OA centres, weighted heat map), **Popular** (each ward coloured by its leading detailed type: most common, or stands out vs its city-wide share with ≥3 places; marker + label per ward; hover tooltip with the ward's top 6), Per 1,000 (wards shaded per 1,000 residents); click a ward (in any area view, or the ward links) to focus it: zoom, outline, rest faded, table filtered, and a ward profile (places, per 1,000 vs city, residents, % most deprived fifth, top 10 types as bars with "× city" share ratio, types it has less of than the city); `#view=heat|pop|area&ward=Portswood` opens a view and ward, **Suggest spots to open** (ranks OA centres: residents within 800 m × footfall stand-in ÷ (1 + 2 × same-type within 800 m); 5 picks ≥1 km apart) |
| `build_viewers.py` | Fills the templates' `__PLACEHOLDERS__` with data and writes the two HTML files, plus `frontend/public/data/{places,city}.json` |

The React app (`frontend/`) has the same map views on its Places page (`places/PlacesView.jsx`). The view switch
sits at the top of the left panel and the panel shows only what that view needs: **Popular** = sector list (all
sectors → wards coloured by leading sector; one sector → leading business type in it) + most common / stands out;
**Heatmap** = sector list; **People** = age groups with city totals; **Places** = full search (text, industry,
detailed types). A type clicked in an area profile opens the Places search for it. Views: Popular,
Heatmap (places), **People** (where residents live, by age group: all, 0–4, 5–15, 16–24, 25–44, 45–64, 65+;
ward tooltip and area profile show each area's age mix against the city) and Places. `?view=people&ward=Bargate#places`
opens a view and ward. Age groups come from `AGE_BANDS` in `pipeline/population.py` (each OA takes its LSOA's age mix). Both heat maps use `lib/HeatLayer.jsx` (points may carry a weight `w`).

### React business simulator (`frontend/src/simulator/`)

`SimulatorView.jsx` + `opportunity.js` (deterministic, no AI). The user types what they want to open; the model
matches it to a detailed type in the places data (`matchBusiness`; no exact match → the whole category, e.g. all
restaurants), picks default customers by age group (editable), then scores all 792 Output Area centres
(`analyse`): customers nearby (target-age residents within the walking distance, nearer ones weighted more),
room in the market (customers ÷ (1 + 2 × competitors + 0.3 × related businesses)), passing trade (customer-facing
places within 400 m) and growth (residents since 2021). Each is a percentile across all sites; weights depend on
the sector (passing-trade sectors weight footfall 25%); flood zone 3 costs 15 points. **Whole Southampton**
proposes the top 5 sites ≥1 km apart (`suggest`), **Choose an area** the top 3 in one ward, **Pick on map** tests
any spot (`siteAt`). `feasibilityBrief` turns the numbers into strengths, risks, suggested changes (including a
better site within 1.5 km) and limitations. For nursery / GP / pharmacy / café / library the planning engine adds
coverage and the audited planning brief. Place-type helpers shared with the Places page are in
`lib/placeTypes.js`.

**AI classification:** pressing Enter / *Analyse with AI* (or `?idea=thai%20restaurant#simulator`) sends the idea
plus the data's own sectors and detailed types to `POST /api/classify` (`rag/classify.py`). The local LLM (same
model as the assistant, `OLLAMA_CHAT_MODEL`) returns JSON: business, sector, niche, like-for-like types, related
types, name keywords, customers, passing trade, reasoning and setup tips. The server keeps only types and sectors
that exist (vague "cuisine not known" types can only be related; related must share the sector; generic name words
are dropped). `targetFromAI` turns it into the model's target: direct competitors = the like-for-like types plus
same-sector places whose name contains a keyword; passing trade sets the footfall weight. The AI never produces a
score or count. If Ollama is off, the page falls back to `matchBusiness` and says so. Tests:
`tests/test_rag_classify.py`.

**Assistant context:** `lib/assistantContext.js` holds a plain-text summary of what is on screen (set by the
Places and Simulator pages); the chatbot (`App.jsx`) sends it as `context` with each question, and
`rag/generator.py prepare_answer(app_context=...)` adds it to the prompt as "App analysis" that the model may cite.

## 11. `tests/` and `evaluation/`

| File | What it covers |
|---|---|
| `tests/test_engine.py` (22) | Hand-checked toy example, dense café ≈ 0 change, flood flag, thin-data refusal, outside city, empty input, no-key fallback, sensitivity, identical scenarios, optimiser = brute force, equity sums, audit catches injected number, retry then fallback, housing growth, ward centre inside city, scores never merged, mid-2024 scaling, baseline keeps Census 2021 |
| `tests/test_build_places.py` (20) | Name normalising, cross-source merge, neighbours stay separate, location/type conflict, postcode checks, missing coords / outside city, duplicate merge + stale flag, exclusions, confidence, Companies House matching/no-guessing/wrong industry, advanced search window splitting, website CSV parsing, address grouping, company merges into places, SIC categories, pharmacy ≠ surgery, register name wins, detailed types and cuisine |
| `evaluation/run_evaluation.py` | Baseline comparison + optimiser timings → `baseline_results*.csv`, `evaluation_summary*.json` (suffix `_places` unless `SIM_DATASET=baseline`) |
| `evaluation/run_live_briefs.py` | 10 live AI briefs (needs `ANTHROPIC_API_KEY`) → audit pass rate and real cost |

## 12. Rules when changing things

- Numbers come from `engine.py` only. If you change maths there, change `viewer/src/engine.js` the same way and run
  `python run.py viewers` (49/49 checks must still pass) and `python run.py test`.
- Never let the AI compute a number; extend `build_payload` instead.
- Keep the 17 Oct baseline files (`facilities.csv`, `evaluation/results/baseline_results.csv`, `evaluation/results/evaluation_summary.json`)
  unchanged: the README numbers were computed on them.
- New data source → produce the standard record format, add it to `SRC_LABEL`, `NAME_PRIORITY`, `COORD_RANK`
  if relevant, call `note()` with URL and licence, add a test.
- Never store personal data (company officers, childminders' addresses). Don't use the VOA rating list (licence)
  or store Google content in the repo.
- Git: commit as TYK3, no AI attribution lines, push only to `feature/simulator` (see `CLAUDE.md`).
