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
- **Data used**: the simulator now reads existing sites from the merged places database
  (`data/processed/facilities_places.csv`, written by `python -m src.build_places`). GP and pharmacy sites must be on
  the NHS register (the map also tags MRI units and counsellors as "doctors"); companies known only by their
  registered office are never counted as sites. The 17 Oct file stays available as `SIM_DATASET=baseline` (and in
  the app's sidebar) so the numbers below can be reproduced. Places database results:
  `tests/evaluation_summary_places.json` and `tests/baseline_results_places.csv`.

| Use | Coverage now → after top 3 (places database) | 17 Oct baseline |
|---|---|---|
| Nursery (children 0-4) | 60.2% → 76.7% (Sholing, Bevois, Millbrook) | 60.2% → 76.7% |
| GP | 83.1% → 91.1% (Redbridge, Sholing, Bassett) | 83.5% → 91.5% |
| Pharmacy | 85.9% → 92.8% (Sholing, Bassett, Woolston) | 85.6% → 92.8% |
| Café | 79.4% → 89.0% | 79.4% → 89.0% |
| Library | 43.7% → 59.7% | 43.7% → 59.7% |

  Baseline comparison on the places database: our pick differs in **5 of 10** cases and newly covers **9,403** more
  people in those cases (17 Oct baseline: 5 of 10, 8,457).

- **Optimiser on the 17 Oct baseline** (top 3, 800 m), under 0.01 s per run:

| Use | Coverage now | After top 3 sites | Top 3 wards |
|---|---|---|---|
| Nursery (children 0-4) | 60.2% | 76.7% | Sholing, Bevois, Millbrook |
| GP | 83.5% | 91.5% | Redbridge, Bassett, Sholing |
| Pharmacy | 85.6% | 92.8% | Bassett, Sholing, Woolston |
| Café | 79.4% | 89.0% | Sholing, Coxford, Woolston |
| Library | 43.7% | 59.7% | Freemantle, Redbridge, Sholing |

- **AI brief numbers audit on live briefs**: not yet run (needs an API key). TODO: run
  `python -m tests.run_live_briefs` (10 scenarios) and report the pass rate and real cost from
  `tests/live_brief_results.json`.

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

## Business and scale

**Who has the problem, and how often.** Two statutory jobs already ask "is this service within reach, and
where is the gap?":
- **Pharmaceutical Needs Assessment (PNA)**: every Health and Wellbeing Board must publish one at least every
  three years (NHS Pharmaceutical Services Regulations 2013). Southampton's latest was published in August
  2025 ([data.southampton.gov.uk](https://data.southampton.gov.uk/health/pharmaceutical-needs-assessment)).
  Councils often buy these in: Westminster and Kensington & Chelsea tendered their 2022 PNA at an estimated
  **£45k-£60k** ([bidstats](https://bidstats.uk/tenders/2021/W52/765853914)).
- **Childcare sufficiency**: councils have a statutory duty to secure enough childcare and report on it to
  elected members every year. Southampton's Early Years team produces a Childcare Sufficiency Assessment and
  delivery plan ([southampton.gov.uk](https://southampton.gov.uk/children-families/early-years-and-childcare/childcare-providers/improving-early-years-practice/improving-quality/childcare-sufficiency-assessment)).

Today these are mostly spreadsheets, GIS analyst time and consultants' reports, refreshed once a year or less.

**Who pays (hypothesis, not yet tested with a buyer).**

| Customer | What they buy | Price hypothesis |
|---|---|---|
| Council public health / early years / planning teams | City licence: all uses, unlimited scenarios, yearly data refresh, exportable briefs for PNA and sufficiency reports | **£6,000 per council per year**, about a tenth of one outsourced PNA |
| Nursery groups, pharmacy operators, café chains | Site reports: coverage gain, competition, deprivation reach, flood flag | **£150 per site report**, or £2,000 per year per region |

First three customers to approach: Southampton City Council (Data Observatory, public health, early years),
a neighbouring authority (Portsmouth or Hampshire) using the same national data, and a regional nursery group
expanding under the wider childcare entitlements.

**Cost to run.**
- AI: one brief on Claude Haiku 5.5 ($0.10 / $0.50 per million input / output tokens) is about **0.02p**
  (≈1,500 in, ≈350 out, at $1 = £0.75). Even 1,000 briefs a month is about 25p. Estimate until the live
  test logs real token counts.
- Hosting: one small cloud VM per region, roughly **£20-£40 a month**, plus a few hours of analyst time
  per city per year to refresh the data. Inference is a rounding error; data upkeep is the real cost.

**What stops a big player copying it.** Honestly, not the data: it is all open. The defence is the
method and trust: deterministic, tested numbers, an audit that blocks any unverified figure, a refusal when
evidence is thin, and outputs shaped to the PNA and sufficiency reports councils already write. Being the
tool a council's own analysts have checked is hard to copy quickly.

**At 10x and 100x.** Every input is national open data (ONS, Census, IMD, NHS ODS, Environment Agency, OSM),
so a new English city is a config change and a data rebuild, with no new model training. The optimiser runs
in under 0.01 s per city, and AI cost grows linearly and stays tiny. What changes: OSM needs a mirrored extract
instead of the public Overpass API, walking-network distance (OSMnx) adds precompute per city, and each new
service type needs a register (Ofsted for childcare, NHS ODS for health). Scotland, Wales and NI need their own
deprivation indices.

## AI-generated vs pre-existing

The code in `src/` and `tests/` was written during the hackathon with an AI coding assistant (Claude),
directed and reviewed by the team. No pre-existing project code. Libraries: pandas, numpy, shapely, pyproj,
streamlit, folium, streamlit-folium, anthropic. All data is from the public sources above.
