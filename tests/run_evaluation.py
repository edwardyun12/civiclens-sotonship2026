"""Evidence for the README and pitch (T1, T2, T5). Run: python -m tests.run_evaluation

1. Baseline comparison: for each use, compare 3 candidate wards. Our pick = most residents newly
   covered within a 10 minute walk. Baseline pick = fewest competitors within 400 m (the spreadsheet answer).
2. Optimiser timing and coverage gains per use.
Writes tests/baseline_results.csv and tests/evaluation_summary.json.
"""
import json
import time
from pathlib import Path

import pandas as pd

from src import config as C
from src import engine as E

OUT = Path(__file__).parent

# Candidate wards per use: a city-centre ward, a suburban ward and an outer ward (chosen before running).
CASES = [
    ("cafe", ["Bargate", "Portswood", "Redbridge"]),
    ("cafe", ["Bevois", "Shirley", "Sholing"]),
    ("nursery", ["Bargate", "Bevois", "Sholing"]),
    ("nursery", ["Portswood", "Millbrook", "Woolston"]),
    ("gp", ["Bargate", "Redbridge", "Coxford"]),
    ("gp", ["Swaythling", "Harefield", "Peartree"]),
    ("pharmacy", ["Bevois", "Bitterne Park", "Coxford"]),
    ("pharmacy", ["Freemantle", "Bassett", "Woolston"]),
    ("library", ["Bargate", "Peartree", "Redbridge"]),
    ("library", ["Bitterne", "Freemantle", "Swaythling"]),
]


def main():
    city = E.load_city()
    rows = []
    for i, (cat, wards) in enumerate(CASES, 1):
        sites = [E.ward_centroid(city, w) for w in wards]
        res = [E.evaluate_site(city, cat, lat, lon) for lat, lon in sites]
        ours = max(range(3), key=lambda k: (res[k]["newly_covered"], res[k]["need_score"]))
        base = E.baseline_rank(city, cat, sites)
        rows.append({
            "case": i, "use": cat, "wards": " / ".join(wards),
            "newly_covered": " / ".join(str(r["newly_covered"]) for r in res),
            "competitors_400m": " / ".join(str(r["competitors_within_400m"]) for r in res),
            "most_deprived_40pct_newly": " / ".join(str(r["equity_most_deprived_40pct"]) for r in res),
            "our_pick": wards[ours], "baseline_pick": wards[base], "differs": ours != base,
            "people_gained_vs_baseline": res[ours]["newly_covered"] - res[base]["newly_covered"],
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "baseline_results.csv", index=False)

    opt = {}
    for cat in C.CATEGORIES:
        t = time.perf_counter()
        p = E.optimise(city, cat, 3)
        opt[cat] = {"seconds": round(time.perf_counter() - t, 3),
                    "coverage_before_pct": p[0]["coverage_before_pct"] if p else None,
                    "coverage_after_top3_pct": p[0]["coverage_after_all_pct"] if p else None,
                    "top3_wards": [x["ward"] for x in p]}
    summary = {"baseline_cases": len(df), "baseline_differs": int(df.differs.sum()),
               "people_gained_vs_baseline_total": int(df.people_gained_vs_baseline.sum()),
               "optimiser": opt}
    (OUT / "evaluation_summary.json").write_text(json.dumps(summary, indent=2))
    pd.set_option("display.width", 220)
    print(df.drop(columns=["most_deprived_40pct_newly"]).to_string(index=False))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
