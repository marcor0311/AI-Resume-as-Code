"""Observable parts of common requirements that can be expressed in different words."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Facet:
    label: str
    patterns: tuple[str, ...]

    def appears_in(self, text: str) -> bool:
        return all(re.search(pattern, text) for pattern in self.patterns)


@dataclass(frozen=True)
class Practice:
    posting_patterns: tuple[str, ...]
    facets: tuple[Facet, ...]
    same_statement: bool = False
    handled_scopes: tuple[str, ...] = ()
    alternate_postings: tuple[tuple[str, ...], ...] = ()


CUSTOMER = r"\b(?:customers?|clients?)\b"
SUPPORT = r"\b(?:support(?:ed|ing)?|assist(?:ed|ance|ing)?|help(?:ed|ing)?|guid(?:e|ed|ing)|advised)\b"
DELIVERY = r"\b(?:built|designed|implemented|configured|deployed|launched|delivered)\b"
ROLLOUT = r"(?:production|go-live|launch(?:es)?|(?<!staging )(?<!test )(?<!pilot )rollout|went live)"
LIFECYCLE = (r"\b(?:from|starting with|beginning with)\b.{0,45}\b(?:evaluation|pre-sales|presales|trials?|pilot|onboarding)\b"
             rf".{{0,35}}\b(?:to|into|through|until)\b.{{0,25}}\b{ROLLOUT}\b")
CONCURRENT = r"\b(?:concurrent(?:ly)?|simultaneous(?:ly)?|in parallel)\b"
AI_WORKFLOW = r"\bai[- ](?:assisted|augmented|driven)\b.{0,40}\b(?:workflows?|development)\b"
TECHNICAL_DETAIL = r"\b(?:integration|ingestion|diagnostics?|permissions?|architectures?|configuration|deployment|production launch(?:es)?|prototype|rollout|migration)\b"

PRACTICES = (
    Practice((r"\btechnical (?:assistance|support)\b", r"\blife[ -]?cycle\b"), (
        Facet("technical customer support", (CUSTOMER, SUPPORT, rf"\b(?:technical|pre-sales|{ROLLOUT})\b")),
        Facet("support from early evaluation to rollout", (CUSTOMER, SUPPORT, LIFECYCLE)),
    ), same_statement=True, handled_scopes=("production",), alternate_postings=((CUSTOMER, SUPPORT, LIFECYCLE),)),
    Practice((CUSTOMER, CONCURRENT, r"\btechnical solutions?\b"), (
        Facet("parallel customer engagements", (CUSTOMER, CONCURRENT, r"\b(?:supported|managed|guided|handled|assisted|advised|worked)\b")),
        Facet("implementation for customers", (CUSTOMER, DELIVERY, TECHNICAL_DETAIL)),
    )),
    Practice((CUSTOMER, r"\bguide\b", r"\btechnical decisions?\b", AI_WORKFLOW), (
        Facet("technical customer guidance", (CUSTOMER, r"\b(?:guided|advised|recommended|coached)\b", r"\b(?:technical decisions?|options|architecture|production|deployment)\b")),
        Facet("applied AI workflow used in that guidance", (CUSTOMER, AI_WORKFLOW, TECHNICAL_DETAIL, r"\b(?:guided|advised|recommended|coached)\b")),
    ), handled_scopes=("ai_driven_development",)),
    Practice((r"\bcustomer needs\b", r"\brelationships\b", r"\bobjections\b"), (
        Facet("customer discovery", (CUSTOMER, r"\b(?:assessed|elicited|identified|discovery|requirements gathering)\b")),
        Facet("ongoing relationship work", (r"\b(?:weekly|monthly|recurring|ongoing)\b", r"\b(?:check-ins?|reviews?|meetings?|follow-ups?)\b", r"\b(?:decisions?|next steps|customers?|clients?|stakeholders?)\b")),
        Facet("response to customer objections", (r"\b(?:addressed|resolved|answered|turned)\b", r"\b(?:objections?|concerns?)\b")),
        Facet("demonstrating value to customers", (CUSTOMER, r"\b(?:demos?|demonstrations?|proofs? of concept|proofs?-of-concept|technical evaluations?)\b", r"\b(?:moved to onboarding|proceeded to|adopted|converted|reduced|cut|increased|proved|validated)\b")),
    )),
    Practice((r"\bend[- ]to[- ]end\b", r"\bdata engineering\b", r"\banalytics\b"), (
        Facet("data ingestion from a source", (r"\b(?:ingested|imported|extracted|collected|pulled|captured)\b", r"\b(?:from|source|exports?|feeds?|events?|files?|records?|incoming)\b")),
        Facet("transformation or validation", (r"\b(?:validated|transformed|cleaned|reconciled|joined|normalized|aggregated|modeled|standardized|checked duplicates)\b",)),
        Facet("output for downstream analytics", (r"\b(?:published|delivered|served|fed|produced|loaded|powered|sent)\b", r"\b(?:reports?|dashboards?|charts?|analytics|analysts?|reporting|business intelligence)\b")),
    ), same_statement=True, alternate_postings=((r"\bsource data\b", r"\breports?\b", r"\b(?:ingestion|validation)\b"),)),
    Practice((r"\btime management\b", r"\bprioriti[sz](?:ation|e|ing)\b"), (
        Facet("prioritization of competing work", (r"\b(?:prioriti[sz]ed|triaged|ranked)\b", r"\b(?:requests?|tasks?|incidents?|tickets?|escalations?|deliverables?|projects?)\b")),
        Facet("planning or review cadence", (r"\b(?:scheduled|(?:weekly|fortnightly|monthly) (?:check-ins?|reviews?)|milestones?|delivery schedules?|project schedules?|time management|timelines?)\b", r"\b(?:go-live|deliver(?:y|ables?)|deadlines?|decisions?|next steps|projects?|tasks?)\b")),
    ), alternate_postings=((r"\bwork by urgency\b", r"\bdelivery on schedule\b"),)),
    Practice((r"\b(?:calibrate|adjust)\b", r"\b(?:instruments?|measuring devices?)\b", r"\b(?:reference|known) standard\b"), (
        Facet("instrument calibration", (r"\b(?:calibrated|adjusted|tuned)\b", r"\b(?:instruments?|gauges?|meters?|measuring devices?)\b")),
        Facet("verification against a known reference", (r"\b(?:verified|checked|compared|confirmed)\b", r"\breadings?\b", r"\b(?:standard|reference instrument)\b")),
    ), same_statement=True),
)


def practice_for(clause: str) -> Practice | None:
    return next((practice for practice in PRACTICES
                 if any(all(re.search(pattern, clause) for pattern in form)
                        for form in (practice.posting_patterns, *practice.alternate_postings))), None)
