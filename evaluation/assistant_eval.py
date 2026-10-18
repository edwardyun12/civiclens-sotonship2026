"""Assistant evaluation: does document search find the right passage, and are the answers right and properly cited?

Each question is hand-labelled with a figure or phrase that only the right passage contains ("evidence"), the facts a
correct answer must state ("must"), and for out-of-scope questions what it must NOT do (invent a price).
Built-in common questions are excluded: those are answered by fixed templates (rag/templates.py), not the LLM.

Run from the repo root with the API running (`python run.py api`) on the provider you want to measure:
    python evaluation/assistant_eval.py              # retrieval + answers
    python evaluation/assistant_eval.py --retrieval  # retrieval only (no AI calls)
PAUSE seconds between questions (default 25) keeps the Groq free plan under its 8,000 tokens a minute.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag.config import CHAT_MODEL, EMBED_MODEL, LLM_PROVIDER  # noqa: E402
from rag.retriever import retrieve  # noqa: E402

API = os.getenv("API", "http://127.0.0.1:8000")
PAUSE = float(os.getenv("PAUSE", "25"))

# question, evidence that the right passage contains, facts the answer must state, pattern the answer must not contain
CASES = [
    ("What share of new Southampton businesses are still trading after three years, compared with England?", "35.2", ["35.2", "52.8"], None),
    ("What is the five-year business survival rate in Southampton?", "33.1", ["33.1"], None),
    ("How many businesses does Southampton have per 10,000 working-age residents, and how does England compare?", "653", ["421", "653"], None),
    ("By how much did new business registrations in Southampton fall in 2023?", "29.5", ["29.5"], None),
    ("Which sector lost the most enterprises in Southampton last year?", "155", ["retail"], None),
    ("What proportion of working-age people in Southampton were claiming out-of-work benefits in February 2025?", "7,910", ["4.5"], None),
    ("Is Southampton's claimant rate back to where it was before the pandemic?", "3.5%", ["3.5"], None),
    ("What share of economically active adults in Southampton hold only Level 3 qualifications?", "23.5", ["23.5"], None),
    ("How did footfall in Shirley change between 2023 and 2024?", "5,337", ["24"], None),
    ("Which of Southampton's centres saw footfall rise in 2024?", "4,268", ["lordshill"], None),
    ("What is the commercial vacancy rate in Portswood?", "6.45", ["6.45"], None),
    ("How many commercial units are there in Southampton city centre?", "458", ["458"], None),
    ("Which councils would make up the proposed Hampshire and the Solent mayoral combined county authority?", "Isle of Wight Council", ["portsmouth", "isle of wight", "hampshire"], None),
    ("How did Southampton City Council publicise the devolution consultation?", "16,300", ["facebook"], None),
    # out of scope: no rent data is indexed, so a good answer says so instead of inventing a price
    ("How much does it cost to rent a shop on Above Bar Street?", None, [], r"£\s?\d"),
    ("What will Southampton's population be in 2040?", None, [], r"\b2040\b[^.]*\b\d{3},\d{3}\b"),
]


def retrieval_hit(question: str, evidence: str | None) -> tuple[bool | None, list[str]]:
    results = retrieve(question, top_k=3)
    cites = [r["citation"] for r in results]
    if evidence is None:
        return None, cites
    return any(evidence.lower() in r["text"].lower() for r in results), cites


def ask(question: str) -> dict:
    req = urllib.request.Request(f"{API}/api/chat", data=json.dumps({"question": question}).encode(),
                                 headers={"Content-Type": "application/json"})
    t0, answer, sources, error = time.time(), [], [], None
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            for raw in r:
                line = raw.decode("utf-8").strip()
                if not line:
                    continue
                event = json.loads(line)
                if event.get("type") == "sources":
                    sources = event.get("sources", [])
                elif event.get("type") == "token":
                    answer.append(event.get("content", ""))
                elif event.get("type") == "error":
                    error = event.get("message")
    except (urllib.error.URLError, TimeoutError) as exc:
        error = str(exc)
    return {"answer": "".join(answer), "sources": [s.get("citation") for s in sources], "error": error,
            "seconds": round(time.time() - t0, 1)}


def check(answer: str, sources: list[str], must: list[str], must_not: str | None) -> dict:
    text = answer.lower()
    facts = all(m.lower() in text for m in must)
    allowed = set(sources) | {"App analysis"}
    labels = [label for label in re.findall(r"\[([^\]]+)\]", answer)]
    bad = [label for label in labels if label not in allowed]
    invented = bool(must_not and re.search(must_not, answer))
    return {"facts_ok": facts, "citations": labels, "invalid_citations": bad, "cited": bool(labels),
            "invented": invented, "correct": facts and not bad and not invented and bool(answer.strip())}


def main() -> None:
    answers = "--retrieval" not in sys.argv
    health = {}
    if answers:
        try:
            with urllib.request.urlopen(f"{API}/api/health", timeout=10) as r:
                health = json.load(r)
        except urllib.error.URLError:
            sys.exit(f"The API is not running at {API}. Start it with `python run.py api`.")
    rows = []
    for i, (question, evidence, must, must_not) in enumerate(CASES):
        hit, cites = retrieval_hit(question, evidence)
        row = {"question": question, "evidence": evidence, "retrieval_hit": hit, "top3": cites}
        if answers:
            if i:
                time.sleep(PAUSE)
            row.update(ask(question))
            row.update(check(row["answer"], row["sources"], must, must_not))
        rows.append(row)
        mark = lambda v: "Y" if v else ("-" if v is not None else " ")
        print(f"{mark(hit)} {mark(row.get('correct')) if answers else ''} {question[:70]}"
              + (f"  ERROR {row['error'][:80]}" if answers and row.get("error") else ""))

    in_scope = [r for r in rows if r["evidence"]]
    summary = {
        "run": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "provider": health.get("provider", LLM_PROVIDER),
        "chat_model": health.get("model", CHAT_MODEL), "search": EMBED_MODEL, "questions": len(rows),
        "retrieval_top3_hits": sum(bool(r["retrieval_hit"]) for r in in_scope), "retrieval_cases": len(in_scope),
    }
    if answers:
        done = [r for r in rows if not r.get("error")]
        secs = sorted(r["seconds"] for r in done)
        summary.update({
            "answers_correct": sum(r["correct"] for r in rows),
            "in_scope_correct": sum(r["correct"] for r in in_scope),
            "out_of_scope_no_invention": sum(not r["invented"] and not r.get("error") for r in rows if not r["evidence"]),
            "answers_with_invalid_citations": sum(bool(r.get("invalid_citations")) for r in rows),
            "errors": len(rows) - len(done),
            "rate_limited": sum("limit" in (r.get("error") or "").lower() or "429" in (r.get("error") or "") for r in rows),
            "mean_seconds": round(sum(secs) / len(secs), 1) if secs else None,
            "p90_seconds": secs[int(0.9 * (len(secs) - 1))] if secs else None,
        })
    summary["rows"] = rows
    name = f"assistant_eval_{summary['provider']}.json" if answers else f"retrieval_eval_{summary['search']}.json"
    out = ROOT / "evaluation" / "results" / name
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n" + json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1))
    print(f"Saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
