"""Check job and evidence contracts, then project a draft into RenderCV input."""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import get_args

from .files import CareerError, contains, digest, identity, normalized, require_unique
from .knowledge import Knowledge
from .models import Analysis, Claim, Credential, DatedRecord, Draft, Education, Entry, Experience, Language, QualityDimension, Review, Skill, Volunteer

SECTIONS = {
    "summary": "Summary", "experience": "Experience", "project": "Projects",
    "education": "Education", "certification": "Certifications", "achievement": "Achievements",
    "language": "Languages", "training": "Training", "other": "Additional Experience",
    "skill": "Technical Skills", "volunteer": "Volunteer Experience",
}

QUALITY_DIMENSIONS = get_args(QualityDimension)

NUMBER = re.compile(
    r"(?<!\w)(?:[+\-−$€£¥]\s*)?\d+(?:[.,/'’]\d+)*(?:[ \u00a0\u202f]\d{3}(?!\d))*"
    r"(?:\s*[%‰]|(?:st|nd|rd|th|[kKmMbBxX+]))?(?!\w)"
)


def numbers(text: str) -> set[str]:
    return {re.sub(r"\s+", "", match.group().replace("−", "-")) for match in NUMBER.finditer(text)}


def validate_analysis(posting: str, analysis: Analysis) -> None:
    require_unique((item.id for item in analysis.requirements), "requirement IDs")
    require_unique((normalized(term) for term in analysis.keywords), "keywords")
    folded = " ".join(posting.split())
    for requirement in analysis.requirements:
        quote = " ".join(requirement.quote.split())
        if not quote or quote not in folded:
            raise CareerError(f"{requirement.id}: quote must appear in the original posting")
    for keyword in analysis.keywords:
        if not contains(posting, keyword):
            raise CareerError(f"{keyword!r}: keyword must appear in the original posting")


@dataclass
class Projection:
    knowledge: Knowledge
    document: dict = field(default_factory=dict)
    claims: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)

    def source(self, record_id: str, key: str) -> str:
        record = self.knowledge.verified(record_id)
        self.sources[record_id] = self.knowledge.sources[record_id]
        value = str(getattr(record, key))
        reference = f"{record_id}.{key}"
        self.evidence[reference] = {"text": value, "record": record_id, "field": key}
        return reference

    def add(self, path: str, text: str, evidence: list[str], expected: str | None = None) -> None:
        self.claims[path] = {
            "text": text, "evidence": evidence, "expected_pdf_text": expected or text,
        }

    def use_fact(self, reference: str):
        fact = self.knowledge.fact(reference)
        record_id = reference.split("#", 1)[0]
        self.sources[record_id] = self.knowledge.sources[record_id]
        self.evidence[reference] = {
            "text": fact.text, "record": record_id, "sources": fact.sources, "mentions": fact.mentions,
        }
        for linked in fact.sources:
            source = self.knowledge.verified(linked)
            self.source(linked, "title")
            if source.excerpt:
                self.source(linked, "excerpt")
            if source.attachment:
                self.source(linked, "attachment")
        for linked in fact.mentions:
            self.source(linked, "title")
        return fact

    def narrative(self, path: str, claim: Claim, parent: str | None = None) -> None:
        require_unique(claim.evidence, f"{path}.evidence")
        if parent and any(ref.split("#", 1)[0] != parent for ref in claim.evidence):
            raise CareerError(f"{path}: highlights must cite facts recorded under {parent}")
        facts = [self.use_fact(ref) for ref in claim.evidence]
        missing = numbers(claim.text) - set().union(*(numbers(fact.text) for fact in facts))
        if missing:
            raise CareerError(f"{path}: unsupported numeric tokens: {', '.join(sorted(missing))}")
        registry = [
            record for record in self.knowledge.records.values()
            if isinstance(record, Skill) or record.kind in {"certification", "training"}
        ]
        for record in registry:
            terms = [record.title, *record.aliases]
            if any(contains(claim.text, term) for term in terms):
                supported = any(
                    record.id in fact.mentions or any(contains(fact.text, term) for term in terms)
                    for fact in facts
                )
                if not supported or record.status != "verified":
                    raise CareerError(f"{path}: unsupported or unverified term {record.title!r}")
        self.add(path, claim.text, claim.evidence)


