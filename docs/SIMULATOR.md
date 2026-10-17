# Module C: Planning scenario simulator and optimiser

A planner asks "where should the next nursery (or GP, pharmacy, café, library) go?", or tests a specific
site. The tool shows before-and-after walking-distance coverage, who benefits (including the most deprived
areas), nearby competition, a jobs estimate and flood constraints, side by side with alternatives and
"do nothing". It shows uncertainty and sources, and writes a short brief in which every number is
automatically checked against the computed data.

## Run it

```bash
git clone https://github.com/edwardyun12/sotonship2026 && cd sotonship2026
git checkout feature/simulator
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...                     # optional; Windows: set ANTHROPIC_API_KEY=...
streamlit run src/app.py
```

Processed data is committed, so the app runs from a clean clone with no downloads. Without an API key it
still works and shows a plain template brief instead of the AI brief. **Demo mode** (sidebar) serves
briefs cached from earlier live runs and labels them as cached.

Rebuild the data from source: `python -m src.fetch_data`. Overpass (OpenStreetMap) blocks some cloud IPs.
If it fails, download on a laptop and run `python -m src.fetch_data --osm-file osm_facilities.json`.

Tests: `pytest -q` (20 tests). Evidence: `python -m tests.run_evaluation`.

## Data sources

All downloaded 17 Oct 2026. Full list with URLs and row counts: `data/raw/SOURCES.json`.

| Data | Source | Licence | Used for |
|---|---|---|---|
| Output Area population-weighted centroids (792) | ONS Open Geography, OA Dec 2021 PWC V4 | OGL v3.0 | Demand points |
| Population, total and aged 0-4, by Output Area | Census 2021 TS007A via Nomis | OGL v3.0 | Demand (0-4 for nurseries) |
| OA to LSOA to ward lookups; LSOA 2021 boundaries | ONS Open Geography | OGL v3.0, contains OS data © Crown copyright | Wards, city boundary, map |
| Index of Multiple Deprivation 2019 (national rank) | MHCLG, via ONS lookup | OGL v3.0 | Equity panel, need score |
| GP practices, branch surgeries, pharmacies (active) | NHS Organisation Data Service | OGL v3.0 | Existing GP and pharmacy sites |
| Postcode coordinates | postcodes.io (ONS Postcode Directory) | OGL v3.0, OS and Royal Mail © | Geocoding NHS sites; postcode box |
| Cafés, nurseries/childcare, libraries | OpenStreetMap via Overpass (data as of 17 Oct 2026 17:31 UTC) | ODbL 1.0 © OpenStreetMap contributors | Existing sites |
| Flood Zone 3 (rivers and sea) | Environment Agency Flood Map for Planning | OGL v3.0 | Constraint flag; optimiser excludes FZ3 |
| Jobs per facility | **Our assumption table** (`src/config.py`) | n/a | Indicative jobs only |

No personal data is used. Facility data is about organisations, and population data is aggregated
census counts.

## What the engine computes (deterministic, no AI)

`src/engine.py`, distances in metres on British National Grid.

- **Coverage(R)**: population whose Output Area centroid is within R metres (straight line) of at least one
  facility, divided by total population. Computed before and after adding the proposed site. Default R = 800 m,
  about a 10 minute walk.
- **Mean distance**: population-weighted mean distance to the nearest facility, before and after.
- **Competition**: same-use facilities within 400 m. Three or more raises a cannibalisation flag.
- **Diversity**: distinct uses within 400 m, before and after.
- **Equity**: newly covered people split by national IMD quintile. Headline: share in the most deprived 40%.
- **Community need** and **commercial viability** are two separate 0-100 scores that are never merged.
  Each input is a percentile against all 792 possible sites in the city. Need = uncovered share of the
  catchment (0.4), distance to the nearest existing site (0.3), deprivation (0.3). Viability = catchment
  demand (0.6) and low competition (0.4), with a 15-point penalty in Flood Zone 3. **The weights are design
  choices, not validated.**
- **Sensitivity**: reruns at 600, 800 and 1000 m and with each need weight ±20%, and reports whether the
  ranking changes.
- **Optimiser**: greedy maximum coverage over all 792 Output Area centres, excluding Flood Zone 3: pick the
  site that newly covers the most people, add it, repeat. It proposes locations, never vacant premises.
