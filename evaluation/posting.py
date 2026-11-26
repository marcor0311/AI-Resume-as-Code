"""Parse the original posting into evidence-checkable requirement clauses."""

import re
from dataclasses import dataclass
from decimal import Decimal

from .config import Rubric
from .text import BULLET, YEARS, body, fold, hits, matches

SENIORITY = re.compile(r"\b(senior|staff|principal|lead|director|manager|junior|jr)\b")
DEGREE = re.compile(r"\b(degree|diploma)\b")
CREDENTIAL = re.compile(r"\b(certification|certified|certificate|credentials?|license|licensure)\b")
INFORMATION = re.compile(r"\b(salary|benefits?|compensation|vacation|apply now|about us|we offer)\b")
QUALIFICATION = re.compile(r"\b(experience|knowledge|degree|certified|proficiency|fluency|familiarity|expertise|qualification)\b")
DIRECTIVE = re.compile(
    r"\b(?:set the score|system prompt|output json|"
    r"(?:ignore|override|disregard)\b.{0,40}\b(?:instructions|requirements|criteria|rubric|scores?))\b"
)
ROLE_INTRO = re.compile(
    r"\b(?:as (?:a|an)|(?:seeking|hiring|looking for) (?:a|an))\s+"
    r"([^,;:.!?]+?)(?:\s+(?:to|you|who|will)\b|[,;:.!?])", re.I,
)
OPTIONAL_TENURE_SCOPE = re.compile(r"(?:[,;]\s*|\s+)\b(?:preferably|ideally)\b.*$")
RECRUITING_CLOSE = re.compile(
    r"^(?:we (?:welcome|encourage) (?:applications|candidates|you to apply)|if you are ready to apply)\b",
)


@dataclass(frozen=True)
class Requirement:
    id: str
    category: str
    kind: str
    original: str
    clause: str
    line: int
    concepts: tuple[str, ...] = ()
    alternative: bool = False
    years: Decimal | None = None


@dataclass(frozen=True)
class Posting:
    role: str | None
    requirements: list[Requirement]


def concepts_in(text: str, rubric: Rubric) -> tuple[str, ...]:
    ordered = []
    normalized = fold(text)
    for key, concept in rubric.concepts.items():
        aliases = [alias for alias in concept.aliases if matches(normalized, alias)]
        if aliases:
            first = min(normalized.find(fold(alias)) for alias in aliases)
            longest = max(len(fold(alias)) for alias in aliases)
            ordered.append((first, -longest, key))
    # A credential mention such as CKA is a credential. An embedded brand in its
    # full name should not silently become an extra job technology requirement.
    credential_text = [
        alias for _, _, key in ordered if rubric.concepts[key].kind == "credential"
        for alias in rubric.concepts[key].aliases if matches(normalized, alias)
    ]
    return tuple(key for _, _, key in sorted(ordered) if not (
        rubric.concepts[key].kind == "skill" and any(
            matches(credential_alias, alias)
            and not matches(normalized.replace(fold(credential_alias), " "), alias)
            for credential_alias in credential_text for alias in rubric.concepts[key].aliases
        )
    ))


def tenure_clause(clause: str) -> str:
    return OPTIONAL_TENURE_SCOPE.sub("", fold(clause))


def simple_alternative(req: Requirement) -> bool:
    return req.alternative and not hits(req.clause, ("and", "both"))


def _kind(clause: str, concepts: tuple[str, ...], block: str | None, rubric: Rubric) -> str:
    normalized = fold(clause)
    kinds = {rubric.concepts[key].kind for key in concepts}
    if block == "responsibilities":
        return "responsibility"
    if YEARS.search(normalized):
        return "years"
    if kinds == {"language"}:
        return "language"
    if kinds == {"education"} or DEGREE.search(normalized):
        return "education"
    if kinds == {"credential"} or CREDENTIAL.search(normalized):
        return "credential"
    if SENIORITY.search(normalized) and not concepts and hits(clause, rubric.category_cues["role_words"]):
        return "seniority"
    return "qualification"