def render_entry(projection: Projection, path: str, entry: Entry, draft: Draft) -> dict:
    record = projection.knowledge.verified(entry.record)
    values = {}

    def copy(output_field: str, source_field: str) -> None:
        if value := getattr(record, source_field):
            values[output_field] = value
            projection.add(f"{path}/{output_field}", value, [projection.source(record.id, source_field)])

    if isinstance(record, (Experience, Volunteer)):
        copy("position", "title")
        copy("company", "organization")
    elif isinstance(record, Education):
        copy("area", "title")
        copy("institution", "organization")
        copy("degree", "degree")
    else:
        copy("name", "title")

    dates = []
    date_evidence = []
    date_fields = ("start_date", "end_date") if isinstance(record, DatedRecord) else ("date",)
    for name in date_fields:
        if value := getattr(record, name, None):
            if value != "present" and value > draft.as_of[:len(value)]:
                raise CareerError(f"{record.id}.{name}: date follows the resume's as_of date")
            dates.append(value.replace("-", "/"))
            date_evidence.append(projection.source(record.id, name))
    if dates:
        display_date = " - ".join(dates)
        # RenderCV treats a four-digit string differently from a year integer.
        values["date"] = int(display_date) if re.fullmatch(r"[1-9][0-9]{3}", display_date) else display_date
        projection.add(f"{path}/date", display_date, date_evidence)
    if isinstance(record, DatedRecord):
        copy("location", "location")
    if isinstance(record, Credential):
        copy("summary", "organization")
        if record.expires:
            expiry = f"Expiration: {record.expires.replace('-', '/')}"
            values["highlights"] = [expiry]
            projection.add(f"{path}/highlights/0", expiry, [projection.source(record.id, "expires")])
    if isinstance(record, Language):
        copy("summary", "proficiency")

    for claim in entry.highlights:
        highlights = values.setdefault("highlights", [])
        projection.narrative(f"{path}/highlights/{len(highlights)}", claim, record.id)
        highlights.append(claim.text)
    return values