- **Confidence** (High, Medium, Low): Low under 5 existing sites of that use (the tool refuses to recommend),
  Medium under 10.
- **Housing growth**: adds N new homes × 2.3 residents (assumption) to a ward and recomputes.

## What the AI does

`src/brief.py`. The LLM (Claude Haiku 5.5, configurable with `BRIEF_MODEL`) receives **only** a JSON of numbers
the engine already computed, plus source tags. It writes a 150-250 word brief for a planner, with a source tag
after each claim.

1. **Numbers audit**: every number in the brief is extracted and must match a number in the JSON at the
   precision written. If any number fails, the model gets one retry with the bad numbers listed. If that also
   fails, the app shows a plain template and a warning. The app displays "All N numbers verified against
   source data".
2. **Refusal**: when confidence is Low (too few existing sites), the tool returns "Insufficient evidence"
   with what is missing. This is rule-based, so it cannot be talked out of it.
3. **Fallback**: with no key, network or API failure, the app shows a template brief built from the same numbers.
4. **Cost log**: tokens and cost per brief are written to `logs/briefs.jsonl`. At Haiku 5.5 prices
   ($0.10 / $0.50 per million input/output tokens) a typical brief (~1,500 in, ~350 out) costs about **0.02p**.

The AI never computes a number. The numbers are deterministic on purpose so they can be tested.

## Test results (17 Oct 2026)

- `pytest`: **20 / 20 pass**. Covers hand-checked toy examples, dense-centre café ≈ 0 change, flood flag,
  thin-data refusal, outside-city and empty-input errors, no-key fallback, identical scenarios, optimiser equal
  to exhaustive search over all 792 sites for all 5 uses, equity quintiles summing to the total, an injected
  wrong number caught by the audit, and audit retry then fallback.
- **Baseline** ("pick the site with the fewest competitors within 400 m", the spreadsheet answer), 10 cases ×
  3 candidate wards (`tests/baseline_results.csv`): our pick **differs in 5 of 10 cases**, and in those
  cases newly covers **8,457 more people** in total. Caveat: in several cases the baseline was a tie (0
  competitors at 2-3 sites) broken by list order. That is what a spreadsheet does, but it flatters us.
- **Optimiser** (top 3, 800 m), under 0.01 s per run:

| Use | Coverage now | After top 3 sites | Top 3 wards |
|---|---|---|---|
| Nursery (children 0-4) | 60.2% | 76.7% | Sholing, Bevois, Millbrook |
| GP | 83.5% | 91.5% | Redbridge, Bassett, Sholing |
| Pharmacy | 85.6% | 92.8% | Bassett, Sholing, Woolston |
| Café | 79.4% | 89.0% | Sholing, Coxford, Woolston |
| Library | 43.7% | 59.7% | Freemantle, Redbridge, Sholing |

- **AI brief numbers audit on live briefs**: not yet run (needs an API key). TODO: run 10 live briefs and
  report the pass rate from `logs/briefs.jsonl`.

## Known limits and failures

- **Straight-line distance ignores barriers** such as the River Itchen, railways and main roads, so it overstates
  who can walk to a site, most where crossings are far apart. Network walking distance (OSMnx) is the fix.
- **The city boundary follows the waterfront**, so many sites show a "near the boundary" caveat. Residents
  just outside the city (Eastleigh, Totton) are not counted as demand, though facilities outside the city are.
- **Nurseries come from OpenStreetMap**, which likely undercounts childcare. The Ofsted register would be
  better and is not loaded yet.
- **No capacity**: a GP with a full list counts the same as one with space. ODS sites are geocoded to the
  postcode centroid.
- **IMD 2019 is on 2011 areas**. 38 of 792 Output Areas sit in changed LSOAs and were placed spatially.
- **Population is Census 2021**, not the latest mid-year estimate.
- Scores and weights are unvalidated. Jobs figures are assumptions. This is decision support for a human
  planner, not a decision.

## AI-generated vs pre-existing

The code in `src/` and `tests/` was written during the hackathon with an AI coding assistant (Claude),
directed and reviewed by the team. No pre-existing project code. Libraries: pandas, numpy, shapely, pyproj,
streamlit, folium, streamlit-folium, anthropic. All data is from the public sources above.
