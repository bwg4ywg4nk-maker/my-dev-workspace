"""Validate evidence and content before design is applied."""
import math
import re

class ValidationError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise ValidationError(message)

def validate(data):
    ev, content, plan, theme = (data[k] for k in ("evidence", "content", "presentation_plan", "theme"))
    groups = [ev["sources"], ev["evidence"], ev["calculations"], content["items"], content["charts"], content["metrics"], plan["slides"]]
    ids = [x["id"] for group in groups for x in group]
    require(len(ids) == len(set(ids)) and all(ids), "IDs must be unique and nonempty")
    require(ev["synthetic"] is True, "Fixture must be labeled synthetic")
    sources = {s["id"] for s in ev["sources"]}
    evidence = {e["id"]: e for e in ev["evidence"]}
    for e in evidence.values():
        require(e["source_id"] in sources, "Missing citation target")
        if "value" in e:
            require(type(e["value"]) in (int, float) and math.isfinite(e["value"]) and e["value"] >= 0, "Invalid quantitative value")
            require(e.get("unit") and type(e.get("sample_size")) is int and e["sample_size"] > 0, "Units and sample size required")
    for calc in ev["calculations"]:
        require(calc["operation"] in ("relative_reduction_percent", "absolute_difference"), "Unknown calculation")
        require(len(calc["input_ids"]) == 2 and all(i in evidence for i in calc["input_ids"]), "Missing calculation input")
        a, b = [evidence[i] for i in calc["input_ids"]]
        require(a["unit"] == b["unit"] and a["value"] > 0 and calc["unit"] == ("percent" if calc["operation"] == "relative_reduction_percent" else a["unit"]), "Calculation units or baseline invalid")
        expected = a["value"] - b["value"]
        if calc["operation"] == "relative_reduction_percent":
            expected = expected / a["value"] * 100
        require(math.isclose(calc["value"], expected, rel_tol=0, abs_tol=1e-9), "Incorrect calculation")
    refs = set(evidence) | {c["id"] for c in ev["calculations"]}
    for item in content["items"]:
        require(item["evidence_ids"] and all(i in refs for i in item["evidence_ids"]), "Unresolved claim evidence")
    for chart in content["charts"]:
        require(len(chart["categories"]) == len(chart["evidence_ids"]) == 2, "Invalid chart categories")
        require(all(i in evidence and evidence[i].get("unit") == chart["unit"] for i in chart["evidence_ids"]), "Invalid chart evidence or units")
    calculations = {c["id"]: c for c in ev["calculations"]}
    for metric in content["metrics"]:
        require(metric["calculation_id"] in calculations and metric["evidence_ids"] == [metric["calculation_id"]], "Invalid metric calculation")
        require(metric["label"] == "lower mean handling time\nB versus A", "Invalid metric wording")
    slides = plan["slides"]
    require([s["layout"] for s in slides] == ["hero", "context", "comparison", "chart", "interpretation", "references"], "Expected six ordered layouts")
    claims = {c["id"] for c in content["items"]}
    for slide in slides:
        require(set(slide) <= {"id", "layout", "principal_message", "content_ids", "purpose", "chart_id", "metric_id", "source_ids", "evidence_ids"}, "Plan contains unsupported design fields")
        require(all(i in claims for i in slide["content_ids"]), "Unresolved content")
        require(slide["principal_message"] and slide["purpose"], "Missing message or purpose")
        if slide["layout"] == "chart":
            require(slide.get("chart_id") in {c["id"] for c in content["charts"]}, "Unresolved chart")
        require(all(i in refs for i in slide["evidence_ids"]), "Unresolved headline evidence")
        capacity = {"hero": 2, "context": 3, "comparison": 3, "chart": 2, "interpretation": 4, "references": 0}
        require(len(slide["content_ids"]) <= capacity[slide["layout"]] and len(set(slide["content_ids"])) == len(slide["content_ids"]), "Invalid layout content capacity")
        if slide["layout"] == "hero":
            require(slide.get("metric_id") in {m["id"] for m in content["metrics"]}, "Unresolved metric")
        if slide["layout"] == "references":
            require(all(i in sources for i in slide["source_ids"]), "Unresolved reference")
    validate_fixture_prose(data)
    require(theme["font"] == "Arial", "Milestone 1 requires Arial")
    return data

def citation_sources(data, evidence_ids):
    ev = data["evidence"]
    sources = {e["id"]: [e["source_id"]] for e in ev["evidence"]}
    for calc in ev["calculations"]:
        sources[calc["id"]] = sorted({s for i in calc["input_ids"] for s in sources[i]})
    return sorted({s for i in evidence_ids for s in sources[i]})


