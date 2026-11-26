"""Combine independently measured components and retain evidence for every decision."""

from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timezone
from importlib.metadata import version
from pathlib import Path
import unicodedata

from career.files import CareerError, digest, identity

from .config import Rubric, load_rubric
from .match import Finding, concept_statements, is_negated, keyword_groups, requirement_finding, stuffing, title_alignment, usable, uses_concept
from .pdf import Document, contact_types, date_quality, extract
from .posting import Requirement, parse
from .text import fold, hits, matches, require_english

ENGINE_VERSION = "1.5.0"
SCORING_FILES = ("config.py", "engine.py", "match.py", "pdf.py", "posting.py", "practices.py", "text.py")
NOTICE = (
    "This is an independent ATS approximation. Its scores do not reproduce a proprietary ATS "
    "or estimate hiring probability."
)


def weighted(scores: dict, weights: dict[str, int]) -> float:
    applicable = [(score, weights[key]) for key, score in scores.items() if score is not None]
    total = sum(weight for _, weight in applicable)
    return sum(score * weight for score, weight in applicable) / total if total else 0.0


def breakdown(scores: dict, weights: dict[str, int]) -> dict:
    total = sum(weights[key] for key, score in scores.items() if score is not None)
    return {
        key: {
            "score": round(score, 2) if score is not None else None,
            "weight": weights[key],
            "effective_weight": round(100 * weights[key] / total, 2) if total and score is not None else 0,
            "contribution": round(score * weights[key] / total, 3) if total and score is not None else 0,
        }
        for key, score in scores.items()
    }


def engine_identity() -> str:
    package = Path(__file__).parent
    return identity({name: digest((package / name).read_bytes()) for name in SCORING_FILES})


def readiness(document: Document, rubric: Rubric, expected: tuple[str, ...]) -> dict:
    clean_pages = document.pages - len(set(document.empty_pages) | set(document.hidden_pages))
    visible_fraction = clean_pages / document.pages if document.pages else 0
    readable = [line for line in document.lines if not hits(line.text, rubric.category_cues["excluded"])]
    available_characters = sum(len(fold(line.text).replace(" ", "")) for line in readable)
    signal = min(1, available_characters / rubric.thresholds.min_text_characters)
    headings = {row["section"] for row in document.headings}
    populated = {line.section for line in readable}
    sections = {
        "experience_or_projects": bool(populated & {"experience", "projects"}),
        "education": "education" in populated if "education" in headings else None,
        "skills": "skills" in populated,
        "credentials": "credentials" in populated if "credentials" in headings else None,
    }
    if clean_pages:
        for key, present in sections.items():
            if present is False:
                document.issue(
                    f"missing_or_empty_{key}", f"The extracted resume has no populated {key.replace('_', ' ')} section.",
                    "Use a recognized heading and selectable text for any relevant content in this section.",
                )
    contacts = contact_types([line for line in readable if line.section == "header"])
    if clean_pages and not contacts:
        document.issue("contact_not_extracted", "No contact channel was recognized in the resume header.",
                       "Use a selectable email address, international phone number, or professional website.")
    corrupt = document.corrupt_characters / document.extracted_characters if document.extracted_characters else 0
    if corrupt:
        document.issue("garbled_characters", f"Extraction found {document.corrupt_characters} suspicious characters.",
                       "Inspect the PDF text and re-export with fonts that preserve Unicode.")
    if clean_pages and signal < 1:
        document.issue("sparse_text", "The extracted resume has less text than the readability reference threshold.",
                       "Check that contact information and substantive entries are selectable.")
    date = date_quality(document, rubric)
    section_scores = {key: None if present is None else 100 * present for key, present in sections.items()}
    readable_layout = document.pages - len(set(document.column_pages) | set(document.hidden_pages))
    scores = {
        "text": 100 * signal * visible_fraction,
        "structure": weighted(section_scores, rubric.readiness_sections),
        "contact": 100 if contacts else 0,
        "dates": date,
        "layout": 100 * readable_layout / document.pages if document.pages else 0,
        "characters": 100 * max(0, 1 - corrupt / rubric.thresholds.max_bad_character_fraction)
        if document.extracted_characters else 0,
    }
    if document.unreadable or not clean_pages:
        scores = {key: 0 if score is not None else None for key, score in scores.items()}
    observed = " ".join(line.text for line in document.lines)
    # Source assertions are a supplemental rendering diagnostic. PDF-only scores
    # use the same rules with or without access to a RenderCV source.
    missing = [phrase for phrase in expected if fold(phrase) not in fold(observed)]
    if missing:
        document.issue("source_text_missing", f"{len(missing)} expected text items were not found in the PDF.",
                       "Compare the extracted text with the source and correct any missing content.")
    return {
        "score": round(weighted(scores, rubric.weights["readiness"]), 2),
        "components": breakdown(scores, rubric.weights["readiness"]),
        "pages": document.pages,
        "usable_pages": clean_pages if not document.unreadable else 0,
        "characters": document.extracted_characters,
        "corrupt_characters": document.corrupt_characters,
        "recognized_headings": document.headings,
        "sections": {name: len(lines) for name, lines in document.sections.items() if name != "header"},
        "contact_channels": contacts,
        "source_text_check": {"expected_count": len(expected), "missing": missing} if expected else None,
        "issues": document.issues,
    }


