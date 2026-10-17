# Submission pack (Module C simulator)

Submissions lock **Sun 18 Oct 2026, 13:00**.

## 150-word summary (paste into the team page)

Southampton City Council must regularly decide where services are missing: pharmacies every three years
(the statutory Pharmaceutical Needs Assessment) and childcare every year. Today that means spreadsheets,
GIS time and consultants' reports costing tens of thousands of pounds. Our simulator lets a planner ask
"where should the next nursery, GP, pharmacy, café or library go?", or test a specific site. Using real
open data (Census 2021, deprivation, NHS and OpenStreetMap sites, flood zones), it shows who gains a
10-minute walk, how many live in the most deprived areas, nearby competition and flood risk, compared
with doing nothing. Three well-placed nurseries could raise under-5s' coverage from 60.2% to 76.7%. An
AI brief explains each result; every number is automatically checked against the data, and the tool
refuses when evidence is thin. Built entirely on national open data, it works for any English council
at about 0.02p per brief.

## Checklist

- [ ] Live brief test run on a PC (below), numbers added to `docs/SIMULATOR.md`
- [ ] Demo cache filled for the 3 rehearsed scenarios and committed (`data/cache/demo/*.json`)
- [ ] Real-user quote (only a real one; leave the slot out otherwise)
- [ ] Video 1:00-3:00, screen recording of the real app, YouTube public or unlisted
- [ ] Team page: summary, video link, pitch format (video only, or video + live), repo link, 2 members
- [ ] `feature/simulator` merged into `main` (with your teammate's agreement), repo public, no keys in history
- [ ] Root README points to `docs/SIMULATOR.md`

## Run on your PC: live AI brief test (handover item 1)

The cloud workspace can't install packages or reach the data sites this session, so run this locally
(Windows, in the repo folder, on `feature/simulator`):

```bat
git checkout feature/simulator && git pull
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
set ANTHROPIC_API_KEY=sk-ant-...
pytest -q
python -m tests.run_live_briefs
```

`run_live_briefs` runs 10 scenarios (café centre, library vs café, optimiser top 3 for all 5 uses, three
ward-centre tests) and saves `tests/live_brief_results.json`: audit pass rate (first try / after retry /
fallback), mean tokens and real cost per brief. It is new and has not been run yet, so watch the first
lines of output.

Then fill the demo cache: `streamlit run src/app.py` with **Demo mode off**, and open these three so each
brief is generated live once:
1. Test a site, Café, click or enter 50.9046, -1.4045 (city centre).
2. Find best sites, Nursery, top 3, 800 m.
3. Test a site, Library vs Café at 50.9330, -1.3700 (Bitterne Park).

Commit `tests/live_brief_results.json` and `data/cache/demo/*.json` (never `.env` or the key).

## Ofsted childcare register (handover item 2)

Download Ofsted's "Childcare providers and inspections: management information" (latest release) on your
PC and save the provider-level file into `Downloads\sotonship-data\`. A session with package access can
then add `--ofsted-file` to `fetch_data.py`, filter to Southampton, geocode postcodes and merge with OSM.
Check its licence (expected OGL v3.0) before use. Childminders' home addresses are not published, which is
fine: we only need group settings.
