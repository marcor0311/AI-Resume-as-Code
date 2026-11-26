"""Score requirement evidence from visible PDF text and its local context."""

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from .config import Concept, Rubric
from .pdf import Document, Line
from .posting import Posting, Requirement, simple_alternative, tenure_clause
from .practices import Practice, practice_for
from .text import BULLET, DATE_TOKEN, YEARS, body, experience_days, fold, hits, matches, ranges, stamp, term_pattern, tokens

CONTEXT = {"experience", "projects", "achievements"}
INFLECTIONS = {
    "built": "build", "wrote": "write", "managed": "manage", "operated": "operate",
    "deployed": "deploy", "developed": "develop", "resolved": "resolve", "supported": "support",
    "maintained": "maintain", "tested": "test", "designed": "design", "implemented": "implement",
    "providing": "provide", "provided": "provide", "guided": "guide", "guiding": "guide",
    "collaborated": "collaborate", "collaborating": "collaborate", "mentored": "mentor",
    "assessed": "assess", "addressed": "address", "prioritized": "prioritize", "scheduled": "schedule",
    "delivered": "deliver", "fostered": "foster", "showcased": "showcase", "working": "work",
}
DURATION_CONTEXT = re.compile(r"\b(?:experience|working|using|worked|spent|tenure)\b")
NEGATIVE = re.compile(
    r"\b(?:no|not|never|without|lacks?)\b"
    r"(?!\s+(?:solo|solamente|only|just|longer))"
)
DIRECT_NEGATIVE = re.compile(
    r"^(?:(?:i|we)\s+)?(?:no|not|never|without|lack|lacks)\b"
    r"|\b(?:do not|does not|did not|not certified|never used|no experience)\b"
)
LIMITED_ACTION = r"studied|read about|observed|shadowed|watched|planned to learn|considered learning"
LIMITED_USE = re.compile(rf"\b(?:{LIMITED_ACTION})\b", re.I)
ASSERTION_BREAK = re.compile(rf"(?<=[.!?;])\s+|\s+(?:and|but)\s+(?=(?:{LIMITED_ACTION}|did not)\b)", re.I)
QUALIFICATION_DENIAL = re.compile(
    r"\b(?:no|without|lack|lacks|never used|never worked with|not certified in)\s+"
    r"(?:(?:prior|professional|production|enterprise|commercial|direct|hands-on|any)\s+)*"
    r"(?:experience\s+(?:in|with|using)\s+)?$"
    r"|\b(?:do not|does not)\s+(?:have|use|know|hold)\s+(?:any\s+)?$"
)
OUTCOME = re.compile(r"\b\d+(?:[.,]\d+)?\s*[%€$]|\b\d+\s+(?:users|teams|services|hours|minutes)\b")
DEGREE_SCOPE = re.compile(r"\bin\s+([^.;]+)")
OPEN_DISCIPLINE = re.compile(r"^(?:a\s+)?(?:similar|related|relevant|equivalent)\b")
RELATED_EDUCATION = (
    ("computer science", "computer engineering", "software engineering", "information systems", "information technology"),
    ("statistics", "applied mathematics", "mathematics", "data science"),
    ("electrical engineering", "electronics engineering", "electronic engineering"),
)
TECHNICAL_TITLE = re.compile(
    r"\b(?:engineer|architect|developer|programmer|technician|"
    r"(?:data|systems?|security|technical|infrastructure) (?:analyst|consultant|specialist))\b"
)
ACTIVE_CREDENTIAL = re.compile(r"\b(?:active|current|valid)\b")
EXPLICIT_EXPIRY = re.compile(r"\b(?:expired|expiration|expires)\b")
ACTION_AFTER_OUTCOME = re.compile(r"^(?:you will )?ensure .+? excellent experience by (.+)$")
ABILITY_TO = re.compile(r"\bwith the ability to (.+)$")
CONCURRENT_CUSTOMERS = re.compile(
    r"\bmultiple (?:customers|clients) concurrently\b|\bconcurrent (?:customer|client) engagements\b"
)
CUSTOMER_WORK = re.compile(r"^(?:you will )?work (?:directly )?with (concurrent customers)(?: to (.+))?$")
CLOUD_PROVIDER = re.compile(r"\b(?:aws|azure|gcp|google cloud|amazon web services)\b")
ABILITY_VERBS = {"foster", "showcase", "demonstrate", "coach"}


