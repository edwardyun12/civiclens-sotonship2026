# Data plan: from generic points to named businesses

Goal: every site in the simulator becomes a real, named place (shop, café, nursery, GP, pharmacy, library)
with its coordinates, operator, capacity where it exists, and a link to the company behind it. Areas get
richer population detail. Researched 17 Oct 2026. Licences checked on each source's own page.

## 1. Target database (SQLite or CSV, one file per table)

| Table | One row per | Key fields |
|---|---|---|
| `places` | Physical site (a shop, nursery, surgery) | `place_id`, `name`, `category`, `subcategory`, `lat`, `lon`, `postcode`, `address`, `brand`, `opening_hours`, `website`, `source`, `source_id`, `source_date` |
| `place_quality` | Place + measure | `place_id`, `measure` (hygiene rating, Ofsted grade, CQC rating), `value`, `date` |
| `place_capacity` | Place + measure | `place_id`, `measure` (registered places, registered patients, items dispensed), `value`, `period` |
| `organisations` | Legal entity | `company_number`, `company_name`, `status`, `incorporated`, `sic_codes`, `registered_postcode`, `accounts_type`, `last_accounts_date` |
| `org_financials` | Company + filed accounts | `company_number`, `period_end`, `turnover`, `employees`, `net_assets`, `profit`, `source_file` (most small firms only file some of these) |
| `place_org_link` | Place ↔ company match | `place_id`, `company_number`, `method` (name+postcode, brand, manual), `confidence` (0-1) |
| `area_stats` | Output Area or LSOA + measure | `area_code`, `measure`, `value`, `year`, `source` |
| `transport` | Bus stop / station | `atco_code`, `name`, `lat`, `lon`, `type` |
| `sources` | Dataset | `url`, `licence`, `downloaded`, `rows` (extends `data/raw/SOURCES.json`) |

Rule: the engine keeps reading `places` (coordinates + category) exactly as now, so nothing breaks. The extra
tables feed the map pop-ups, the comparison table and the brief.

## 2. Sources to use

### Named places and their details