def validate_fixture_prose(data):
    """Explicit M1 consistency rules, deliberately not a calculation language.

    Stored prose is accepted only when it matches authoritative quantities.
    This also rejects stale source totals and stale sample-size statements.
    """
    ev = {e["id"]: e for e in data["evidence"]["evidence"]}
    calc = {c["id"]: c for c in data["evidence"]["calculations"]}
    items = {c["id"]: c for c in data["content"]["items"]}
    sources = {s["id"]: s for s in data["evidence"]["sources"]}
    require({"E1", "E2", "E3"} <= ev.keys() and {"D1", "D2"} <= calc.keys(), "Missing fixture quantities")
    a, b = ev["E1"], ev["E2"]
    require(a["unit"] == b["unit"] == "minutes per case" and a["value"] > b["value"] > 0, "Invalid fixture values or units")
    require(type(a["sample_size"]) is int and type(b["sample_size"]) is int and a["sample_size"] == b["sample_size"], "Invalid fixture sample sizes")
    for id, operation in [("D1", "relative_reduction_percent"), ("D2", "absolute_difference")]:
        require(calc[id]["operation"] == operation and calc[id]["input_ids"] == ["E1", "E2"], "Invalid fixture derivation")
    for eid, cid, sid, letter in [("E1", "C5", "S1", "A"), ("E2", "C6", "S2", "B")]:
        e = ev[eid]
        require(e["source_id"] == sid, "Invalid fixture source relationship")
        require(items[cid]["evidence_ids"] == [eid], "Invalid quantitative claim provenance")
        require(items[cid]["text"] == f'{e["value"]:g} minutes per case; n = {e["sample_size"]}. Synthetic pilot {letter} log.', "Stale quantitative prose")
        require(sources[sid]["detail"] == f'Invented fixture; {e["sample_size"]} cases; total handling time {e["value"] * e["sample_size"]:g} minutes.', "Stale source detail")
    require({"E1", "E2"} <= set(items["C3"]["evidence_ids"]), "Missing sample provenance")
    require({"E1", "E2", "D1"} <= set(items["C1"]["evidence_ids"]), "Missing finding provenance")
    require(items["C3"]["text"] == f'Two synthetic pilots; {a["sample_size"]} cases each. Handling time is the only measured outcome.', "Stale sample prose")
    require(items["C8"]["text"] == f'B recorded {calc["D2"]["value"]:g} fewer minutes per case: ({a["value"]:g} − {b["value"]:g}) / {a["value"]:g} × 100 = {calc["D1"]["value"]:g}% lower than A.', "Stale quantitative prose")
    require(items["C8"]["evidence_ids"] == ["E1", "E2", "D1", "D2"], "Missing takeaway provenance")
    for slide in data["presentation_plan"]["slides"]:
        if slide["layout"] == "chart":
            require(slide["principal_message"] == f'B recorded {calc["D1"]["value"]:g}% lower mean handling time' and slide["evidence_ids"] == ["D1"], "Stale headline or missing provenance")
        elif slide["layout"] == "hero":
            require(slide["principal_message"] == items["C1"]["title"] == "Pilot B recorded lower handling time" and slide["evidence_ids"] == ["E1", "E2", "D1"], "Invalid hero headline provenance")

    # Numeric prose is permitted only in the explicitly validated fixture fields.
    for item in data["content"]["items"]:
        require(not re.search(r"[0-9]", item["title"]), "Unvalidated quantitative title")
        if item["id"] not in {"C3", "C5", "C6", "C8"}:
            require(not re.search(r"[0-9]", item["text"]), "Unvalidated quantitative prose")
    for source in data["evidence"]["sources"]:
        require(not re.search(r"[0-9]", source["title"]), "Unvalidated source title")
        if source["id"] not in {"S1", "S2"}:
            require(not re.search(r"[0-9]", source["detail"]), "Unvalidated source prose")
    for slide in data["presentation_plan"]["slides"]:
        if slide["layout"] != "chart":
            require(not re.search(r"[0-9]", slide["principal_message"]), "Unvalidated quantitative headline")
    for chart in data["content"]["charts"]:
        require(chart["title"] == "Mean handling time", "Unsupported fixture chart title")
        require(chart["categories"] == [{"E1": "Approach A", "E2": "Approach B"}.get(i) for i in chart["evidence_ids"]], "Chart category/evidence mismatch")