@dataclass
class Finding:
    status: str
    explanation: str
    evidence: list[dict] = field(default_factory=list)
    demonstration: float = 0
    transferable: float = 0
    depth: float = 0
    # Set when the only support is a bare mention, such as a skills list entry.
    mention_only: bool = False


def stems(text: str) -> set[str]:
    singular = (word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word
                for word in tokens(text))
    return {INFLECTIONS.get(word, word) for word in singular}


def overlap(text: str, target: str) -> float:
    expected = stems(target)
    return len(expected & stems(text)) / len(expected) if expected else 0


def contextual_overlap(text: str, target: str) -> float:
    text = CONCURRENT_CUSTOMERS.sub("concurrent customers", fold(text))
    target = CONCURRENT_CUSTOMERS.sub("concurrent customers", fold(target))
    if "cloud platforms and services" in target:
        target = target.replace("cloud platforms and services", "cloud services")
        text = CLOUD_PROVIDER.sub("cloud", text)
    return overlap(text, target)


def list_like(text: str, rubric: Rubric) -> bool:
    parts = re.split(r"[,;|]", body(text))
    openers = [re.match(r"^(?:and\s+)?(\w+)", fold(part)) for part in parts]
    verbs = rubric.category_cues["actions"]
    if openers[0] and openers[0][1] in verbs and any(match and match[1] in verbs for match in openers[1:]):
        return False
    return (
        len(parts) >= 3 and len(tokens(parts[0])) <= 5 and all(len(tokens(part)) <= 3 for part in parts[1:])
    ) or bool(re.match(r"^[^:]{1,30}:\s*[^,]+,", body(text)))


def action(line: Line, rubric: Rubric) -> bool:
    text = body(line.text)
    return (
        line.section in CONTEXT and len(tokens(text)) >= rubric.thresholds.min_context_words
        and hits(text, rubric.category_cues["actions"]) and not list_like(text, rubric)
    )


def usable(document: Document, rubric: Rubric) -> list[Line]:
    cues = rubric.category_cues
    return [
        line for line in document.lines
        if line.section not in {"header", "other"} and not hits(line.text, cues["excluded"])
        and not re.search(r"\b(system prompt|ignore .{0,30}instructions|set the score|output json)\b", fold(line.text))
    ]


def is_negated(text: str) -> bool:
    normalized = fold(body(text))
    if re.match(r"^(?:no|without)\s+(?:outages|incidents|regressions|downtime|errors)\b", normalized):
        return False
    return bool(DIRECT_NEGATIVE.search(normalized) and NEGATIVE.search(normalized))


def context_strength(line: Line, rubric: Rubric) -> int:
    points = rubric.semantic_points
    return points.outcome_depth if OUTCOME.search(fold(line.text)) else points.description_depth


def related_lines(lines: list[Line], index: int, count: int = 2) -> list[Line]:
    root = lines[index]
    return [
        neighbor for neighbor in lines[index:index + count + 1]
        if neighbor.section == root.section and neighbor.page == root.page and neighbor.number <= root.number + count
    ]


def use_text(lines: list[Line], index: int) -> tuple[str, list[Line]]:
    line = lines[index]
    if line.section not in CONTEXT or ranges(line.text):
        return line.text, [line]
    is_bullet = bool(BULLET.match(line.text))
    rows = [line]
    for neighbor in related_lines(lines, index, 4 if is_bullet else 1)[1:]:
        if (BULLET.match(neighbor.text) or ranges(neighbor.text) or neighbor.number != rows[-1].number + 1
                or (not is_bullet and rows[-1].text.endswith((".", "!", "?")))):
            break
        rows.append(neighbor)
    joined = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", "\n".join(row.text for row in rows))
    return " ".join(joined.split()), rows


def limited_use(text: str, rubric: Rubric) -> bool:
    return bool(LIMITED_USE.search(text) or hits(text, rubric.category_cues["non_evidence"]))


