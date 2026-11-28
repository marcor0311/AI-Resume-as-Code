"""Build an evidence-backed cover letter from the same verified facts as the resume."""

from .files import CareerError, json_text
from .knowledge import Knowledge
from .models import Letter
from .tailoring import numbers


def build_letter(knowledge: Knowledge, letter: Letter) -> tuple[str, dict]:
    profile = knowledge.verified(letter.profile)
    if profile.kind != "profile":
        raise CareerError(f"{letter.profile} is not a profile record")
    evidence: dict[str, dict] = {}
    paragraphs = []
    for p_index, paragraph in enumerate(letter.paragraphs):
        if not paragraph:
            raise CareerError(f"paragraph {p_index} is empty")
        sentences = []
        for s_index, claim in enumerate(paragraph):
            cited = [knowledge.fact(reference) for reference in claim.evidence]
            unsupported = numbers(claim.text) - set().union(*(numbers(fact.text) for fact in cited))
            if unsupported:
                raise CareerError(
                    f"paragraph {p_index} sentence {s_index}: numbers {sorted(unsupported)} are absent from the cited facts"
                )
            evidence[f"/paragraphs/{p_index}/{s_index}"] = {
                "text": claim.text, "evidence": {ref: fact.text for ref, fact in zip(claim.evidence, cited)},
            }
            sentences.append(claim.text)
        paragraphs.append(" ".join(sentences))
    contact = " | ".join(str(value) for value in (profile.email, profile.phone, profile.location, profile.website) if value)
    parts = [f"# {profile.title}", contact, letter.as_of]
    if letter.recipient:
        parts.append(letter.recipient)
    parts += [letter.greeting, *paragraphs, f"{letter.closing}\n\n{profile.title}"]
    return "\n\n".join(part for part in parts if part) + "\n", {"claims": evidence}


def letter_evidence_text(evidence: dict) -> str:
    return json_text(evidence)
