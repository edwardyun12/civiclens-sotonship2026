# sotonship2026

## Project Objective
Module A — Business ecosystem intelligence
Analyse which industries are growing or shrinking, where businesses cluster, how business births and deaths change, and where commercial activity appears concentrated.
Output: sector trends, commercial hotspots and neighbourhood comparisons.




Module B — Business gap and opportunity detector
Compare existing business categories with population needs, local demographics, transport access, vacancies and nearby competition.
Output: potential underserved services and business types worth investigating.




Module C — Urban planning scenario simulator
Let a planner explore what might happen if a vacant unit became a café, affordable workspace, childcare centre or health service, and compare possible outcomes.
Output: scenario comparisons for accessibility, service coverage, commercial diversity and potential jobs.




Module D — AI planning analyst
A user asks questions in ordinary language. The AI retrieves supporting statistics and planning documents, explains its analysis and recommends options with source links and uncertainty.
Output: a decision brief, evidence trail and recommendations for human review.


## Feature Ideas

## Module C: planning scenario simulator (branch `feature/simulator`)

Where should the next nursery, GP, pharmacy, café or library go in Southampton, and who benefits?
Setup, data sources and licences, what the AI does, test results and known limits are in
[docs/SIMULATOR.md](docs/SIMULATOR.md).

```bash
pip install -r requirements.txt
streamlit run src/app.py
```