def concept_statements(lines: list[Line], aliases: list[str], *, structured_entry: bool = False):
    for index, line in enumerate(lines):
        if structured_entry:
            texts, rows = [line.text], [line]
        elif line.section == "skills":
            neighbors = related_lines(lines, index, 1)
            rows = [line] if len(neighbors) == 1 or BULLET.match(neighbors[1].text) else neighbors
            texts = [" ".join(row.text for row in rows)]
        else:
            text, rows = use_text(lines, index)
            texts = ASSERTION_BREAK.split(text)
        for text in texts:
            if hits(text, aliases):
                yield index, replace(line, text=text), rows


def uses_concept(statement: Line, rubric: Rubric) -> bool:
    return action(statement, rubric) and not is_negated(statement.text) and not limited_use(statement.text, rubric)


def _language_level(text: str, rubric: Rubric) -> int:
    return max((value for cue, value in rubric.language_levels.items() if matches(text, cue)), default=0)


def structured(concept: Concept, req: Requirement, lines: list[Line], index: int, rubric: Rubric, as_of: date | None) -> Finding:
    line = lines[index]
    points = rubric.semantic_points
    expected_section = {"education": "education", "credential": "credentials", "language": "languages"}[concept.kind]
    if line.section != expected_section:
        return Finding("PARTIALLY_MET", "The qualification is mentioned outside its recognized section.", [line.evidence("mention")])
    rows = [line]
    for neighbor in related_lines(lines, index)[1:]:
        if any(other.kind == concept.kind and hits(neighbor.text, other.aliases) for other in rubric.concepts.values()):
            break
        rows.append(neighbor)
    context = " ".join(row.text for row in rows)
    evidence = [line.evidence("structured qualification")]
    if concept.kind == "language":
        needed = _language_level(req.clause, rubric)
        # Level on the same line or immediately after the language name.
        rows = rows[:2]
        if len(rows) == 2 and not _language_level(rows[1].text, rubric):
            rows = [line]
        actual = _language_level(" ".join(row.text for row in rows), rubric)
        if needed and actual < needed:
            evidence = [row.evidence("language and stated level") for row in rows]
            status = "NOT_MET" if actual else "PARTIALLY_MET"
            return Finding(status, "The stated proficiency is below the posting's level." if actual else "The language is listed without the requested proficiency.", evidence)
        evidence = [row.evidence("language and stated level") for row in rows]
    elif concept.kind == "education":
        discipline = DEGREE_SCOPE.search(fold(req.clause))
        fields = []
        if discipline:
            field_text = discipline[1].strip()
            fields = re.split(r",\s*(?:or\s+)?|\s+or\s+", field_text) if simple_alternative(req) else [field_text]
            fields = [field for field in fields if not OPEN_DISCIPLINE.search(field) and tokens(field)]
        supported = next((field for field in fields if overlap(context, field) == 1), None)
        if not supported and any(OPEN_DISCIPLINE.search(part.strip()) for part in re.split(r",|\bor\b", fold(req.clause))):
            supported = next((related for family in RELATED_EDUCATION if any(field in family for field in fields)
                              for related in family if hits(context, (related,))), None)
            if supported:
                evidence = [line.evidence("degree and comparable field")]
        if fields and not supported:
            return Finding("PARTIALLY_MET", "The degree appears, but the required field is not clearly stated on its entry.", evidence, demonstration=points.incomplete_qualification)
        if supported and overlap(line.text, supported) < 1:
            evidence += [row.evidence("degree field") for row in rows[1:] if overlap(row.text, supported)]
    else:
        related = [row for row in rows[1:] if EXPLICIT_EXPIRY.search(fold(row.text))]
        expiry = DATE_TOKEN.search(fold(" ".join(row.text for row in related)))
        parsed_expiry = stamp(expiry.group()) if expiry else None
        explicit_expired = re.search(r"\b(?:expired)\b", fold(context))
        if explicit_expired or (parsed_expiry is not None and as_of and parsed_expiry.latest < as_of):
            return Finding("NOT_MET", "The credential is explicitly expired as of the available date.",
                           [*evidence, *(row.evidence("expiry") for row in related)])
        knows_valid = active_credential(context) or (parsed_expiry is not None and as_of and parsed_expiry.earliest >= as_of)
        if ACTIVE_CREDENTIAL.search(fold(req.clause)) and not knows_valid:
            return Finding("PARTIALLY_MET", "The named credential appears, but its current validity is not demonstrated.", evidence, demonstration=points.incomplete_qualification)
    return Finding("MET", "The qualification appears with the required context in its recognized section.", evidence, demonstration=points.demonstrated, depth=points.structured_entry_depth)