def unique_evidence(items: list[dict], maximum: int) -> list[dict]:
    chosen = {}
    for item in items:
        chosen.setdefault((item["page"], item["line"]), item)
    return list(chosen.values())[:maximum]


def improvement(req: Requirement, result: Finding) -> tuple[str, str] | None:
    if result.status in {"MET", "NOT_APPLICABLE"}:
        return None
    if result.status == "NOT_MET":
        return "verify_gap", "Keep the stated limitation visible. Change it if a verified source supports the correction."
    if result.status == "UNCERTAIN":
        return "review", "Check the posting wording and the cited PDF text before changing the résumé."
    if result.status == "NOT_DEMONSTRATED":
        return "verify_gap", "Look for verified evidence that matches this requirement. Leave the gap open if the record supplies none."
    if req.kind == "years":
        return "clarify_evidence", "Show the confirmed dates and scope together, or state the duration supported by the career record."
    if req.kind in {"education", "credential", "language"}:
        return "clarify_evidence", "Show the verified field, validity, or proficiency alongside the qualification in its section."
    if result.evidence and all(item["basis"] in {"mention", "limited claim"} for item in result.evidence):
        return "clarify_evidence", "If the skill was used, cite the work under Experience or Projects with the action and its purpose."
    return "clarify_evidence", "Use the cited example to make the demonstrated action and scope explicit. Add outcomes or missing scope when the career record supports them."


def score_requirements(posting, lines, rubric: Rubric, as_of: date | None) -> list[tuple[dict, Finding]]:
    items = []
    for req in posting.requirements:
        result = requirement_finding(req, lines, rubric, as_of)
        points = rubric.status_points.get(result.status)
        bare = bool(result.evidence) and all(
            item["basis"] in {"mention", "limited claim"} or item["section"] == "skills" for item in result.evidence
        )
        result = replace(result, mention_only=result.mention_only or bare)
        if result.status == "PARTIALLY_MET" and result.mention_only:
            points = min(points, rubric.thresholds.mention_only_points)
        evidence = unique_evidence(result.evidence, rubric.thresholds.max_evidence_lines)
        guidance = improvement(req, result)
        items.append(({
            "id": req.id, "category": req.category, "kind": req.kind,
            "importance": {"required": "high", "preferred": "medium", "informational": "none"}[req.category],
            "original_requirement": req.original, "posting_line": req.line, "status": result.status,
            "points": points, "mention_only": result.mention_only, "evidence": evidence, "resume_sections": list(dict.fromkeys(row["section"] for row in evidence)),
            "explanation": result.explanation, "improvement_kind": guidance[0] if guidance else None,
            "recommended_improvement": guidance[1] if guidance else None,
        }, result))
    return items


def mean(values) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def coverage(rows: list[dict], category: str) -> dict:
    applicable = [row for row in rows if row["category"] == category]
    return {"total": len(applicable), "statuses": dict(Counter(row["status"] for row in applicable))}


def recommendations(issues: list[dict], flags: list[dict], rows: list[dict]) -> list[dict]:
    priority = {"review": 2, "clarify_evidence": 2, "verify_gap": 4}
    ordered = [
        {"priority": 0, "kind": "format", "source": item["code"], "suggestion": item["recommendation"]}
        for item in issues if item["severity"] != "info"
    ]
    ordered.extend(
        {"priority": 1, "kind": "repetition", "source": item["code"],
         "suggestion": "Consolidate the flagged text and keep the strongest evidence in context."}
        for item in flags
    )
    ordered.extend(
        {"priority": priority[row["improvement_kind"]] + (row["category"] == "preferred"),
         "kind": row["improvement_kind"], "source": row["id"],
         "suggestion": row["recommended_improvement"]}
        for row in rows if row["recommended_improvement"]
    )
    return sorted(ordered, key=lambda item: (item["priority"], item["source"]))


