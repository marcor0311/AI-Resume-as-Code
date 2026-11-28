"""Canonical records and persisted workflow contracts."""

import re
import unicodedata
from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, HttpUrl
from pydantic_extra_types.phone_numbers import PhoneNumber


def resume_line(value: str) -> str:
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value):
        raise ValueError("use visible, single-line text")
    if re.search(r"[*`\\<>]|__|!\[|\]\(|(?:^|\s)#[a-z][\w-]*\(", value):
        raise ValueError("use plain text without markup or template expressions")
    return value


def career_date(value: str) -> str:
    # Validate calendar precision while retaining exactly what the owner knows.
    padded = {4: "-01-01", 7: "-01", 10: ""}[len(value)]
    date.fromisoformat(value + padded)
    return value


Line = Annotated[str, Field(min_length=1, max_length=600), AfterValidator(resume_line)]
Id = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=80)]
FactRef = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9-]*#[a-z][a-z0-9-]*$", max_length=161)
]
CareerDate = Annotated[
    str, Field(pattern=r"^[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?$"), AfterValidator(career_date)
]
Day = Annotated[
    str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), AfterValidator(career_date)
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Kind = Literal[
    "profile", "experience", "project", "achievement", "education", "certification",
    "skill", "language", "training", "volunteer", "evidence", "other",
]
Status = Literal["verified", "needs_confirmation"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Fact(Contract):
    id: Id
    text: Line
    status: Status
    sources: list[Id] = Field(default_factory=list)
    mentions: list[Id] = Field(default_factory=list)


class BaseRecord(Contract):
    schema_version: Literal[1] = 1
    id: Id
    title: Line
    status: Status
    tags: list[Line] = Field(default_factory=list)
    related: list[Id] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)


class Profile(BaseRecord):
    kind: Literal["profile"]
    email: EmailStr | None = None
    phone: PhoneNumber | None = None
    location: Line | None = None
    website: HttpUrl | None = None


class DatedRecord(BaseRecord):
    start_date: CareerDate | None = None
    end_date: CareerDate | Literal["present"] | None = None
    location: Line | None = None


class Experience(DatedRecord):
    kind: Literal["experience"]
    organization: Line
    start_date: CareerDate
    end_date: CareerDate | Literal["present"] | None = None


class Education(DatedRecord):
    kind: Literal["education"]
    organization: Line
    degree: Line | None = None


class Volunteer(DatedRecord):
    kind: Literal["volunteer"]
    organization: Line


class Project(DatedRecord):
    kind: Literal["project"]


class Credential(BaseRecord):
    kind: Literal["certification", "training"]
    organization: Line
    date: CareerDate
    expires: CareerDate | None = None
    aliases: list[Line] = Field(default_factory=list)


class Milestone(BaseRecord):
    kind: Literal["achievement", "other"]
    date: CareerDate | None = None


class Skill(BaseRecord):
    kind: Literal["skill"]
    aliases: list[Line] = Field(default_factory=list)


class Language(BaseRecord):
    kind: Literal["language"]
    proficiency: Line


class Evidence(BaseRecord):
    kind: Literal["evidence"]
    excerpt: Line | None = None
    attachment: str | None = None


Record = Annotated[
    Profile | Experience | Education | Volunteer | Project | Credential | Milestone | Skill | Language | Evidence,
    Field(discriminator="kind"),
]


class Requirement(Contract):
    id: Id
    kind: Literal["mandatory", "preferred", "responsibility"]
    text: Line
    quote: Annotated[str, Field(min_length=1, max_length=1500)]


class Analysis(Contract):
    role: Line
    employer: Line | None = None
    requirements: list[Requirement] = Field(min_length=1)
    keywords: list[Line] = Field(default_factory=list)


class Claim(Contract):
    text: Line
    evidence: list[FactRef] = Field(min_length=1)


class Entry(Contract):
    record: Id
    highlights: list[Claim] = Field(default_factory=list)


class Draft(Contract):
    profile: Id
    as_of: Day
    language: Literal["english"] = "english"
    summary: list[Claim] = Field(default_factory=list)
    entries: list[Entry] = Field(min_length=1)
    skills: list[Id] = Field(default_factory=list)


class ClaimReview(Contract):
    path: str
    verdict: Literal["verbatim", "supported_reformulation", "unsupported", "needs_confirmation"]
    reason: Line


class CoverageReview(Contract):
    requirement: Id
    status: Literal["covered", "partial", "gap", "needs_confirmation"]
    claims: list[str] = Field(default_factory=list)
    reason: Line


QualityDimension = Literal[
    "relevance", "evidence_strength", "clarity", "action_language", "quantification",
    "conciseness", "consistency", "readability", "formatting",
]


class Review(Contract):
    input_sha256: Digest
    reviewer: Line
    claims: list[ClaimReview]
    coverage: list[CoverageReview]
    quality: dict[QualityDimension, Line]
    disposition: Literal["ready", "revise"]


class Letter(Contract):
    """A cover letter whose narrative sentences each cite verified facts."""
    profile: Id
    as_of: Day
    language: Literal["english"] = "english"
    recipient: Line | None = None
    greeting: Line = "Dear Hiring Manager,"
    paragraphs: list[list[Claim]] = Field(min_length=1)
    closing: Line = "Sincerely,"


ApplicationStatus = Literal["submitted", "screen", "interview", "offer", "rejected", "withdrawn", "no_response"]


class ApplicationEvent(Contract):
    date: Day
    status: ApplicationStatus
    note: Line | None = None


class Application(Contract):
    version: Id
    employer: Line
    role: Line | None = None
    events: list[ApplicationEvent] = Field(min_length=1)