def active_credential(text: str) -> bool:
    return bool(ACTIVE_CREDENTIAL.search(fold(text)) and not is_negated(text))


def demonstrated_use(req: Requirement, line: Line, rows: list[Line], rubric: Rubric) -> Finding:
    points = rubric.semantic_points
    missing = [key.replace("_", " ") for key, aliases in rubric.scope_aliases.items()
               if hits(req.clause, aliases) and not hits(line.text, aliases)]
    evidence = [row.evidence("demonstrated use") for row in rows]
    if missing:
        return Finding("PARTIALLY_MET", "Use is demonstrated, but the requested scope is not explicit: " + ", ".join(missing) + ".",
                       evidence, demonstration=points.partial_use, depth=context_strength(line, rubric))
    return Finding("MET", "The resume describes using the skill in professional or project work.",
                   evidence, demonstration=points.demonstrated, depth=context_strength(line, rubric))


def contradicts(req: Requirement, line: Line, aliases: list[str], rubric: Rubric) -> bool:
    text = fold(body(line.text))
    narrow = any(hits(text, scope) and not hits(req.clause, scope) for scope in rubric.scope_aliases.values())
    if narrow:
        return False
    return any(QUALIFICATION_DENIAL.search(text[:match.start()]) for alias in aliases
               for match in term_pattern(alias).finditer(text))


def concept_finding(key: str, req: Requirement, lines: list[Line], rubric: Rubric, as_of: date | None) -> Finding:
    concept = rubric.concepts[key]
    points = rubric.semantic_points
    direct = []
    structured_entry = concept.kind in {"language", "education", "credential"}
    for index, line, rows in concept_statements(lines, concept.aliases, structured_entry=structured_entry):
        if is_negated(line.text):
            if contradicts(req, line, concept.aliases, rubric):
                direct.append(Finding("NOT_MET", "The resume explicitly states that this qualification is absent.",
                                      [row.evidence("explicit contradiction") for row in rows]))
            continue
        if limited_use(line.text, rubric) and not (
            concept.kind == "credential" and EXPLICIT_EXPIRY.search(fold(line.text))
        ):
            direct.append(Finding("PARTIALLY_MET", "The phrase describes familiarity, study, or interest without demonstrated use.",
                                  [row.evidence("limited claim") for row in rows], demonstration=points.mention,
                                  mention_only=True))
        elif structured_entry:
            direct.append(structured(concept, req, lines, index, rubric, as_of))
        elif action(line, rubric):
            direct.append(demonstrated_use(req, line, rows, rubric))
        else:
            direct.append(Finding("PARTIALLY_MET", "The term appears without a concrete example of application.",
                                  [row.evidence("mention") for row in rows], demonstration=points.mention,
                                  mention_only=True))
    if direct:
        order = {"MET": 3, "PARTIALLY_MET": 2, "NOT_MET": 1}
        best = max(direct, key=lambda finding: (order[finding.status], not finding.mention_only, finding.depth))
        negative = next((item for item in direct if item.status == "NOT_MET"), None)
        if negative and best.status != "NOT_MET":
            if any(item["basis"] not in {"mention", "limited claim"} for item in best.evidence):
                return Finding("UNCERTAIN", "Positive and negative statements both appear. Confirm their scope.",
                               best.evidence + negative.evidence)
            return negative
        return best

    adjacent = {other for other, entry in rubric.concepts.items() if key in entry.adjacent or other in concept.adjacent}
    for other in sorted(adjacent):
        rows = next((rows for _, line, rows in concept_statements(lines, rubric.concepts[other].aliases)
                     if uses_concept(line, rubric)), None)
        if rows:
            label = rubric.concepts[other].label
            return Finding("NOT_DEMONSTRATED", f"{label} shows related work. The requested tool is not demonstrated.",
                           [row.evidence("transferable experience") for row in rows],
                           transferable=rubric.thresholds.transferability_cap)
    return Finding("NOT_DEMONSTRATED", "The submitted PDF does not demonstrate this qualification.")


