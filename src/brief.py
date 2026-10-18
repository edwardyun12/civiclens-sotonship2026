"""Grounded planning brief (L1-L5).

The LLM never sees raw data and never computes anything. It receives ONLY a JSON of numbers the
engine already computed, plus source tags, and turns them into a short brief a planner can paste
into a report. Every number in the brief is then checked against that JSON (the numbers audit).
If the audit fails twice, or the API is unavailable, the app shows a plain template instead.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "briefs.jsonl"

MODEL = os.environ.get("BRIEF_MODEL", "claude-haiku-5-5")
# USD per million tokens (platform.claude.com/docs/en/about-claude/pricing, checked 17 Oct 2026)
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}
USD_TO_GBP = float(os.environ.get("USD_TO_GBP", "0.75"))  # ASSUMPTION: rough exchange rate

SOURCE_TAGS = {
    "census": "Census 2021 TS007A spread, scaled to ONS mid-2024 small area population estimates (ONS, OGL)",
    "imd": "English Indices of Deprivation 2019 (MHCLG, OGL)",
    "osm": "OpenStreetMap (ODbL)",
    "nhs": "NHS Organisation Data Service (OGL)",
    "flood": "Environment Agency Flood Map for Planning (OGL)",
    "assumption": "Jobs-per-facility assumption table (ours, unvalidated)",
    "engine": "Our coverage calculation (straight-line distance from Census 2021 Output Area centroids)",
}

SYSTEM = """You write short, neutral planning briefs for a city council officer.

Rules you must follow:
1. Use ONLY the numbers in the JSON you are given. Do not calculate, round differently, add, subtract or estimate any new number. If you want a number that is not in the JSON, leave it out.
2. Copy numbers exactly as they appear (you may add a % sign or 'm' unit, and thousands commas).
3. After each claim, add a source tag in square brackets using only these keys: [engine], [census], [imd], [osm], [nhs], [flood], [assumption].
4. Write 150 to 250 words in plain English. No headings except the four labels below, each on its own line followed by a short paragraph:
   Summary: / Who benefits: / Trade-offs and risks: / Limits:
