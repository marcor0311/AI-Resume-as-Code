"""Seeded synthetic postings and profiles. Expected findings come from the authored facts."""

import random
import textwrap
from dataclasses import dataclass


@dataclass(frozen=True)
class Practice:
    key: str
    role: str
    postings: tuple[str, ...]
    direct: tuple[str, ...]
    paraphrases: tuple[str, ...]
    partial: str
    misleading: str
    tools: tuple[str, ...]


PRACTICES = (
    Practice(
        "client-delivery", "Implementation Consultant",
        ("Provide technical support across the client lifecycle.",
         "Help customers from their first pilot through production launch."),
        ("Supported clients from pilot through production as the implementation lead.",
         "Provided technical assistance from initial evaluation through production for 12 customers."),
        ("Helped clients move from sandbox trials until their services went live.",
         "Assisted customer teams starting with their initial pilot and continuing until rollout."),
        "Supported clients during production incidents as the on-call lead.",
        "Built internal schedules and studied technical support across the client lifecycle.",
        ("AWS", "Google Cloud"),
    ),
    Practice(
        "data-workflow", "Analytics Engineer",
        ("Build end-to-end data engineering and analytics workflows.",
         "Turn source data into reliable reports through ingestion and validation."),
        ("Built pipelines that ingested billing exports, validated totals, and published daily revenue reports.",
         "Built a job that imported payment records, reconciled currency totals, and delivered dashboards."),
        ("Pulled transactions from ledger exports, standardized currency codes, and powered revenue charts.",
         "Captured incoming meter readings, checked duplicates, and sent hourly summaries to reports."),
        "Built jobs that ingested meter readings from message queues.",
        "Built an inventory screen. Studied end-to-end data engineering and analytics workflows as coursework.",
        ("PostgreSQL", "SQL"),
    ),
    Practice(
        "work-planning", "Project Coordinator",
        ("Use time management and prioritization to keep delivery on track.",
         "Organize work by urgency and keep delivery on schedule."),
        ("Prioritized requests by impact and scheduled weekly check-ins to review delivery deadlines.",
         "Prioritized deliverables by risk and managed project schedules against agreed milestones."),
        ("Triaged support tickets by severity and held weekly reviews of deadline risks.",
         "Ranked incoming tasks by urgency and ran fortnightly milestone reviews with delivery teams."),
        "Prioritized requests by urgency during a busy week.",
        "Created a staffing roster and read about time management and prioritization.",
        ("Microsoft Excel", "Python"),
    ),
    Practice(
        "field-service", "Instrumentation Technician",
        ("Calibrate measurement instruments and verify readings against a reference standard.",
         "Adjust measuring devices and confirm their readings using a known standard."),
        ("Calibrated pressure gauges and verified readings against a certified reference standard.",
         "Calibrated flow meters and verified their readings against a traceable bench standard."),
        ("Adjusted pressure gauges and checked each reading against a certified bench standard.",
         "Tuned flow meters and compared their readings with a calibrated reference instrument."),
        "Calibrated pressure gauges at the repair workshop.",
        "Built workshop schedules and observed technicians calibrate instruments against a reference standard.",
        ("Python", "SQL"),
    ),
)

TOOL_USE = {
    "AWS": "Deployed telemetry collectors to Amazon Web Services for a customer rollout.",
    "Google Cloud": "Deployed telemetry collectors to GCP for a customer rollout.",
    "PostgreSQL": "Created reporting views in Postgres for weekly reconciliation.",
    "SQL": "Wrote Structured Query Language joins to reconcile equipment readings.",
    "Microsoft Excel": "Built Excel pivot tables to track monthly delivery capacity.",
    "Python": "Built Python scripts to validate maintenance log exports.",
}

HEADINGS = (
    ("Responsibilities", "Required qualifications", "- "),
    ("What you will do", "What we look for", ""),
    ("How you'll contribute", "What you'll bring", "• "),
)
NAMES = ("Morgan", "Jamie", "Casey", "Sasha", "Riley", "Cameron", "Taylor", "Avery")


@dataclass(frozen=True)
class Profile:
    key: str
    lines: tuple[str, ...]
    expected: tuple[str, str]
    proof: tuple[str | None, str | None]


@dataclass(frozen=True)
class PostingCase:
    key: str
    family: str
    posting: str
    requirement_lines: tuple[int, int]
    profiles: tuple[Profile, ...]


def wrapped(statement: str, width: int) -> list[str]:
    return textwrap.wrap(
        statement, width=width, initial_indent="• ", subsequent_indent="  ",
        break_long_words=False, break_on_hyphens=False,
    )


def generate(seed: int, postings_per_family: int) -> tuple[PostingCase, ...]:
    rng = random.Random(seed)
    cases = []
    for practice in PRACTICES:
        for number in range(postings_per_family):
            heading, qualifications, bullet = rng.choice(HEADINGS)
            duty = practice.postings[(rng.randrange(len(practice.postings)) + number) % len(practice.postings)]
            tool = rng.choice(practice.tools)
            title = practice.role
            posting = "\n".join((
                f"Job Title: {title}", f"{heading}:", f"{bullet}{duty}",
                f"{qualifications}:", f"{bullet}Hands-on experience with {tool}.",
                "Benefits:", "Standard paid time off and training allowance.", "",
            ))
            direct = rng.choice(practice.direct)
            paraphrase = rng.choice(practice.paraphrases)
            tool_use = TOOL_USE[tool]
            unrelated = rng.choice((
                "Cataloged museum objects and maintained gallery visitor logs.",
                "Coordinated venue bookings and managed printed event materials.",
            ))
            width = rng.choice((61, 74, 92))
            year = rng.choice((2020, 2021, 2022))
            variants = (
                ("direct", (direct, tool_use), "Reporting and documentation", ("MET", "MET"), (direct, tool_use)),
                ("paraphrase", (paraphrase, tool_use), "Reporting and documentation", ("MET", "MET"), (paraphrase, tool_use)),
                ("partial", (practice.partial, tool_use), "Reporting and documentation", ("PARTIALLY_MET", "MET"), (None, tool_use)),
                ("inventory", (unrelated,), f"{duty} {tool}", ("NO_FULL", "PARTIALLY_MET"), (None, None)),
                ("wrong-action", (practice.misleading, f"Built a paper ticket queue. Studied {tool} in a course."),
                 "Reporting and documentation", ("NO_FULL", "NO_FULL"), (None, None)),
                ("negated", (f"No hands-on experience with {tool}.", f"I did not perform this duty: {duty}"),
                 "Reporting and documentation", ("NO_FULL", "NOT_MET"), (None, None)),
                ("unrelated", (unrelated,), "Event logistics and filing", ("NOT_DEMONSTRATED", "NOT_DEMONSTRATED"), (None, None)),
            )
            profiles = []
            for key, statements, skills, expected, proof in variants:
                name = rng.choice(NAMES)
                previous_job = title if key in {"direct", "paraphrase", "partial"} else "Office Assistant"
                lines = [f"{name} Example", f"{name.lower()}@example.com", "Experience",
                         f"{previous_job}, Example Services {year}/03 - {year + 3}/09"]
                for statement in statements:
                    lines.extend(wrapped(statement, width))
                lines.extend(["Skills", *textwrap.wrap(skills, width=74)])
                profiles.append(Profile(key, tuple(lines), expected, proof))
            cases.append(PostingCase(f"{seed}-{practice.key}-{number + 1}", practice.key, posting, (3, 5), tuple(profiles)))
    return tuple(cases)