def generic_finding(req: Requirement, lines: list[Line], rubric: Rubric, required_action: set[str] | None = None) -> Finding:
    points = rubric.semantic_points
    if req.kind == "seniority":
        lines = [line for line in lines if line.section in {"experience", "summary"}]
    elif req.kind in {"education", "credential", "language"}:
        section = {"education": "education", "credential": "credentials", "language": "languages"}[req.kind]
        lines = [line for line in lines if line.section == section]
    else:
        lines = [line for line in lines if line.section in CONTEXT | {"summary", "skills"}]
    best = (0, [], False)
    for index, line in enumerate(lines):
        text, excerpts = use_text(lines, index)
        if required_action and not required_action & stems(text):
            continue
        amount = contextual_overlap(text, req.clause)
        if amount < rubric.thresholds.min_partial_overlap:
            continue
        if is_negated(text) and amount >= rubric.thresholds.min_requirement_overlap:
            return Finding("NOT_MET", "The resume explicitly contradicts the requirement.", [line.evidence("explicit contradiction")])
        if is_negated(text):
            continue
        contextual = action(Line(line.page, line.number, line.section, text), rubric) or req.kind in {
            "education", "credential", "language", "seniority",
        }
        if (contextual, amount) > (best[2], best[0]):
            best = amount, excerpts, contextual
    amount, excerpts, contextual = best
    evidence = [line.evidence("matching requirement language") for line in excerpts]
    if amount >= rubric.thresholds.min_requirement_overlap and contextual:
        return Finding("MET", "The relevant wording occurs in a qualifying experience or structured entry.",
                       evidence, demonstration=points.demonstrated, depth=context_strength(excerpts[0], rubric))
    if evidence:
        return Finding("PARTIALLY_MET", "Only some of the requirement wording or its context is visible.", evidence,
                       demonstration=points.partial_wording,
                       mention_only=all(line.section == "skills" for line in excerpts))
    return Finding("NOT_DEMONSTRATED", "No sufficiently specific evidence was found in the submitted PDF.")


def action_opener(clause: str) -> set[str]:
    text = re.sub(r"^(?:you will |effectively |successfully )+", "", clause)
    return stems(text.split()[0]) if text.split() else set()


def action_scope(req: Requirement, lines: list[Line], rubric: Rubric) -> Finding:
    verbs = stems(" ".join(rubric.category_cues["actions"])) | ABILITY_VERBS
    clause = fold(req.clause)
    if outcome := ACTION_AFTER_OUTCOME.fullmatch(clause):
        clause = outcome[1]
    if ability := ABILITY_TO.search(clause):
        clause = ability[1]
    if customer_work := CUSTOMER_WORK.fullmatch(CONCURRENT_CUSTOMERS.sub("concurrent customers", clause).rstrip(".")):
        clauses = [f"manage {customer_work[1]}"]
        if customer_work[2]:
            clauses.append(customer_work[2])
    else:
        first, *pieces = re.split(r",\s*(?:and\s+)?|\s+and\s+", clause)
        clauses = [first]
        for piece in pieces:
            # Keep enumerations of objects attached to their action.
            if not action_opener(piece) & verbs:
                clauses[-1] += " " + piece
                continue
            clauses.append(piece)
    findings = [generic_finding(replace(req, clause=clause), lines, rubric, action_opener(clause) & verbs)
                for clause in clauses]
    if len(findings) == 1:
        return findings[0]
    evidence = [item for finding in findings for item in finding.evidence]
    scores = {name: sum(getattr(finding, name) for finding in findings) / len(findings)
              for name in ("demonstration", "depth")}
    if all(finding.status == "MET" for finding in findings):
        return Finding("MET", "The PDF demonstrates each stated action.", evidence, **scores)
    if evidence:
        gaps = [clause.rstrip(".") for clause, finding in zip(clauses, findings, strict=True) if finding.status != "MET"]
        explanation = "The PDF shows some of the requested actions. Review the evidence for " + ", ".join(gaps) + "."
        return Finding("PARTIALLY_MET", explanation, evidence, **scores)
    return Finding("NOT_DEMONSTRATED", "The PDF does not demonstrate the stated actions.")


