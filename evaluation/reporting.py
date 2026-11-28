"""Render independent evaluation reports and compare like-for-like scores."""

import html
import json
import math
from pathlib import Path

from career.files import CareerError, identity, write_json

JSON_REPORT = "ats-evaluation.json"
MARKDOWN_REPORT = "ats-evaluation.md"
SCORES = {
    "overall": "Overall deterministic compatibility",
    "ats_readiness": "ATS readiness",
    "job_match": "Job match",
    "semantic_fit": "Semantic fit",
}
IMPROVEMENT_LABELS = {
    "format": "Fix parsing or formatting",
    "repetition": "Review repeated text",
    "clarify_evidence": "Clarify evidence",
    "review": "Review the finding",
    "verify_gap": "Verify the qualification",
}


def clean(text: str) -> str:
    """Quote untrusted document text without introducing HTML or Markdown."""
    text = html.escape(" ".join(text.split()))
    return "".join("\\" + char if char in r"\`*_[]|!#" else char for char in text)


def score_text(score: float | None) -> str:
    return "N/A" if score is None else f"{score:.2f}"


def evidence_text(row: dict) -> str:
    return f"Page {row['page']}, line {row['line']}, {clean(row['section'])} ({clean(row['basis'])}) — {clean(row['quote'])}"


def evaluation_markdown(report: dict) -> str:
    engine = report["engine"]
    configuration = report["configuration"]
    lines = [
        "# Independent ATS evaluation", "", report["notice"], "",
        f"- Evaluated at {report['evaluation_timestamp']}",
        f"- Evaluator {engine['version']} · {engine['pdf_parser']}",
        f"- Evaluator SHA-256 `{engine['sha256']}`",
        f"- Rubric {configuration['version']} with SHA-256 `{configuration['sha256']}`",
        f"- Reference date {configuration['as_of'] or 'unspecified'}",
        f"- Resume SHA-256 `{report['inputs']['pdf_sha256']}`",
        f"- Posting SHA-256 `{report['inputs']['posting_sha256']}`",
    ]
    if report["role"]:
        lines.append(f"- Posting role · {clean(report['role'])}")
    lines.extend(["", "## Scores", "", "| Metric | Score out of 100 |", "| --- | ---: |"])
    for key, label in SCORES.items():
        score = report[key]["score"] if report[key] is not None else None
        lines.append(f"| {label} | {score_text(score)} |")
    lines.extend(["", "Weights are redistributed among applicable components. Semantic fit is reported separately.", ""])
    job = report["job_match"]
    lines.append(f"Job Match started at {job['before_adjustments']:.2f}, with a cap of {job['eligibility_cap']} "
                 f"and a stuffing deduction of {job['stuffing_penalty']} points.")
    if job["no_usable_evidence"]:
        lines.append("Usable professional evidence was unavailable, so Job Match received zero points.")
    for key, label in SCORES.items():
        block = report[key]
        if block is None:
            continue
        lines.extend(["", f"### {label} calculation", "",
                      "| Component | Score | Configured weight | Effective weight | Points |",
                      "| --- | ---: | ---: | ---: | ---: |"])
        for name, value in block["components"].items():
            lines.append(f"| {name.replace('_', ' ')} | {score_text(value['score'])} | {value['weight']}% | "
                         f"{value['effective_weight']:.2f}% | {value['contribution']:.3f} |")
    if report["semantic_fit"]:
        lines.extend(["", "Semantic fit uses versioned contextual rules. No model version applies."])
    lines.extend(["", "## Qualification coverage", ""])
    for kind, details in report["coverage"].items():
        counts = ", ".join(f"{key} {value}" for key, value in sorted(details["statuses"].items())) or "none"
        lines.append(f"- **{kind.title()}** · {details['total']} requirements · {counts}")
    lines.extend(["", "## Requirement evidence", ""])
    for row in report["requirements"]:
        lines.extend([
            f"### {row['id']} · {row['status']} · {row['category']} / {row['kind']}", "",
            f"Posting line {row['posting_line']} · Importance {row['importance']} · {clean(row['original_requirement'])}", "",
            clean(row["explanation"]), "",
        ])
        lines.extend(f"- {evidence_text(item)}" for item in row["evidence"])
        if row["recommended_improvement"]:
            lines.extend(["", clean(row["recommended_improvement"])])
        lines.append("")
    lines.extend(["## Keywords and technical evidence", ""])
    for name in ("matched", "missing"):
        summary = ", ".join(map(clean, report["keywords"][name])) or "none"
        lines.append(f"- **{name.title()} keywords** · {summary}")
    for group in report["keywords"].get("groups", []):
        if len(group["terms"]) > 1:
            choices = " or ".join(map(clean, group["terms"]))
            found = ", ".join(map(clean, group["matched"])) or "none"
            lines.append(f"- **Alternative keywords** · {choices} · Found {found}")
    lines.append("- **Open requirement IDs** · " + (", ".join(report["gaps"]) or "none"))
    lines.extend(["", "### Demonstrated skills", ""])
    for skill, evidence in report["demonstrated_technical_skills"].items():
        lines.append(f"- **{clean(skill)}**")
        lines.extend(f"  - {evidence_text(item)}" for item in evidence)
    if not report["demonstrated_technical_skills"]:
        lines.append("No configured technical skill was demonstrated in an extractable experience or project statement.")
    lines.extend(["", "### Relevant professional experience", ""])
    lines.extend(f"- {evidence_text(item)}" for item in report["relevant_experience"])
    if not report["relevant_experience"]:
        lines.append("No relevant experience excerpts were identified.")
    if job["title_evidence"]:
        lines.extend(["", "### Historical title evidence", ""])
        lines.extend(f"- {evidence_text(item)}" for item in job["title_evidence"])
    ats = report["ats_readiness"]
    lines.extend(["", "## PDF parsing and formatting", "",
                  f"Usable pages {ats['usable_pages']} of {ats['pages']}. Extracted characters {ats['characters']}.",
                  f"Contact channels · {', '.join(ats['contact_channels']) or 'none'}.",
                  "Sections · " + (", ".join(f"{section} ({count} lines)" for section, count in ats["sections"].items()) or "none"), ""])
    lines.extend(f"- **{item['severity'].upper()}** · {clean(item['detail'])}" for item in ats["issues"])
    if not ats["issues"]:
        lines.append("No parsing or layout warnings.")
    if source := ats["source_text_check"]:
        lines.extend(["", f"Source text assertions · {source['expected_count'] - len(source['missing'])} "
                      f"of {source['expected_count']} found."])
        lines.extend(f"- Missing · {clean(phrase)}" for phrase in source["missing"])
    lines.extend(["", "### Keyword stuffing warnings", ""])
    lines.extend(f"- {clean(item['detail'])} {evidence_text(item['evidence'])}" for item in report["keyword_stuffing_warnings"])
    if not report["keyword_stuffing_warnings"]:
        lines.append("No threshold-based repetition warnings.")
    if check := report.get("cross_check"):
        lines.extend(["", "### Parser cross-check", "", "Diagnostic only. It does not affect any score.", ""])
        for name, row in check["readers"].items():
            if row["available"]:
                lines.append(f"- {name} · token agreement {row['token_agreement']:.0%} · order agreement {row['order_agreement']:.0%}")
            else:
                lines.append(f"- {name} · not installed")
        if check["note"]:
            lines.append(f"- **WARNING** · {check['note']}")
    lines.extend(["", "## Prioritized improvements", ""])
    for index, item in enumerate(report["recommendations"], 1):
        label = IMPROVEMENT_LABELS.get(item.get("kind"))
        heading = f"{label} · {item['source']}" if label else item["source"]
        lines.append(f"{index}. **{clean(heading)}** · {clean(item['suggestion'])}")
    if not report["recommendations"]:
        lines.append("No scoring-related changes were identified.")
    lines.extend(["", "The JSON report preserves the complete rubric and all requirement evidence."])
    return "\n".join(lines) + "\n"