def project(knowledge: Knowledge, draft: Draft) -> Projection:
    projection = Projection(knowledge)
    profile = knowledge.verified(draft.profile)
    if profile.kind != "profile":
        raise CareerError("draft profile must reference a profile record")
    require_unique((entry.record for entry in draft.entries), "resume entries")
    require_unique(draft.skills, "resume skills")

    cv = {"name": profile.title}
    projection.add("/cv/name", profile.title, [projection.source(profile.id, "title")])
    for name in ("email", "phone", "location", "website"):
        if value := getattr(profile, name):
            text = str(value)
            cv[name] = text
            expected = text.removeprefix("https://").removeprefix("http://").rstrip("/") if name == "website" else text
            projection.add(f"/cv/{name}", text, [projection.source(profile.id, name)], expected)

    titles = SECTIONS
    sections = {}
    if draft.summary:
        title = titles["summary"]
        sections[title] = [claim.text for claim in draft.summary]
        for index, claim in enumerate(draft.summary):
            projection.narrative(f"/cv/sections/{title}/{index}", claim)
    substantive_kinds = {"experience", "project", "education", "achievement", "training", "certification", "volunteer", "other"}
    if not any(knowledge.verified(entry.record).kind in substantive_kinds for entry in draft.entries):
        raise CareerError("resume needs at least one experience, project, education, achievement, credential, or other entry")
    for entry in draft.entries:
        record = knowledge.verified(entry.record)
        if record.kind not in titles or record.kind == "skill":
            raise CareerError(f"{record.id}: kind {record.kind} cannot be in draft entries")
        title = titles[record.kind]
        section = sections.setdefault(title, [])
        section.append(render_entry(projection, f"/cv/sections/{title}/{len(section)}", entry, draft))

    if draft.skills:
        title = titles["skill"]
        sections[title] = []
        cited_facts = {ref: row for ref, row in projection.evidence.items() if "#" in ref}
        for i, skill_id in enumerate(draft.skills):
            skill = knowledge.verified(skill_id)
            if not isinstance(skill, Skill):
                raise CareerError(f"{skill_id}: draft.skills requires a skill record")
            refs = [
                ref for ref, row in cited_facts.items()
                if skill_id in row["mentions"] or any(contains(row["text"], term) for term in (skill.title, *skill.aliases))
            ]
            if not refs:
                raise CareerError(f"{skill_id}: a listed skill needs support in a cited resume fact")
            sections[title].append({"bullet": skill.title})
            projection.add(f"/cv/sections/{title}/{i}/bullet", skill.title,
                           [projection.source(skill_id, "title"), *refs])

    cv["sections"] = sections
    projection.document = {
        "cv": cv,
        "design": {
            "theme": "engineeringresumes",
            "page": {"show_top_note": False},
            "header": {"connections": {"phone_number_format": "international"}},
        },
        "locale": {"language": draft.language},
        "settings": {"current_date": draft.as_of},
    }
    return projection


def review_input(projection: Projection, posting: bytes, analysis: Analysis) -> dict:
    packet = {
        "posting_sha256": digest(posting),
        "analysis": analysis.model_dump(mode="json"),
        "resume": projection.document,
        "section_order": list(projection.document["cv"]["sections"]),
        "claims": projection.claims,
        "evidence": projection.evidence,
        "sources": projection.sources,
    }
    return {"input_sha256": identity(packet), **packet}


def check_review(packet: dict, analysis: Analysis, review: Review) -> dict:
    if review.input_sha256 != packet["input_sha256"]:
        raise CareerError("review is stale. Review the current posting, draft, and cited sources.")
    require_unique((item.path for item in review.claims), "reviewed claims")
    require_unique((item.requirement for item in review.coverage), "reviewed requirements")
    if {item.path for item in review.claims} != packet["claims"].keys():
        raise CareerError("review must address every current resume claim exactly once")
    for item in review.claims:
        if item.verdict in {"unsupported", "needs_confirmation"}:
            raise CareerError(f"{item.path}: {item.verdict}. Remove, revise, or confirm the claim.")
        claim = packet["claims"][item.path]
        candidate_sources = [packet["evidence"][ref]["text"] for ref in claim["evidence"]]
        if item.verdict == "verbatim" and not any(claim["text"] == value for value in candidate_sources):
            raise CareerError(f"{item.path}: verbatim requires an exact source match")
    if {item.requirement for item in review.coverage} != {item.id for item in analysis.requirements}:
        raise CareerError("review must address every job requirement exactly once")
    if set(review.quality) != set(QUALITY_DIMENSIONS):
        raise CareerError("review must address all quality dimensions")
    for item in review.coverage:
        require_unique(item.claims, f"{item.requirement}.claims")
        if any(path not in packet["claims"] for path in item.claims):
            raise CareerError(f"{item.requirement}: coverage references a missing resume claim")
        if bool(item.claims) != (item.status in {"covered", "partial"}):
            raise CareerError(f"{item.requirement}: only covered or partial requirements cite claims")
    if review.disposition != "ready":
        raise CareerError("review disposition requests revision")
    result = {}
    for requirement in analysis.requirements:
        result.setdefault(requirement.kind, Counter())
    by_id = {item.id: item for item in analysis.requirements}
    for item in review.coverage:
        result[by_id[item.requirement].kind][item.status] += 1
    return result