def practice_finding(practice: Practice, req: Requirement, lines: list[Line], rubric: Rubric) -> Finding:
    points = rubric.semantic_points
    examples = []
    for index, line in enumerate(lines):
        text, rows = use_text(lines, index)
        statement = replace(line, text=text)
        if not uses_concept(statement, rubric):
            continue
        if any(key not in practice.handled_scopes and hits(req.clause, scopes) and not hits(text, scopes)
               for key, scopes in rubric.scope_aliases.items()):
            continue
        matched = {facet.label for facet in practice.facets if facet.appears_in(fold(text))}
        if matched:
            examples.append((matched, rows, context_strength(statement, rubric)))
    if practice.same_statement:
        examples = sorted(examples, key=lambda item: (len(item[0]), item[2]), reverse=True)[:1]
    best = {}
    for matched, rows, depth in sorted(examples, key=lambda item: item[2], reverse=True):
        for facet in practice.facets:
            if facet.label in matched:
                best.setdefault(facet.label, (rows, depth))
    if not best:
        fallback = generic_finding(req, lines, rubric)
        if fallback.status in {"MET", "PARTIALLY_MET"}:
            return Finding("PARTIALLY_MET", "The PDF describes related work. It leaves the requested scope open.",
                           fallback.evidence, demonstration=points.partial_wording)
        return fallback
    evidence = [row.evidence(label) for label, (rows, _) in best.items() for row in rows]
    missing = [facet.label for facet in practice.facets if facet.label not in best]
    depth = sum(item[1] for item in best.values()) / len(practice.facets)
    if missing:
        return Finding("PARTIALLY_MET", "Evidence covers part of the requested work. Verify " + ", ".join(missing) + ".",
                       evidence, demonstration=points.demonstrated * len(best) / len(practice.facets), depth=depth)
    return Finding("MET", "The cited work demonstrates each part of the requested practice.", evidence,
                   demonstration=points.demonstrated, depth=depth)


def _duration_scope(req: Requirement, line: Line, rubric: Rubric) -> bool:
    scope = tenure_clause(req.clause)
    alternative = simple_alternative(replace(req, clause=scope))
    if req.concepts:
        matches_concepts = [hits(line.text, rubric.concepts[key].aliases) for key in req.concepts]
        return any(matches_concepts) if alternative else all(matches_concepts)
    remainder = YEARS.sub("", scope)
    fragments = re.split(r"\s+or\s+", remainder) if alternative else [remainder]
    scopes = [expected for fragment in fragments if (expected := stems(fragment) - {"professional", "relevant", "related"})]
    actual = stems(line.text)
    if (scopes == [{"technical", "role"}] and line.section == "experience" and ranges(line.text)
            and TECHNICAL_TITLE.search(fold(line.text).partition(",")[0])):
        return True
    return not scopes or any(len(expected & actual) / len(expected) >= rubric.thresholds.min_requirement_overlap
                             for expected in scopes)


