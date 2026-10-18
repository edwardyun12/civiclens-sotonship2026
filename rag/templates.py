"""Deterministic answers for the assistant's built-in questions."""

from __future__ import annotations

import re


BUSINESS_PDF = "data/raw/project/southampton_business_opportunity_data.pdf"


def _line(context: str, prefix: str) -> str:
    return next((line.removeprefix(prefix) for line in context.splitlines() if line.startswith(prefix)), "")


def _pairs(text: str) -> list[tuple[str, str]]:
    return re.findall(r"(?:^|, )(.+?) ([\d,]+)(?=, |\.$|$)", text)


def _fmt(value: str) -> str:
    return f"{int(value.replace(',', '')):,}"


def _pdf_source(page: int) -> dict:
    citation = f"Southampton Business Opportunity Data, p. {page}"
    return {
        "citation": citation,
        "source": BUSINESS_PDF,
        "chunk": page,
        "preview": "Southampton Business & Place Evidence — Centres Study tables and quality notes.",
        "url": f"/api/evidence/{BUSINESS_PDF}#page={page}",
        "vectorScore": 1.0,
        "bm25Score": 1.0,
        "hybridScore": 1.0,
    }


def answer_template(question: str, context: str | None) -> tuple[str, list[dict]] | None:
    q = question.strip().lower()
    context = context or ""

    if q == "which areas have the most businesses?":
        rows = _pairs(_line(context, "Mapped trading places by ward: "))[:3]
        if rows:
            lead = rows[0]
            rest = ", ".join(f"{name} ({_fmt(count)})" for name, count in rows[1:])
            return f"{lead[0]} has the most mapped trading places, with {_fmt(lead[1])} [App analysis]. The next highest are {rest} [App analysis].", []

    if q == "where is commercial vacancy highest?":
        source = _pdf_source(6)
        return (
            "Windermere Avenue Local Centre has the highest recorded vacancy rate at 25%, "
            "but this is 2 vacant units out of only 8, so the percentage is sensitive to one unit "
            f"[{source['citation']}].",
            [source],
        )

    if q == "compare shirley and portswood.":
        counts = dict(_pairs(_line(context, "Mapped trading places by ward: ")))
        leaders = dict(re.findall(r"(?:^|; )([^:]+): ([^;]+)", _line(context, "All sectors. Leading sector per area: ")))
        source = _pdf_source(6)
        return (
            f"Portswood has {counts.get('Portswood', '255')} mapped trading places, compared with "
            f"{counts.get('Shirley', '198')} in Shirley. Portswood’s leading sector is "
            f"{leaders.get('Portswood', 'Food and drink')}, while Shirley’s is {leaders.get('Shirley', 'Retail')} "
            "[App analysis]. Shirley has the higher vacancy rate: 10.94% versus 6.45% in Portswood "
            f"[{source['citation']}].",
            [source],
        )

    if q == "which sectors lead across southampton’s wards?":
        leaders = re.findall(r"(?:^|; )([^:]+): ([^;]+)", _line(context, "All sectors. Leading sector per area: "))
        grouped: dict[str, list[str]] = {}
        for ward, sector in leaders:
            grouped.setdefault(sector.rstrip(". "), []).append(ward)
        if grouped:
            parts = [f"{sector}: {', '.join(wards)}" for sector, wards in sorted(grouped.items(), key=lambda item: -len(item[1]))]
            return "The ward-leading sectors are:\n\n- " + "\n- ".join(parts) + " [App analysis].", []

    if q == "which wards have the most people aged 16–24?":
        match = re.search(r"16–24: ([^;]+)", _line(context, "Age-group leaders by resident count: "))
        rows = _pairs(match.group(1) + ".") if match else []
        if rows:
            return "The wards with the most residents aged 16–24 are " + ", ".join(f"{name} ({_fmt(count)})" for name, count in rows) + " [App analysis].", []

    if q == "what is the evidence on southampton city centre?":
        source = _pdf_source(6)
        return (
            "The City Centre is Southampton’s largest listed centre, with 458 commercial units. "
            "Its recorded vacancy rate is 12.04%, and its footfall indicator is 9.6% below the comparison period "
            f"[App analysis] [{source['citation']}]. These are place indicators, not a forecast of business performance.",
            [source],
        )

    selected = _line(context, "Selected site in ")
    details = next((line for line in context.splitlines() if " direct competitors within " in line), "")
    strengths = _line(context, "Strengths: ")
    risks = _line(context, "Risks: ")
    changes = _line(context, "Suggested changes: ")
    business = re.search(r"Business: ([^.]+)", context)

    if q == "why is the top site the best place for my business?" and selected:
        site, score = selected.split(": feasibility ", 1)
        return f"The top site is in {site}, with feasibility {score.split('. Factors')[0]} [App analysis]. {strengths}", []

    if q == "how was my business idea matched to the data?" and business:
        matching = _line(context, "Business matching: ")
        matching = matching.rstrip(". ")
        matching = matching[:1].upper() + matching[1:]
        return f"Your idea was matched as {business.group(1)}. {matching} [App analysis].", []

    if q == "what are the main risks at this site?" and selected:
        if risks:
            return f"The model flags these risks: {risks} [App analysis].", []
        comp = re.search(r"(\d+) direct competitors within (\d+) m \((\d+) within 400 m\)", details)
        pressure = f" There are {comp.group(3)} direct competitors within 400 m, so differentiation still matters." if comp else ""
        return f"The model does not flag a major scored risk at this site.{pressure} This is not a guarantee: rents, live vacancies and observed footfall are not included [App analysis].", []

    if q == "how many competitors are near this site?":
        comp = re.search(r"(\d+) direct competitors within (\d+) m \((\d+) within 400 m\)", details)
        if comp:
            return f"There are {comp.group(1)} direct competitors within {comp.group(2)} m, including {comp.group(3)} within 400 m [App analysis].", []

    if q == "who would my customers be here?":
        page = re.search(r"Customers: ([^.]+)\. Walking distance (\d+) m", context)
        people = re.search(r"([\d,]+) target customers", details)
        if page and people:
            return f"The model targets people aged {page.group(1)}, with {_fmt(people.group(1))} target customers within {page.group(2)} m of the site [App analysis].", []

    if q == "what should i change to make this site work?" and changes:
        return f"{changes.rstrip('. ')} [App analysis].", []

    return None