def _posting_lines(raw: str):
    """Join indented or soft-wrapped continuations while preserving their original text."""
    current = []
    first = 0
    for number, line in enumerate(raw.splitlines(), 1):
        current_statement = current and BULLET.match(current[0])
        if current_statement and line.strip() and line[:1].isspace() and body(line) == line.strip():
            current.append(line.rstrip())
            continue
        if current:
            yield first, "\n".join(current)
            current = []
        if line.strip():
            first, current = number, [line]
    if current:
        yield first, "\n".join(current)


def parse(raw: str, rubric: Rubric) -> Posting:
    aliases = {fold(alias): kind for kind, terms in rubric.posting_sections.items() for alias in terms}
    cues = rubric.category_cues
    block = None
    role = None
    rows = []
    seen = set()
    for number, line in _posting_lines(raw):
        text = " ".join(body(line).split()).lstrip("# ").strip()
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        normalized = fold(text).rstrip(":")
        label, colon, tail = text.partition(":")
        heading = aliases.get(fold(label.rstrip())) if colon else aliases.get(normalized)
        if normalized in {"about the role", "description"}:
            block = None
            continue
        if not heading and len(text.split()) <= 7 and normalized.startswith("about ") and not colon:
            heading = "informational"
        if heading and not tail.strip():
            block = heading
            continue
        if (heading or block) == "title":
            role = (tail if heading else text).strip() or role
            if not heading:
                block = None
            continue
        if role is None and number <= 5 and 1 <= len(text.split()) <= 8 and (
            hits(text, cues["role_words"]) and not any(hits(text, cues[key]) for key in ("required", "preferred", "excluded"))
            and not QUALIFICATION.search(normalized) and not heading and block is None
        ):
            role = text
            continue
        if role is None and not BULLET.match(line) and block in {None, "informational"}:
            for match in ROLE_INTRO.finditer(text):
                candidate = match[1].strip()
                if len(candidate.split()) <= 8 and hits(candidate, cues["role_words"]):
                    role = candidate
                    break
            if role and not heading:
                block = "informational"
        clause = tail.strip() if heading else text
        current = heading or block
        if heading == "informational" or (not BULLET.match(line) and RECRUITING_CLOSE.search(normalized)):
            block = "informational"
            category = "informational"
        elif (current == "informational" or hits(clause, cues["excluded"]) or DIRECTIVE.search(fold(clause))
              or (current is None and INFORMATION.search(fold(clause)))):
            category = "informational"
        elif heading == "preferred" or hits(tenure_clause(clause) if YEARS.search(fold(clause)) else clause, cues["preferred"]):
            category = "preferred"
        elif current in {"required", "responsibilities"} or hits(clause, cues["required"]):
            category = "required"
        elif current == "preferred":
            category = "preferred"
        elif QUALIFICATION.search(fold(clause)):
            category = "required"
        else:
            category = "informational"
        concept_ids = concepts_in(clause, rubric) if category != "informational" else ()
        kind = "informational" if category == "informational" else _kind(clause, concept_ids, current, rubric)
        logic = tenure_clause(clause) if kind == "years" else clause
        if kind == "years":
            concept_ids = concepts_in(logic, rubric)
        minimum = YEARS.search(logic) if kind == "years" else None
        key = category, kind, fold(clause)
        if key in seen:
            continue
        seen.add(key)
        rows.append(Requirement(
            f"r{len(rows) + 1:03d}", category, kind, line, clause, number, concept_ids,
            hits(logic, cues["alternatives"]), Decimal(minimum[1].replace(",", ".")) if minimum else None,
        ))
    if role and (hits(role, cues["excluded"]) or DIRECTIVE.search(fold(role))):
        role = None
    return Posting(role, rows)