def write_evaluation(directory: Path, report: dict) -> None:
    write_json(directory / JSON_REPORT, report)
    (directory / MARKDOWN_REPORT).write_text(evaluation_markdown(report), encoding="utf-8")


def check_report(report: dict) -> None:
    if report["schema_version"] != 1:
        raise CareerError("unsupported evaluation report schema version")
    config = report["configuration"]
    snapshot = {"rubric": config["rubric"], "as_of": config["as_of"]}
    if config["sha256"] != identity(snapshot) or config["version"] != snapshot["rubric"]["version"]:
        raise CareerError("evaluation configuration does not match its recorded identity")
    for key in SCORES:
        block = report[key]
        if key == "semantic_fit" and block is None:
            continue
        score = block["score"]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
            raise CareerError(f"invalid {key} score in evaluation report")


def read_report(path: Path) -> dict:
    report = json.loads(path.read_bytes())
    check_report(report)
    return report


def compare(first: dict, second: dict) -> dict:
    check_report(first)
    check_report(second)
    if first["inputs"]["posting_sha256"] != second["inputs"]["posting_sha256"]:
        raise CareerError("comparison requires the same original posting bytes")
    differences = []
    if first["configuration"]["sha256"] != second["configuration"]["sha256"]:
        differences.append(f"configuration ({first['configuration']['sha256'][:12]} vs {second['configuration']['sha256'][:12]})")
    for key in ("version", "sha256", "pdf_parser", "unicode_version"):
        a, b = first["engine"][key], second["engine"][key]
        if a != b:
            differences.append(f"{key} ({a} vs {b})")
    if differences:
        raise CareerError("evaluation methods differ: " + ", ".join(differences) + ". Reevaluate under the same settings.")
    baseline = {row["id"]: row for row in first["requirements"]}
    candidate = {row["id"]: row for row in second["requirements"]}
    if baseline.keys() != candidate.keys() or any(
        (baseline[key]["original_requirement"], baseline[key]["category"]) !=
        (candidate[key]["original_requirement"], candidate[key]["category"]) for key in baseline
    ):
        raise CareerError("reports disagree on the requirements extracted from the same posting")
    scores = {}
    for key in SCORES:
        old = first[key]["score"] if first[key] is not None else None
        new = second[key]["score"] if second[key] is not None else None
        scores[key] = {"baseline": old, "candidate": new,
                       "delta": None if old is None or new is None else round(new - old, 2)}
    changes = [
        {"id": key, "requirement": row["original_requirement"], "category": row["category"],
         "from": baseline[key]["status"], "to": row["status"],
         "evidence": row["evidence"], "explanation": row["explanation"]}
        for key, row in candidate.items() if baseline[key]["status"] != row["status"]
    ]
    old_issues = {row["code"]: row for row in first["ats_readiness"]["issues"]}
    new_issues = {row["code"]: row for row in second["ats_readiness"]["issues"]}
    old_skills = first["demonstrated_technical_skills"].keys()
    new_skills = second["demonstrated_technical_skills"].keys()
    return {
        "schema_version": 1,
        "posting_sha256": first["inputs"]["posting_sha256"],
        "baseline_pdf_sha256": first["inputs"]["pdf_sha256"],
        "candidate_pdf_sha256": second["inputs"]["pdf_sha256"],
        "configuration": {"version": first["configuration"]["version"], "sha256": first["configuration"]["sha256"]},
        "engine": first["engine"],
        "scores": scores,
        "improved_scores": [key for key, value in scores.items() if value["delta"] is not None and value["delta"] > 0],
        "regressed_scores": [key for key, value in scores.items() if value["delta"] is not None and value["delta"] < 0],
        "baseline_readiness": first["ats_readiness"]["components"],
        "candidate_readiness": second["ats_readiness"]["components"],
        "baseline_semantic": first["semantic_fit"]["components"] if first["semantic_fit"] else None,
        "candidate_semantic": second["semantic_fit"]["components"] if second["semantic_fit"] else None,
        "requirement_changes": changes,
        "newly_demonstrated_requirements": [row["id"] for row in changes if row["to"] == "MET"],
        "newly_demonstrated_skills": sorted(new_skills - old_skills),
        "lost_demonstrated_skills": sorted(old_skills - new_skills),
        "remaining_gaps": [row for row in candidate.values() if row["id"] in second["gaps"]],
        "new_formatting_issues": [new_issues[key] for key in sorted(new_issues.keys() - old_issues.keys())],
        "resolved_formatting_issues": [old_issues[key] for key in sorted(old_issues.keys() - new_issues.keys())],
    }