def years_finding(req: Requirement, lines: list[Line], rubric: Rubric, as_of: date | None) -> Finding:
    points = rubric.semantic_points
    amounts = []
    for line in lines:
        if line.section not in CONTEXT | {"summary"} or not _duration_scope(req, line, rubric) or is_negated(line.text):
            continue
        amount = YEARS.search(fold(line.text))
        if amount and DURATION_CONTEXT.search(fold(line.text)):
            amounts.append((Decimal(amount[1].replace(",", ".")), line))
    if amounts:
        actual, line = max(amounts, key=lambda item: item[0])
        evidence = [line.evidence("explicit duration")]
        if actual >= req.years:
            return Finding("MET", f"The resume explicitly states {actual} years against the requested {req.years}.",
                           evidence, demonstration=points.demonstrated, depth=points.outcome_depth)
        # A lower minimum such as “2+ years” is incomplete evidence rather than a ceiling.
        amount = YEARS.search(fold(line.text))
        qualifier = fold(line.text)[max(0, amount.start() - 14):amount.end()]
        if "+" not in qualifier and not re.search(r"at least|more than|\d\s*-\s*\d", qualifier):
            return Finding("NOT_MET", f"The resume explicitly states {actual} years against the requested {req.years}.",
                           evidence)
    employment = [line for line in lines if line.section == "experience"]
    groups = []
    for line in employment:
        spans = ranges(line.text) if not BULLET.match(line.text) else []
        if spans:
            groups.append((line, spans[0], [line]))
        elif groups:
            groups[-1][2].append(line)
    intervals = []
    evidence = []
    incomplete = False
    for heading, span, rows in groups:
        related = next((line for line in rows if _duration_scope(req, line, rubric) and not is_negated(line.text)), None)
        if related is None:
            continue
        if interval := span.bounds(as_of):
            intervals.append(interval)
        else:
            incomplete = True
        evidence.append(heading.evidence("employment dates"))
        if related != heading:
            evidence.append(related.evidence("role scope"))
    days = experience_days(intervals)
    if days:
        years = Decimal(days) / Decimal("365.2425")
        # Round only for presentation. Dates show time in the role, not time on each tool.
        if years >= req.years and not req.concepts:
            return Finding("MET", f"Non-overlapping dated evidence supports at least {years:.1f} years.",
                           evidence, demonstration=points.demonstrated, depth=points.outcome_depth)
        return Finding("PARTIALLY_MET", f"Related role dates support at least {years:.1f} years of employment. "
                       "The full requested duration and scope are not directly demonstrated.",
                       evidence, demonstration=points.incomplete_qualification, depth=points.description_depth)
    if incomplete:
        return Finding("UNCERTAIN", "Related dates were found, but they do not establish a usable duration.", evidence)
    if amounts:
        actual, line = max(amounts, key=lambda item: item[0])
        return Finding("PARTIALLY_MET", f"The resume states a lower bound of {actual} years.", [line.evidence("reported lower bound")])
    return Finding("NOT_DEMONSTRATED", "The PDF provides no usable duration for the requested experience.")


def requirement_finding(req: Requirement, lines: list[Line], rubric: Rubric, as_of: date | None) -> Finding:
    if req.category == "informational":
        return Finding("NOT_APPLICABLE", "This posting line is informational or outside permitted scoring criteria.")
    if not lines:
        return Finding("UNCERTAIN", "The PDF has no usable text that supports an assessment.")
    if req.kind == "years":
        return years_finding(req, lines, rubric, as_of)
    if not req.concepts or set(req.concepts) == {"time-management", "prioritization"}:
        if practice := practice_for(fold(req.clause)):
            return practice_finding(practice, req, lines, rubric)
    if not req.concepts:
        if req.kind == "responsibility" or ABILITY_TO.search(fold(req.clause)):
            return action_scope(req, lines, rubric)
        return generic_finding(req, lines, rubric)
    findings = [concept_finding(key, req, lines, rubric, as_of) for key in req.concepts]
    if req.alternative:
        if len(findings) > 1 and not simple_alternative(req) and any(f.status != "MET" for f in findings):
            return Finding("UNCERTAIN", "The posting mixes alternatives and conjunctions. The required combination needs review.",
                           [item for finding in findings for item in finding.evidence])
        order = {"MET": 4, "PARTIALLY_MET": 3, "UNCERTAIN": 2, "NOT_DEMONSTRATED": 1, "NOT_MET": 0}
        return max(findings, key=lambda finding: (order[finding.status], finding.transferable, finding.depth))
    evidence = [item for finding in findings for item in finding.evidence]
    scores = {
        name: sum(getattr(item, name) for item in findings) / len(findings)
        for name in ("demonstration", "transferable", "depth")
    }
    status_set = {finding.status for finding in findings}
    if status_set == {"MET"} and req.kind == "responsibility":
        generic = action_scope(req, lines, rubric)
        if generic.status != "MET":
            return Finding("PARTIALLY_MET", "The relevant skills appear, but the PDF demonstrates only part of the requested responsibility.",
                           evidence + generic.evidence,
                           demonstration=max(generic.demonstration, rubric.semantic_points.partial_use),
                           transferable=scores["transferable"], depth=max(generic.depth, scores["depth"]))
    if len(status_set) == 1:
        explanations = list(dict.fromkeys(finding.explanation for finding in findings))
        return Finding(findings[0].status, " ".join(explanations), evidence, **scores)
    missing = [rubric.concepts[key].label for key, finding in zip(req.concepts, findings, strict=True) if finding.status != "MET"]
    if "NOT_MET" in status_set:
        status = "NOT_MET"
    elif status_set & {"MET", "PARTIALLY_MET"}:
        status = "PARTIALLY_MET"
    elif "UNCERTAIN" in status_set:
        status = "UNCERTAIN"
    else:
        status = "NOT_DEMONSTRATED"
    return Finding(status, "The complete requirement is not supported. Review " + ", ".join(missing) + ".", evidence, **scores)


