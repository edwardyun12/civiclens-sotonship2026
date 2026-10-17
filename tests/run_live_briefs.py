"""Live AI brief test: 10 scenarios, real API calls, numbers-audit pass rate and real cost.

Run (needs ANTHROPIC_API_KEY):  python -m tests.run_live_briefs
Writes tests/live_brief_results.json and appends every call to logs/briefs.jsonl.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import brief as B  # noqa: E402
from src import engine as E  # noqa: E402

OUT = ROOT / "tests" / "live_brief_results.json"


def site_payload(city, cats, lat, lon):
    results = [E.evaluate_site(city, c, lat, lon) for c in cats]
    sens = E.sensitivity(city, [{"category": c, "lat": lat, "lon": lon} for c in cats])
    return B.build_payload(results, sens)


def optimiser_payload(city, cat):
    picks = E.optimise(city, cat, 3)
    results = [E.evaluate_site(city, cat, p["lat"], p["lon"]) for p in picks]
    return B.build_payload(results, extra={"optimiser": {
        "method": "greedy maximum coverage", "candidate_sites": len(city.oa),
        "coverage_before_pct": picks[0]["coverage_before_pct"],
        "coverage_after_all_pct": picks[0]["coverage_after_all_pct"]}})


def ward_payload(city, cats, ward):
    lat, lon = E.ward_centroid(city, ward)
    return site_payload(city, cats, lat, lon)


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY first.")
    city = E.load_city()
    scenarios = [
        ("Cafe, city centre", lambda: site_payload(city, ["cafe"], 50.9046, -1.4045)),
        ("Library vs cafe, Bitterne Park", lambda: site_payload(city, ["library", "cafe"], 50.9330, -1.3700)),
        *[(f"Optimiser top 3: {c}", (lambda c=c: optimiser_payload(city, c)))
          for c in ["nursery", "gp", "pharmacy", "cafe", "library"]],
        ("Nursery, Sholing ward centre", lambda: ward_payload(city, ["nursery"], "Sholing")),
        ("GP vs pharmacy, Redbridge ward centre", lambda: ward_payload(city, ["gp", "pharmacy"], "Redbridge")),
        ("Pharmacy, Bassett ward centre", lambda: ward_payload(city, ["pharmacy"], "Bassett")),
    ]
    rows = []
    for name, make in scenarios:
        try:
            payload = make()
        except E.EngineError as ex:
            print(f"SKIP {name}: {ex}")
            continue
        b = B.generate(payload)
        row = {"scenario": name, "mode": b["mode"], "attempts": b["attempts"],
               "audit_ok": b["audit"]["ok"], "numbers_checked": b["audit"]["checked"],
               "failed_numbers": b["audit"]["failed"], "tokens_in": b["tokens_in"],
               "tokens_out": b["tokens_out"], "cost_gbp": round(b["cost_gbp"], 6), "warning": b["warning"]}
        rows.append(row)
        print(f"{name:40s} {b['mode']:9s} attempts={b['attempts']} audit_ok={b['audit']['ok']} "
              f"numbers={b['audit']['checked']} cost=£{b['cost_gbp']:.6f}")

    llm = [r for r in rows if r["attempts"] > 0]
    summary = {
        "model": B.MODEL,
        "briefs_run": len(rows),
        "ai_briefs_attempted": len(llm),
        "passed_audit_first_try": sum(r["mode"] == "llm" and r["attempts"] == 1 for r in llm),
        "passed_audit_after_retry": sum(r["mode"] == "llm" and r["attempts"] == 2 for r in llm),
        "fell_back_to_template": sum(r["mode"] == "template" for r in llm),
        "numbers_checked_total": sum(r["numbers_checked"] for r in rows if r["mode"] == "llm"),
        "mean_tokens_in": round(sum(r["tokens_in"] for r in llm) / max(len(llm), 1)),
        "mean_tokens_out": round(sum(r["tokens_out"] for r in llm) / max(len(llm), 1)),
        "mean_cost_pence": round(sum(r["cost_gbp"] for r in llm) / max(len(llm), 1) * 100, 4),
        "total_cost_pence": round(sum(r["cost_gbp"] for r in llm) * 100, 4),
        "rows": rows,
    }
    OUT.write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1))
    print(f"Saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