def comparison_markdown(report: dict) -> str:
    lines = [
        "# Resume version comparison", "",
        f"Posting SHA-256 `{report['posting_sha256']}`",
        f"Baseline PDF SHA-256 `{report['baseline_pdf_sha256']}`",
        f"Candidate PDF SHA-256 `{report['candidate_pdf_sha256']}`",
        f"Rubric {report['configuration']['version']} · `{report['configuration']['sha256']}`",
        "", "| Metric | Baseline | Candidate | Change |", "| --- | ---: | ---: | ---: |",
    ]
    for key, scores in report["scores"].items():
        change = "N/A" if scores["delta"] is None else f"{scores['delta']:+.2f}"
        lines.append(f"| {SCORES[key]} | {score_text(scores['baseline'])} | {score_text(scores['candidate'])} | {change} |")
    lines.extend(["", "## Requirement changes", ""])
    lines.extend(f"- **{row['id']}** · {row['from']} → {row['to']} · {clean(row['requirement'])}"
                 for row in report["requirement_changes"])
    if not report["requirement_changes"]:
        lines.append("Requirement statuses match.")
    lines.extend(["", "## Newly demonstrated qualifications and skills", "",
                  "- Requirements · " + (", ".join(report["newly_demonstrated_requirements"]) or "none"),
                  "- Skills · " + (", ".join(map(clean, report["newly_demonstrated_skills"])) or "none"),
                  "- Lost skill evidence · " + (", ".join(map(clean, report["lost_demonstrated_skills"])) or "none"),
                  "", "## Remaining gaps", ""])
    lines.extend(f"- **{row['id']}** · {row['status']} · {clean(row['original_requirement'])}"
                 for row in report["remaining_gaps"])
    if not report["remaining_gaps"]:
        lines.append("All assessed qualifications are demonstrated.")
    lines.extend(["", "## Changes in readability and context", ""])
    for heading, prefix in (("ATS readiness", "readiness"), ("Semantic fit", "semantic")):
        first, second = report[f"baseline_{prefix}"], report[f"candidate_{prefix}"]
        if first is None or second is None:
            lines.append(f"- {heading} could not be compared.")
            continue
        for key, component in first.items():
            a, b = component["score"], second[key]["score"]
            if a != b:
                lines.append(f"- {heading} · {key.replace('_', ' ')} · {score_text(a)} → {score_text(b)}")
    for change, key in (("New", "new_formatting_issues"), ("Resolved", "resolved_formatting_issues")):
        lines.extend(f"- {change} PDF finding · {clean(item['detail'])}" for item in report[key])
    return "\n".join(lines) + "\n"
