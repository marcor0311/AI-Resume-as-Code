"""Load the evaluator's versioned rubric from trusted project or owner configuration."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from career.files import parse_yaml

DEFAULT_CONFIG = Path(__file__).parent / "config" / "scoring.yaml"
WEIGHT_KEYS = {
    "overall": {"readiness", "job_match"},
    "readiness": {"text", "structure", "contact", "dates", "layout", "characters"},
    "job_match": {"required", "preferred", "responsibilities", "title", "keywords"},
    "semantic": {"demonstration", "transferability", "depth"},
}
SECTIONS = {"summary", "experience", "projects", "achievements", "education", "skills", "credentials", "languages", "other"}
CATEGORIES = {"required", "preferred", "responsibilities", "informational", "title"}
STATUS_POINTS = {"MET", "PARTIALLY_MET", "NOT_DEMONSTRATED", "NOT_MET", "UNCERTAIN"}
CUES = {"required", "preferred", "alternatives", "excluded", "non_evidence", "actions", "role_words"}
Percent = Annotated[int, Field(ge=0, le=100)]
Positive = Annotated[int, Field(gt=0)]
FractionValue = Annotated[float, Field(gt=0, lt=1)]
Terms = Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Thresholds(Contract):
    min_text_characters: Positive
    max_bad_character_fraction: FractionValue
    min_column_lines: Positive
    column_split_fraction: FractionValue
    row_tolerance_points: Positive
    min_readable_font_points: Positive
    repeated_line_count: Annotated[int, Field(ge=2)]
    repeated_term_count: Annotated[int, Field(ge=2)]
    keyword_list_size: Annotated[int, Field(ge=2)]
    max_stuffing_penalty: Percent
    stuffing_penalty_per_flag: Percent
    max_match_without_requirements: Percent
    title_partial_cap: Percent
    transferability_cap: Percent
    max_evidence_lines: Positive
    min_context_words: Positive
    min_requirement_overlap: FractionValue
    min_partial_overlap: FractionValue
    max_pdf_pages: Positive
    max_pdf_bytes: Positive
    max_posting_bytes: Positive
    mention_only_points: Percent


class Refinement(Contract):
    max_iterations: Annotated[int, Field(ge=0, le=20)]


class SemanticPoints(Contract):
    demonstrated: Percent
    mention: Percent
    partial_wording: Percent
    incomplete_qualification: Percent
    partial_use: Percent
    description_depth: Percent
    structured_entry_depth: Percent
    outcome_depth: Percent


class Concept(Contract):
    label: Annotated[str, Field(min_length=1)]
    kind: Literal["skill", "practice", "education", "credential", "language"]
    aliases: Terms
    adjacent: list[str] = Field(default_factory=list)


class Rubric(Contract):
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    weights: dict[str, dict[str, Percent]]
    readiness_sections: dict[str, Percent]
    status_points: dict[str, Percent]
    thresholds: Thresholds
    refinement: Refinement
    semantic_points: SemanticPoints
    language_levels: dict[str, Positive]
    sections: dict[str, Terms]
    posting_sections: dict[str, Terms]
    category_cues: dict[str, Terms]
    scope_aliases: dict[str, Terms]
    concepts: dict[str, Concept]

    @model_validator(mode="after")
    def validate_rubric(self):
        if self.weights.keys() != WEIGHT_KEYS.keys():
            raise ValueError("weights must define overall, readiness, job_match and semantic")
        for name, components in self.weights.items():
            if components.keys() != WEIGHT_KEYS[name] or sum(components.values()) != 100:
                raise ValueError(f"weights.{name} must define its components and sum to 100")
        if self.readiness_sections.keys() != {"experience_or_projects", "education", "skills", "credentials"}:
            raise ValueError("invalid readiness section keys")
        if sum(self.readiness_sections.values()) != 100:
            raise ValueError("readiness_sections must sum to 100")
        if self.thresholds.min_partial_overlap >= self.thresholds.min_requirement_overlap:
            raise ValueError("partial overlap must be lower than full overlap")
        if self.status_points.keys() != STATUS_POINTS:
            raise ValueError("invalid requirement status points")
        for name, actual, keys in (
            ("sections", self.sections, SECTIONS), ("posting_sections", self.posting_sections, CATEGORIES),
            ("category_cues", self.category_cues, CUES),
        ):
            if actual.keys() != keys:
                raise ValueError(f"{name} has invalid keys")
        for key, concept in self.concepts.items():
            if any(adjacent == key or adjacent not in self.concepts for adjacent in concept.adjacent):
                raise ValueError(f"concepts.{key} has an invalid adjacent concept")
        return self


def load_rubric(path: Path = DEFAULT_CONFIG) -> Rubric:
    return Rubric.model_validate(parse_yaml(path.read_bytes()))
