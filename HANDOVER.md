# HANDOVER: SotonShip 2026, Module C planning simulator

Paste this whole file into the next AI session. It is self-contained.

## Context

- Hackathon: SotonShip 2026 (Southampton AI Society). **Submissions lock Sun 18 Oct 2026, 13:00 UK time.**
- Judging: C1 Problem and user 20%, C2 AI at the core 20%, C3 Working product 25% (live, real data, failure
  handling, tests vs baseline), C4 Business and scale 20%, C5 Responsibility and trust 15%.
- Submission: public GitHub repo, a README covering setup, data sources with dates and licences, what the AI
  does, what is AI-generated vs pre-existing, test results and limits, a 1:00-3:00 YouTube video showing the
  real product, a 150-word summary, and exactly 2 team members.
- Repo: https://github.com/edwardyun12/sotonship2026, branch **`feature/simulator`** (all work is here; `main` untouched).
- Product in one sentence: a planner asks "where should the next nursery / GP / pharmacy / café / library go
  in Southampton?" or tests a site. The tool shows before/after walking coverage, who benefits (deprivation),
  competition, jobs, flood constraint, alternatives vs do-nothing, uncertainty, and an AI brief whose
  numbers are automatically audited.
- User preferences: commit messages must **not** contain `Claude-Session:` links. Keep answers short and practical.

## Status (Sat 17 Oct, ~18:50): core works end to end, Gate 2 passed early

Run: `pip install -r requirements.txt && streamlit run src/app.py`. Tests: `pytest -q` → **20/20 pass**.
Evidence: `python -m tests.run_evaluation`. Full docs: **`docs/SIMULATOR.md`** (sources, method, results, limits).

### Files
| File | What it is |
|---|---|
| `src/fetch_data.py` | Downloads and cleans all data → `data/processed/`. `--skip-osm`, `--osm-file PATH` options |
| `src/config.py` | Categories, demand column, jobs assumptions, radii, score weights, thresholds |
| `src/engine.py` | Deterministic engine (no AI): `load_city`, `evaluate_site`, `do_nothing`, `sensitivity`, `optimise`, `brute_force_best`, `baseline_rank`, `ward_centroid`, `EngineError` |
| `src/brief.py` | `build_payload`, `audit` (numbers check), `refusal`, `template`, `generate` (LLM + 1 retry + fallback + cost log to `logs/briefs.jsonl`), `export_markdown` |
| `src/app.py` | Streamlit app: Mode "Test a site" (map click / postcode / ward, compare up to 2 uses + do nothing, tabs: compare, who benefits, uncertainty, score inputs, brief, export) and Mode "Find best sites" (greedy top-3 map + table + brief). Sidebar: use, radius 600-1000, housing growth, demo mode |
| `tests/test_engine.py` | 20 tests incl. hand-checked toy example, outside-city, empty input, flood, refusal, audit injection, optimiser = exhaustive search |
| `tests/run_evaluation.py` | Baseline comparison → `tests/baseline_results.csv`, `tests/evaluation_summary.json` |
| `data/processed/` | `oa.csv` (792 Output Areas: lat/lon, pop, pop_0_4, ward, IMD rank/decile/quintile), `facilities.csv`, `lsoa.geojson`, `flood_zone3.geojson` |
| `data/raw/SOURCES.json` | URL, licence, download time, row count per dataset |

### Data (all real, downloaded 17 Oct 2026)
- 792 Census 2021 Output Area population-weighted centroids, pop 248,982, aged 0-4 13,782, 16 wards.
- IMD 2019 national rank (754 OAs matched by code, 38 placed spatially in 2011 LSOAs).
- Facilities: cafe 171, nursery 40 (OSM), library 17 (OSM), GP 52 + pharmacy 52 (NHS ODS register, geocoded via postcodes.io). Coworking dropped (2 sites).
- Flood Zone 3 from Environment Agency WFS (raw 19 MB file gitignored).
- Network note: in the cloud workspace, Overpass (OpenStreetMap) is blocked. It was downloaded on the user's
  Windows PC into `Downloads\sotonship-data\osm_facilities.json`, then processed with `--osm-file`.