| # | Source | What it adds | Access | Licence | Join key | Priority |
|---|---|---|---|---|---|---|
| P1 | **OpenStreetMap** (Overpass) | Every mapped shop and amenity in the city: name, `brand`, `brand:wikidata`, `opening_hours`, `website`, `phone`, address tags. Use all `shop=*`, `amenity=*`, `healthcare=*`, `office=*` inside the city boundary, not just 5 categories | Overpass query on your PC (blocked in the cloud workspace) | ODbL, attribute OSM contributors | `osm_id`; name + postcode | **Tonight** |
| P2 | **FSA Food Hygiene Ratings** | Every registered food business (cafés, restaurants, takeaways, shops, nurseries with kitchens, care homes): business name, type, address, postcode, lat/lon, hygiene rating and date, `FHRSID` | One file per council, updated daily: `https://ratings.food.gov.uk/api/open-data-files/FHRS{code}en-GB.xml`, or the national CSV `FHRS_All_en-GB.csv`; filter to Southampton | OGL v3 (don't use the FSA rating images or logo) | `FHRSID`; name + postcode | **Tonight** |
| P3 | **Ofsted childcare providers** (management information) | Every registered nursery and pre-school: name, provider type, postcode, **registered places**, latest inspection grade. Childminders' names and addresses are redacted | CSV on gov.uk, published twice a year (as at 31 Dec and 30 Jun) | OGL v3 | Ofsted URN; postcode → postcodes.io | **Tonight** (fixes the nursery undercount) |
| P4 | **NHS ODS** (already loaded) + **Patients Registered at a GP Practice** (NHS England, monthly) | Registered patients per practice, by age band: real GP **capacity / list pressure** | Monthly CSV on gov.uk statistics / NHS Digital | OGL v3 | ODS practice code | **Tonight** (fixes "no capacity" limit) |
| P5 | **NHSBSA pharmacy contractor dispensing data** | Items dispensed and services (e.g. Pharmacy First consultations) per pharmacy, monthly, 3-month lag | opendata.nhsbsa.net, CSV | OGL v3 | Pharmacy ODS code / address | Sunday if time |
| P6 | **CQC care directory** | GP surgeries, dentists, care homes: CQC rating and location | CQC API or directory CSV | Check CQC terms page | CQC location ID; ODS code | Later |
| P7 | **Public libraries in England dataset** (DCMS) | Library type and opening hours | data.gov.uk CSV | OGL | name + postcode | Skip: data is as at 2016. Keep OSM |

### Companies and their reports

| # | Source | What it adds | Access | Licence / terms | Notes |
|---|---|---|---|---|---|
| C1 | **Companies House free company data product** | Every live UK company: number, name, status, incorporation date, **SIC codes**, registered office postcode, accounts category and dates | Free monthly bulk CSV (large file; filter by SIC and by postcode prefix SO14-SO19) | Companies House sets no reuse rules; you must still follow data protection law | No shop address: registered office is often an accountant's address |
| C2 | **Companies House public data API** | Search by name, company profile, filing history, officers | Free API key; **600 requests per 5 minutes** | As above | Use for matching only. Don't store officers' names or addresses (personal data) |
| C3 | **Companies House accounts data product** | Filed accounts as iXBRL, about 60% of filings: turnover, employees, net assets, profit where filed | Free daily/monthly ZIPs | As above | Most local cafés and nurseries are micro-entities: they file a balance sheet only, **no turnover**. Many independents are sole traders and are not on Companies House at all. Chains report at group level (e.g. one set of accounts for all branches) |

**How a shop gets linked to a company** (there is no shared ID):
1. Chains: OSM `brand` / `brand:wikidata` → a hand-made table of ~30 brands → parent company number. Confidence 0.9.
2. Independents: FSA / OSM name + postcode → Companies House name search → accept if the normalised name matches
   and the registered office or a trading address is in the same postcode district. Confidence 0.5-0.8.
3. No match → stays unlinked (likely a sole trader). Show "No company record found", never guess.

### Area detail (population and context)

| # | Source | What it adds | Geography | Licence |
|---|---|---|---|---|
| A1 | **ONS small area population estimates, mid-2024** (released 7 Nov 2025) | Population by single year of age and sex, newer than Census 2021 | LSOA | OGL v3 |
| A2 | **Census 2021 TS045 car or van availability** | Share of households with no car: who really depends on walking distance | Output Area | OGL v3 |
| A3 | Census 2021 extras: TS003 household composition, TS066 economic activity, TS037 general health, TS021 ethnic group | Families with young children, working parents, health need | Output Area | OGL v3 |
| A4 | **ONS UK Business Counts** (IDBR, via Nomis, March 2026) | Number of businesses by 5-digit SIC and size band | MSOA (finest level) | OGL v3 |
| A5 | ONS Business demography | Business births, deaths and survival | Local authority | OGL v3 |
| A6 | **NaPTAN** bus stops and stations (DfT) | Public transport access to a site | Point | OGL, updated yearly |
| A7 | HM Land Registry Price Paid | House prices: affluence and new-build activity | Address | OGL (contains address data: aggregate to area) |
| A8 | English Indices of Deprivation 2025, if published, else IMD 2019 (current) | Deprivation | LSOA | OGL v3 |

## 3. Don't use

| Source | Why not |
|---|---|
| **VOA business rates list** (rateable value per property) | Its terms restrict use to non-domestic rating purposes and forbid passing it on. A public hackathon repo breaks that |
| Google Places / Maps API | Terms forbid storing results beyond place IDs, and it costs money. OSM + FSA cover the same names legally |
| Scraped review sites, LinkedIn, Apify scrapers | Licence and personal-data risk; hurts C5 |
| Companies House officers' names, home addresses, PSC data | Personal data we don't need. Store company-level facts only |
| Childminders | Ofsted redacts them for safety. Don't try to reconstruct them |

## 4. Order of work and effort (deadline Sun 13:00, freeze 09:15)

| When | Task | Where | Effort |
|---|---|---|---|
| Tonight | P2 FSA file for Southampton → `places` with names, type, rating | PC (file download) | 30 min |
| Tonight | P1 Overpass: all shops and amenities with name/brand/hours | PC | 30 min |
| Tonight | P3 Ofsted CSV → nurseries with registered places (replace OSM's 40) | PC | 45 min |
| Tonight | P4 GP registered patients → list size per surgery | PC | 30 min |
| Tonight | A2 car availability → "households without a car" in the who-benefits panel | PC (Nomis CSV) | 20 min |
| Sunday 07:00 | Map pop-ups with names, rating, capacity; competitors listed by name | Code | 1 h |
| Stretch | C1/C2 company matching for the top 30 brands + named independents | PC + code | 2 h+ |
| After the hackathon | C3 accounts parsing, P5, P6, A1, A4-A7 | | |

Everything in "Tonight" needs downloads that the cloud workspace can't reach, so run them on the PC and commit
the processed CSVs. Keep the 17 Oct versions in git history so the published test numbers stay reproducible,
and re-run `pytest` and `tests.run_evaluation` after swapping data (counts and coverage will change).

## 5. Sources

- FSA open data and API: https://ratings.food.gov.uk/open-data/ , terms: https://ratings.food.gov.uk/terms-and-conditions
- Ofsted childcare methodology (redaction, OGL): https://www.gov.uk/government/statistics/childcare-providers-and-inspections-as-at-31-march-2025/methodology-childcare-providers-and-inspections-as-at-31-march-2025
- Companies House data products: https://www.gov.uk/guidance/companies-house-data-products
- Companies House API rate limit: https://developer-specs.company-information.service.gov.uk/guides/rateLimiting
- VOA terms: https://www.tax.service.gov.uk/view-my-valuation/terms-and-conditions
- UK Business Counts (Nomis): https://nmweb.dur.ac.uk/datasets/idbrlu
- NHSBSA pharmacy dispensing data: https://opendata.nhsbsa.net/dataset/25230765-9494-4fde-b3fc-af9c00037dfb
- GP registered patients: https://www.gov.uk/government/statistics/patients-registered-at-a-gp-practice-february-2024 (monthly series)
- ONS small area population estimates: https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationestimates/bulletins/annualsmallareapopulationestimates/mid2023andmid2024revisedmid2022/relateddata
- Census 2021 TS045: https://www.ons.gov.uk/datasets/TS045
- NaPTAN: https://findtransportdata.dft.gov.uk/dataset/national-public-transport-access-nodes-17f0ce86368
- Public libraries dataset: https://www.data.gov.uk/dataset/public-libraries-in-england-basic-dataset