def evaluate(
    pdf: bytes, posting: bytes, rubric: Rubric | None = None, *,
    as_of: date | None = None, semantic: bool = True, expected: tuple[str, ...] = (),
) -> dict:
    rubric = rubric or load_rubric()
    if len(posting) > rubric.thresholds.max_posting_bytes:
        raise CareerError("job posting exceeds the configured size limit")
    raw_posting = posting.decode("utf-8-sig")
    if not raw_posting.strip():
        raise CareerError("job posting is empty")
    require_english(raw_posting, "The job posting")
    job = parse(raw_posting, rubric)
    document = extract(pdf, rubric)
    require_english(" ".join(line.text for line in document.lines), "The resume PDF")
    ats = readiness(document, rubric, expected)
    lines = usable(document, rubric)
    items = score_requirements(job, lines, rubric, as_of)
    rows = [row for row, _ in items]
    groups = keyword_groups(job, rubric)
    terms = list(dict.fromkeys(term for group in groups for term in group))
    keyword_flags = stuffing(lines, terms, rubric)
    if keyword_flags:
        # Repetition already signals padding, so bare mentions earn nothing on top of it.
        for row in rows:
            if row["status"] == "PARTIALLY_MET" and row["mention_only"]:
                row["points"] = 0
    matched = [term for term in terms if any(matches(line.text, term) and not is_negated(line.text) for line in lines)]
    keyword_coverage = [
        {"terms": list(group), "matched": [term for term in group if term in matched]} for group in groups
    ]
    missing = [" or ".join(group["terms"]) for group in keyword_coverage if not group["matched"]]
    demonstrated = {}
    for key, concept in rubric.concepts.items():
        if concept.kind != "skill":
            continue
        examples = [
            row.evidence("demonstrated use")
            for _, statement, rows in concept_statements(lines, concept.aliases)
            if uses_concept(statement, rubric) for row in rows
        ]
        if examples:
            demonstrated[concept.label] = unique_evidence(examples, rubric.thresholds.max_evidence_lines)
    applicable = [row for row in rows if row["points"] is not None]
    title, title_evidence = title_alignment(job.role, lines, rubric)
    # Keyword frequency never counts as additional coverage.
    literal = 100 * sum(bool(group["matched"]) for group in keyword_coverage) / len(groups) if groups else None
    job_scores = {
        "required": mean(row["points"] for row in applicable if row["category"] == "required" and row["kind"] != "responsibility"),
        "preferred": mean(row["points"] for row in applicable if row["category"] == "preferred"),
        "responsibilities": mean(row["points"] for row in applicable if row["category"] == "required" and row["kind"] == "responsibility"),
        "title": title,
        "keywords": literal,
    }
    unadjusted = weighted(job_scores, rubric.weights["job_match"])
    penalty = min(rubric.thresholds.max_stuffing_penalty, rubric.thresholds.stuffing_penalty_per_flag * len(keyword_flags))
    eligibility_cap = 100 if applicable else rubric.thresholds.max_match_without_requirements
    matched_score = max(0, min(eligibility_cap, unadjusted) - penalty)
    if not lines:
        matched_score = 0
    contextual = None
    if semantic:
        assessed = [finding for row, finding in items if row["points"] is not None]
        semantic_scores = {
            "demonstration": mean(finding.demonstration for finding in assessed),
            "transferability": mean(max(finding.demonstration, finding.transferable) for finding in assessed),
            "depth": mean(finding.depth for finding in assessed),
        }
        contextual = {
            "score": round(weighted(semantic_scores, rubric.weights["semantic"]), 2),
            "method": "contextual-rules",
            "model_version": None,
            "components": breakdown(semantic_scores, rubric.weights["semantic"]),
            "finding_details": {
                row["id"]: {
                    "demonstration": round(finding.demonstration, 2),
                    "transferable_evidence": round(finding.transferable, 2),
                    "depth": round(finding.depth, 2),
                } for row, finding in items if row["points"] is not None
            },
        }
    overall_scores = {"readiness": ats["score"], "job_match": round(matched_score, 2)}
    config = {"rubric": rubric.model_dump(mode="json"), "as_of": as_of.isoformat() if as_of else None}
    report = {
        "schema_version": 1,
        "engine": {
            "version": ENGINE_VERSION, "sha256": engine_identity(),
            "pdf_parser": f"pypdf {version('pypdf')}", "unicode_version": unicodedata.unidata_version,
        },
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
        "inputs": {"pdf_sha256": digest(pdf), "posting_sha256": digest(posting)},
        "configuration": {"version": rubric.version, "sha256": identity(config), **config},
        "role": job.role, "notice": NOTICE,
        "overall": {"score": round(weighted(overall_scores, rubric.weights["overall"]), 2),
                    "components": breakdown(overall_scores, rubric.weights["overall"])},
        "ats_readiness": ats,
        "job_match": {
            "score": round(matched_score, 2), "components": breakdown(job_scores, rubric.weights["job_match"]),
            "before_adjustments": round(unadjusted, 2), "eligibility_cap": eligibility_cap,
            "stuffing_penalty": penalty, "title_evidence": title_evidence,
            "no_usable_evidence": not lines,
        },
        "semantic_fit": contextual,
        "requirements": rows,
        "coverage": {kind: coverage(rows, kind) for kind in ("required", "preferred")},
        "keywords": {"matched": matched, "missing": missing, "groups": keyword_coverage},
        "demonstrated_technical_skills": demonstrated,
        "relevant_experience": unique_evidence([
            item for row in applicable for item in row["evidence"]
            if item["section"] in {"experience", "projects", "achievements"}
            and item["basis"] not in {"explicit contradiction", "mention", "limited claim"}
        ], rubric.thresholds.max_evidence_lines * 2),
        "gaps": [row["id"] for row in applicable if row["status"] != "MET"],
        "keyword_stuffing_warnings": keyword_flags,
        "recommendations": recommendations(ats["issues"], keyword_flags, rows),
    }
    return report
