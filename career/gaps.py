"""Measure how well verified career facts cover a posting before any draft exists."""

from datetime import date

from evaluation.config import Rubric, load_rubric
from evaluation.engine import score_requirements
from evaluation.pdf import Line
from evaluation.posting import parse
from evaluation.text import require_english

from .knowledge import Knowledge
from .models import Credential, DatedRecord, Language, Milestone, Skill

SECTION = {
    "experience": "experience", "volunteer": "experience", "project": "projects",
    "achievement": "achievements", "other": "achievements", "education": "education",
    "certification": "credentials", "training": "credentials", "skill": "skills", "language": "languages",
}


def display_date(value: str | None) -> str:
    return "Present" if value == "present" else (value or "").replace("-", "/")


def heading(record) -> str:
    parts = [record.title]
    if organization := getattr(record, "organization", None):
        parts[0] += f", {organization}"
    if isinstance(record, DatedRecord) and record.start_date:
        end = display_date(record.end_date) if record.end_date else ""
        parts.append(f"{display_date(record.start_date)} - {end}".rstrip(" -"))
    elif isinstance(record, (Credential, Milestone)) and record.date:
        parts.append(display_date(record.date))
    if isinstance(record, Language):
        parts[0] += f" {record.proficiency}"
    return " ".join(parts)


def knowledge_lines(knowledge: Knowledge) -> tuple[list[Line], dict[int, str]]:
    """Lay verified records out like a single-column resume, remembering each line's source."""
    lines: list[Line] = []
    sources: dict[int, str] = {}

    def add(section: str, text: str, source: str) -> None:
        number = len(lines) + 1
        lines.append(Line(1, number, section, text))
        sources[number] = source

    for record_id, record in sorted(knowledge.records.items()):
        section = SECTION.get(record.kind)
        if section is None or record.status != "verified":
            continue
        if isinstance(record, Skill):
            add(section, " | ".join([record.title, *record.aliases]), record_id)
            continue
        add(section, heading(record), record_id)
        for fact in record.facts:
            if fact.status == "verified":
                add(section, f"• {fact.text}", f"{record_id}#{fact.id}")
    return lines, sources


def gaps(knowledge: Knowledge, posting: str, *, as_of: date | None = None, rubric: Rubric | None = None) -> dict:
    rubric = rubric or load_rubric()
    require_english(posting, "The job posting")
    job = parse(posting, rubric)
    lines, sources = knowledge_lines(knowledge)
    rows = []
    for row, _ in score_requirements(job, lines, rubric, as_of):
        if row["points"] is None:
            continue
        rows.append({
            "id": row["id"], "category": row["category"], "kind": row["kind"],
            "requirement": row["original_requirement"], "status": row["status"],
            "sources": list(dict.fromkeys(sources[item["line"]] for item in row["evidence"] if item.get("line") in sources)),
            "explanation": row["explanation"],
        })
    order = {"NOT_MET": 0, "NOT_DEMONSTRATED": 1, "UNCERTAIN": 2, "PARTIALLY_MET": 3, "MET": 4}
    rows.sort(key=lambda row: (row["category"] != "required", order.get(row["status"], 2), row["id"]))
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = summary.setdefault(row["category"], {})
        bucket[row["status"]] = bucket.get(row["status"], 0) + 1
    return {
        "role": job.role,
        "notice": "Coverage of verified facts only. Add or confirm facts with maintain-career before drafting.",
        "summary": summary,
        "requirements": rows,
    }