def title_alignment(role: str | None, lines: list[Line], rubric: Rubric) -> tuple[float | None, list[dict]]:
    if not role:
        return None, []
    role_lines = [line for line in lines if line.section == "experience" and (
        ranges(line.text) or (not BULLET.match(line.text) and len(line.text.split()) <= 8
                              and hits(line.text, rubric.category_cues["role_words"]) and not action(line, rubric))
    )]
    best = max(role_lines, key=lambda line: overlap(line.text, role), default=None)
    if best is None:
        return 0, []
    score = 100 if matches(best.text, role) else rubric.thresholds.title_partial_cap * overlap(best.text, role)
    return score, [best.evidence("historical role title")] if score else []


def keyword_groups(posting: Posting, rubric: Rubric) -> list[tuple[str, ...]]:
    terms = {}
    groups = {}
    for req in posting.requirements:
        if req.category == "informational":
            continue
        clause = tenure_clause(req.clause) if req.kind == "years" else req.clause
        keys = []
        for key in req.concepts:
            aliases = [alias for alias in rubric.concepts[key].aliases if matches(clause, alias)]
            if aliases:
                terms.setdefault(key, max(aliases, key=len))
                keys.append(key)
        if len(keys) > 1 and simple_alternative(replace(req, clause=clause)):
            groups.setdefault(tuple(sorted(keys)), tuple(keys))
        else:
            if not keys:
                keys = sorted(tokens(clause))[:rubric.thresholds.max_evidence_lines]
                for word in keys:
                    terms.setdefault(word, word)
            for key in keys:
                groups.setdefault((key,), (key,))
    return list(dict.fromkeys(tuple(terms[key] for key in group) for group in groups.values()))


def stuffing(lines: list[Line], terms: list[str], rubric: Rubric) -> list[dict]:
    limits = rubric.thresholds
    flags = []
    normalized = [(line, fold(body(line.text))) for line in lines]
    repetitions = Counter(text for _, text in normalized if len(tokens(text)) >= 2)
    for line, text in normalized:
        if repetitions[text] >= limits.repeated_line_count:
            flags.append({"code": "repeated_line", "detail": "Substantially identical text repeats across the resume.",
                          "evidence": line.evidence("repeated text")})
            break
    repeated_term = next(
        ((line, term, count) for line, text in normalized for term in terms
         if (count := len(term_pattern(term).findall(text))) >= limits.repeated_term_count),
        None,
    )
    if repeated_term:
        line, term, count = repeated_term
        flags.append({"code": "repeated_term", "detail": f"{term} occurs {count} times on one line.",
                      "evidence": line.evidence("repeated posting term on one line")})
    for line in lines:
        count = sum(matches(line.text, term) for term in terms)
        if count >= limits.keyword_list_size and list_like(line.text, rubric) and line.section != "skills":
            flags.append({"code": "uncontextualized_list", "detail": "A dense posting-term list appears in narrative content.",
                          "evidence": line.evidence("keyword list")})
            break
    return flags