5. Never call a site vacant, available or approved. This is decision support, not a decision.
6. Keep 'community need' and 'commercial viability' separate. Do not merge them into one verdict.
7. State the confidence label given in the JSON and its reasons in 'Limits:'.
8. If comparing scenarios, say which scenario newly covers the most people and whether the ranking was stable in the sensitivity check, using the JSON fields."""


# ------------------------------------------------------------------ payload
def build_payload(results: list[dict], sens: dict | None = None, extra: dict | None = None) -> dict:
    """The only thing the LLM sees. Keep it small and explicit."""
    keep = ["category_label", "demand_label", "site", "radius_m", "walk_minutes", "existing_facilities",
            "coverage_before_pct", "coverage_after_pct", "coverage_change_pct_points", "newly_covered",
            "mean_distance_before_m", "mean_distance_after_m", "catchment_demand", "nearest_existing_m",
            "competitors_within_400m", "cannibalisation_flag", "jobs_estimate", "jobs_range", "flood_zone3",
            "equity_most_deprived_40pct", "equity_most_deprived_40pct_share", "need_score", "viability_score",
            "confidence", "confidence_reasons"]
    scen = []
    for i, r in enumerate(results):
        s = {k: r[k] for k in keep if k in r}
        s["scenario"] = chr(65 + i)
        scen.append(s)
    p = {"scenarios": scen,
         "score_notes": "need_score and viability_score are 0-100 percentiles against every possible site in the city; weights are design choices, not validated",
         "data_years": {"census": 2021, "population_estimate": results[0].get("population_year", 2021) if results else 2021,
                        "imd": 2019},
         "definitions": {"most_deprived_share_pct": 40, "competition_radius_m": 400, "score_scale_max": 100,
                         "demand_age_band": "0-4", "sensitivity_weight_change_pct": 20},
         "sources": SOURCE_TAGS}
    if sens:
        p["sensitivity"] = {"radii_tested_m": list(sens["newly_covered_by_radius"].keys()),
                            "newly_covered_by_radius": {str(k): v for k, v in sens["newly_covered_by_radius"].items()},
                            "ranking_stable_across_radii_and_weights": sens["stable_need_ranking"] and sens["stable_coverage_ranking"]}
    if extra:
        p.update(extra)
    return p


# ------------------------------------------------------------------ L3 numbers audit
NUM_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
TAG_RE = re.compile(r"\[[^\]]*\]")


def _flatten_numbers(obj, out: set[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        for m in NUM_RE.findall(obj):
            out.add(float(m.replace(",", "")))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_numbers(k, out)
            _flatten_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _flatten_numbers(v, out)


def audit(text: str, payload: dict) -> dict:
    """Every number in the brief must equal a number in the payload, at the precision the brief used.
    Numbers inside [source tags] are ignored. Returns {'ok', 'checked', 'failed': [...]}."""
    allowed: set[float] = set()
    _flatten_numbers(payload, allowed)
    body = TAG_RE.sub(" ", text)
    found = NUM_RE.findall(body)
    failed = []
    for raw in found:
        n = float(raw.replace(",", ""))
        dec = len(raw.split(".")[1]) if "." in raw else 0
        if not any(round(v, dec) == n or abs(v - n) < 1e-9 for v in allowed):
            failed.append(raw)
    return {"ok": not failed and len(found) > 0, "checked": len(found), "failed": failed}


# ------------------------------------------------------------------ L2 refusal, L4 template
def refusal(payload: dict) -> str | None:
    bad = [s for s in payload["scenarios"] if s.get("confidence") == "Low"]
    if not bad:
        return None
    s = bad[0]
    reasons = "; ".join(s.get("confidence_reasons") or ["data too thin"])
    return (f"Insufficient evidence. The tool will not make a recommendation for {s['category_label'].lower()} "
            f"at this site because: {reasons}. What is missing: a fuller register of existing "
            f"{s['category_label'].lower()} sites. Add a better data source, then rerun.")


def template(payload: dict) -> str:
    lines = []
    for s in payload["scenarios"]:
        lines.append(
            f"Scenario {s['scenario']}: a new {s['category_label'].lower()} in {s['site']['ward']} would change "
            f"{s['walk_minutes']}-minute-walk coverage of {s['demand_label']} from {s['coverage_before_pct']}% to "
            f"{s['coverage_after_pct']}%, newly covering {s['newly_covered']:,} people "
            f"({s['equity_most_deprived_40pct_share']}% of them in the most deprived 40% of areas) [engine]. "
            f"There are {s['competitors_within_400m']} existing {s['category_label'].lower()} sites within 400 m [osm]. "
            f"Community need {s['need_score']}/100, commercial viability {s['viability_score']}/100. "
            f"Confidence: {s['confidence']}.")
    yr = payload.get("data_years", {}).get("population_estimate", 2021)
    lines.append(f"Limits: residents are {'Census 2021 counts' if yr == 2021 else f'ONS mid-{yr} estimates'} at Output Area "
                 "centroids; straight-line distances; score weights are "
                 "design choices, not validated; decision support only.")
    return "\n\n".join(lines)


# ------------------------------------------------------------------ L1 + L3 + L5
def _log(rec: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def cost_gbp(model: str, tin: int, tout: int) -> float:
    pin, pout = PRICES.get(model, PRICES["claude-haiku-5-5"])
    return (tin * pin + tout * pout) / 1e6 * USD_TO_GBP


def generate(payload: dict, client=None, model: str = MODEL) -> dict:
    """Returns {'text', 'mode': 'llm'|'template'|'refusal', 'audit', 'warning', 'tokens_in', 'tokens_out',
    'cost_gbp', 'attempts'}."""
    ref = refusal(payload)
    if ref:
        return {"text": ref, "mode": "refusal", "audit": audit(ref, payload) | {"ok": True},
                "warning": None, "tokens_in": 0, "tokens_out": 0, "cost_gbp": 0.0, "attempts": 0}

    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            t = template(payload)
            return {"text": t, "mode": "template", "audit": audit(t, payload),
                    "warning": "No API key set, so this is the plain template, not an AI brief.",
                    "tokens_in": 0, "tokens_out": 0, "cost_gbp": 0.0, "attempts": 0}
        import anthropic
        client = anthropic.Anthropic()

    msg = "Write the brief from this JSON. Use only these numbers.\n\n" + json.dumps(payload, indent=1)
    tin = tout = 0
    last_audit = None
    t0 = time.time()
    for attempt in (1, 2):
        try:
            resp = client.messages.create(model=model, max_tokens=700, system=SYSTEM,
                                          messages=[{"role": "user", "content": msg}])
        except Exception as ex:  # network, auth, rate limit: fall back, never crash the app
            t = template(payload)
            _log({"ts": _now(), "model": model, "error": str(ex)[:200]})
            return {"text": t, "mode": "template", "audit": audit(t, payload),
                    "warning": f"AI brief unavailable ({type(ex).__name__}); showing the plain template.",
                    "tokens_in": tin, "tokens_out": tout, "cost_gbp": cost_gbp(model, tin, tout), "attempts": attempt}
        tin += resp.usage.input_tokens
        tout += resp.usage.output_tokens
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        last_audit = audit(text, payload)
        if last_audit["ok"]:
            rec = {"ts": _now(), "model": model, "attempts": attempt, "tokens_in": tin, "tokens_out": tout,
                   "cost_gbp": round(cost_gbp(model, tin, tout), 6), "audit": last_audit,
                   "seconds": round(time.time() - t0, 2)}
            _log(rec)
            return {"text": text, "mode": "llm", "audit": last_audit, "warning": None,
                    "tokens_in": tin, "tokens_out": tout, "cost_gbp": cost_gbp(model, tin, tout), "attempts": attempt}
        # one retry, telling the model exactly which numbers were not in the data
        msg += (f"\n\nYour previous draft used numbers that are not in the JSON: {', '.join(last_audit['failed'])}. "
                "Rewrite it using only numbers that appear in the JSON.")
    t = template(payload)
    _log({"ts": _now(), "model": model, "attempts": 2, "tokens_in": tin, "tokens_out": tout,
          "cost_gbp": round(cost_gbp(model, tin, tout), 6), "audit": last_audit, "fallback": True})
    return {"text": t, "mode": "template", "audit": audit(t, payload),
            "warning": f"The AI brief failed the numbers audit twice (unverified: {', '.join(last_audit['failed'])}); "
                       "showing the plain template instead.",
            "tokens_in": tin, "tokens_out": tout, "cost_gbp": cost_gbp(model, tin, tout), "attempts": 2}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ U10 export
def export_markdown(payload: dict, brief: dict, sources: dict) -> str:
    rows = ["| Metric | " + " | ".join(f"Scenario {s['scenario']}" for s in payload["scenarios"]) + " |",
            "|---|" + "---|" * len(payload["scenarios"])]
    fields = [("Use", lambda s: s["category_label"]), ("Ward", lambda s: s["site"]["ward"]),
              ("Coverage before (%)", lambda s: s["coverage_before_pct"]),
              ("Coverage after (%)", lambda s: s["coverage_after_pct"]),
              ("Newly covered", lambda s: f"{s['newly_covered']:,}"),
              ("Of which most deprived 40% (%)", lambda s: s["equity_most_deprived_40pct_share"]),
              ("Competitors within 400 m", lambda s: s["competitors_within_400m"]),
              ("Community need (0-100)", lambda s: s["need_score"]),
              ("Commercial viability (0-100)", lambda s: s["viability_score"]),
              ("Jobs (assumption)", lambda s: s["jobs_estimate"]),
              ("Flood Zone 3", lambda s: {True: "Yes", False: "No", None: "Not checked"}[s.get("flood_zone3")]),
              ("Confidence", lambda s: s["confidence"])]
    for label, f in fields:
        rows.append(f"| {label} | " + " | ".join(str(f(s)) for s in payload["scenarios"]) + " |")
    a = brief["audit"]
    badge = (f"All {a['checked']} numbers verified against source data." if a["ok"]
             else f"{len(a['failed'])} of {a['checked']} numbers could not be verified.")
    src = "\n".join(f"- {v['title']}. {v['licence']}. Downloaded {v['downloaded']}." for v in sources.values())
    return (f"# Planning scenario brief\n\nGenerated {_now()} by the SotonShip planning simulator. "
            f"Decision support only.\n\n## Brief\n\n{brief['text']}\n\n_{badge}_\n\n## Key numbers\n\n"
            + "\n".join(rows) + f"\n\n## Sources\n\n{src}\n")