### Key numbers for the pitch
- City-centre café (50.9046, -1.4045): coverage change **0**, 16-32 competitors within 400 m → "already served" demo moment.
- Optimiser top 3 (800 m): nursery 0-4s **60.2% → 76.7%** (Sholing, Bevois, Millbrook); GP 83.5→91.5; pharmacy 85.6→92.8; café 79.4→89.0; library 43.7→59.7. Runtime < 0.01 s.
- Baseline (fewest competitors within 400 m): differs in **5 of 10** cases, and in those our pick newly covers **8,457 more people**. Caveat: some baseline picks were ties broken by list order.
- Brief cost on Claude Haiku 5.5 ($0.10 / $0.50 per M tokens): ~**0.02p per brief** (estimate, ~1,500 in / 350 out tokens; not yet measured live).

## Not done yet (priority order)

1. **Live AI brief test.** No `ANTHROPIC_API_KEY` in the cloud workspace yet. Set the key, run 10 briefs
   across scenarios, record the audit pass rate and real cost from `logs/briefs.jsonl`, and add them to
   `docs/SIMULATOR.md` (there's a TODO line). Running live also fills the **demo-mode cache**
   (`data/cache/demo/*.json`). Commit those 3 rehearsed scenarios (cafe city centre; nursery optimiser top 3;
   library Bitterne Park 50.9330,-1.3700 vs cafe).
2. **Ofsted childcare register** for nurseries (OSM's 40 is likely an undercount): add to `fetch_data.py`
   like `fetch_nhs`, geocode postcodes, `merge_registers`. Check the licence.
3. **Real-user quote** (C1): email data.observatory@southampton.gov.uk and ask mentors. Never invent a quote.
4. **Business numbers** (C4): who pays (council planning/public health teams, nursery chains, pharmacy
   operators), price hypothesis, cost per brief. Put them in the docs and the pitch.
5. **Submission artefacts:** 150-word summary, 3-minute video (screen recording of the real app, see
   plan below), merge `feature/simulator` into `main` (repo must be public, no secrets in history),
   and team page fields.
6. Nice-to-have, only if time: walking-network distance (OSMnx), natural-language input, an equity chart
   label tweak. Feature freeze Sun 09:15.

## Known limits (already documented)
Straight-line distance ignores barriers (River Itchen, railways). The city boundary follows the waterfront,
so many sites show a "near boundary" caveat (it doesn't lower confidence). Demand outside the city isn't
counted. No capacity data (GP list sizes). Weights and jobs are unvalidated assumptions. Census 2021 population.

## Gotchas
- `use_container_width` is deprecated in Streamlit 1.66: use `width="stretch"` (except `st_folium`, which still takes `use_container_width`).
- CartoDB tiles now need an API key, so the app uses `tiles="OpenStreetMap"`.
- Folium GeoJson needs Feature-wrapped geometry, and the flood layer must be MultiPolygon (`polygonal()` in fetch_data).
- Don't `pkill -f streamlit` from a shell whose command line contains "streamlit": it kills itself.
- Headless UI test: `streamlit.testing.v1.AppTest.from_file("src/app.py")`. Set `at.session_state["site"]=(lat, lon)`.

## Video plan (3:00)
0:00-0:20 problem + evidence + quote · 0:20-1:40 live demo: café in centre = 0 change → "Find best sites"
nursery top 3 (60.2→76.7%) → who-benefits chart → audited brief with "All N numbers verified" badge ·
1:40-2:10 why AI: grounded brief, audit, refusal on thin data, baseline 5/10 · 2:10-2:45 who pays, cost per
brief, works for any English city (all national open data) · 2:45-3:00 limits + next step.
