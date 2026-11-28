"""Reproducible synthetic PDF and posting benchmark for the independent evaluator."""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import typst

from career.files import CareerError, digest
from evaluation.config import Rubric, load_rubric
from evaluation.engine import evaluate
from evaluation.reporting import compare, evaluation_markdown

POSTING = b"""Job Title: Senior Platform Engineer

Required Qualifications:
- At least 4 years of professional experience.
- Python and Kubernetes experience.
- Bachelor's degree in Computer Science.
- Active Certified Kubernetes Administrator certification.
- English C1 or higher.

Preferred Qualifications:
- Experience with Terraform.
- AWS experience.

Responsibilities:
- Build incident response playbooks and resolve production incidents.

Benefits:
- Annual leave and professional development budget.
"""

HEADER = ["Ellis Example", "ellis@example.com"]
STRONG = [
    *HEADER,
    "Experience",
    "Senior Platform Engineer, Example Software 2018/01 - 2024/11",
    "Built production services with Python and deployed them to Kubernetes, serving 20 teams.",
    "Managed AWS workloads and automated infrastructure using Terraform.",
    "Built incident response playbooks and resolved production incidents.",
    "Education", "Bachelor's degree in Computer Science, Example University 2017",
    "Certifications", "Active Certified Kubernetes Administrator",
    "Skills", "Python | Kubernetes | AWS | Terraform",
    "Languages", "English C2",
]
PARTIAL = [
    *HEADER,
    "Experience", "Platform Engineer, Example Software 2021/01 - 2023/01",
    "Built internal Python services for 8 teams.",
    "Deployed internal infrastructure using OpenTofu.",
    "Education", "Bachelor's degree in Information Systems",
    "Skills", "Python | Kubernetes | OpenTofu", "Languages", "English B2",
]
UNRELATED = [
    *HEADER, "Experience", "Graphic Designer, Example Studio 2018 - 2024",
    "Created editorial illustrations for weekly magazines and coordinated print proofs.",
    "Skills", "Illustration, Print Design, Editorial Layout",
]
STUFFED = [
    *UNRELATED[:-2], "Skills",
    *["Python Kubernetes Terraform AWS incident response CKA English Computer Science"] * 8,
]
FOREIGN = (
    "Buscamos una persona con experiencia para nuestras funciones. Los requisitos incluyen conocimientos "
    "profesionales y habilidades para desarrollar servicios. La formación es deseable."
)
KEYWORDS = (
    b"Job Title: Platform Engineer\nRequired:\n- Python.\n- Kubernetes.\n- AWS.\n"
    b"Preferred:\n- Terraform.\nResponsibilities:\n- Build incident response playbooks."
)


def make_pdf(lines: list[str], right: list[str] | None = None, *, font_points: int = 11) -> bytes:
    source = ['#set page(width: 210mm, height: 297mm, margin: 0pt)', f'#set text(size: {font_points}pt)']
    for left, column in ((40, lines), (330, right or [])):
        for index, line in enumerate(column):
            string = json.dumps(line, ensure_ascii=False)
            source.append(f'#place(top + left, dx: {left}pt, dy: {40 + index * 21}pt)[#text({string})]')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "benchmark.typ"
        path.write_text("\n".join(source), encoding="utf-8")
        return typst.compile(path, format="pdf", ignore_system_fonts=True, timestamp=0)


def by_text(report: dict, text: str) -> dict:
    return next(row for row in report["requirements"] if text in row["original_requirement"])


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rubric = load_rubric()
        cls.strong_pdf = make_pdf(STRONG)
        cls.partial_pdf = make_pdf(PARTIAL)
        cls.unrelated_pdf = make_pdf(UNRELATED)
        cls.stuffed_pdf = make_pdf(STUFFED)

    def test_alignment_benchmark_rewards_evidence_over_words(self):
        strong, partial, unrelated = [
            evaluate(pdf, POSTING, self.rubric) for pdf in (self.strong_pdf, self.partial_pdf, self.unrelated_pdf)
        ]
        self.assertGreater(strong["job_match"]["score"], partial["job_match"]["score"])
        self.assertGreater(partial["job_match"]["score"], unrelated["job_match"]["score"])
        self.assertGreaterEqual(strong["job_match"]["score"], 90)
        self.assertEqual(by_text(strong, "4 years")["status"], "MET")
        self.assertEqual(by_text(strong, "Computer Science")["status"], "MET")
        self.assertEqual(by_text(strong, "Administrator")["status"], "MET")
        self.assertEqual(by_text(partial, "Computer Science")["status"], "PARTIALLY_MET")
        self.assertEqual(by_text(partial, "English C1")["status"], "NOT_MET")
        self.assertEqual(by_text(partial, "Administrator")["status"], "NOT_DEMONSTRATED")
        self.assertEqual(by_text(unrelated, "Python and Kubernetes")["status"], "NOT_DEMONSTRATED")
        self.assertIn("Python", strong["demonstrated_technical_skills"])
        self.assertNotIn("Kubernetes", partial["demonstrated_technical_skills"])
        self.assertEqual(strong["ats_readiness"]["score"], 100)
        self.assertTrue(by_text(strong, "Python and Kubernetes")["evidence"][0]["page"])

    def test_stuffing_can_win_naive_coverage_but_loses_job_match(self):
        strong = evaluate(self.strong_pdf, KEYWORDS, self.rubric)
        stuffed = evaluate(self.stuffed_pdf, KEYWORDS, self.rubric)
        self.assertEqual(len(stuffed["keywords"]["missing"]), 0)
        self.assertGreaterEqual(len(stuffed["keywords"]["matched"]), len(strong["keywords"]["matched"]))
        self.assertTrue(stuffed["keyword_stuffing_warnings"])
        self.assertLess(stuffed["job_match"]["score"], 40)
        self.assertGreater(strong["job_match"]["score"], 85)
        self.assertFalse(stuffed["demonstrated_technical_skills"])
        irrelevant = make_pdf([*UNRELATED, "Roadmaps, Art History, Award Design, Branding"])
        self.assertEqual(evaluate(irrelevant, KEYWORDS)["job_match"]["score"],
                         evaluate(self.unrelated_pdf, KEYWORDS)["job_match"]["score"])

    def test_equivalence_adjacency_and_unsupported_claims(self):
        report = evaluate(make_pdf([
            *HEADER, "Experience", "Engineer, Example Software 2020/03 - 2024/11",
            "Operated production K8s clusters serving 9 engineering teams.",
            "Deployed infrastructure with OpenTofu for service migrations.",
            "No AWS experience.", "Skills", "K8s | OpenTofu | AWS",
        ]), KEYWORDS)
        alias = by_text(report, "Kubernetes")
        self.assertEqual(alias["status"], "MET")
        self.assertIn("K8s", alias["evidence"][0]["quote"])
        self.assertIn("kubernetes", report["keywords"]["missing"])
        self.assertEqual(by_text(report, "Terraform")["status"], "NOT_DEMONSTRATED")
        related = report["semantic_fit"]["finding_details"][by_text(report, "Terraform")["id"]]
        self.assertGreater(related["transferable_evidence"], 0)
        self.assertEqual(by_text(report, "AWS")["status"], "NOT_MET")

    def test_scope_and_mixed_requirements_do_not_award_full_credit(self):
        pdf = make_pdf([
            *HEADER, "Experience", "Platform Engineer 2020/02 - 2024/06",
            "Deployed Kubernetes in a test environment for internal development.",
            "No production AWS experience.", "Skills", "Kubernetes",
        ])
        posting = b"Required:\n- Production Kubernetes experience.\n- AWS.\n- Kubernetes and AWS or Azure."
        report = evaluate(pdf, posting)
        self.assertEqual(by_text(report, "Production Kubernetes")['status'], "PARTIALLY_MET")
        self.assertEqual(by_text(report, "AWS.")['status'], "NOT_DEMONSTRATED")
        self.assertEqual(by_text(report, "Kubernetes and AWS")['status'], "UNCERTAIN")

    def test_compound_responsibility_requires_action_evidence(self):
        lines = [*HEADER, "Projects", "Wrote incident response playbooks covering rollback and escalation."]
        posting = b"Responsibility: Write incident response playbooks and support rollbacks."
        incomplete = evaluate(make_pdf(lines), posting)
        self.assertEqual(by_text(incomplete, "playbooks")["status"], "PARTIALLY_MET")
        complete = evaluate(make_pdf([*lines, "Supported rollbacks for production services."]), posting)
        self.assertEqual(by_text(complete, "playbooks")["status"], "MET")

    def test_date_consistency_invalid_ranges_and_open_duration(self):
        posting = b"Required:\n- At least 4 years of professional experience."
        for date_range, as_of, status in (
            ("2024/06 - 2020/05", None, "UNCERTAIN"),
            ("2019/13 - 2023/01", None, "UNCERTAIN"),
            ("2020/05 - present", None, "UNCERTAIN"),
            ("2020/05 - present", date(2026, 1, 1), "MET"),
        ):
            with self.subTest(date_range=date_range, as_of=as_of):
                pdf = make_pdf([*HEADER, "Experience", f"Engineer, Example Software {date_range}", "Skills", "Python"])
                report = evaluate(pdf, posting, as_of=as_of)
                self.assertEqual(by_text(report, "4 years")["status"], status)
                if "2020/05" in date_range and "present" not in date_range or "2019/13" in date_range:
                    self.assertIn("invalid_date_range", {item["code"] for item in report["ats_readiness"]["issues"]})
        overlapping = make_pdf([
            *HEADER, "Experience", "Engineer 2019/01 - 2022/01", "Lead 2020/01 - 2022/12", "Skills", "Python",
        ])
        self.assertEqual(by_text(evaluate(overlapping, b"Required: At least 5 years of professional experience."),
                                 "5 years")["status"], "PARTIALLY_MET")

    def test_pdf_readability_columns_corruption_and_source_loss(self):
        unreadable = evaluate(b"not a PDF", POSTING)
        self.assertEqual(unreadable["overall"]["score"], 0)
        self.assertTrue(unreadable["job_match"]["no_usable_evidence"])
        self.assertEqual(by_text(unreadable, "Python and Kubernetes")["status"], "UNCERTAIN")
        laid_out = make_pdf(STRONG, ["Technical Skills", "Programming and scripting", "Production deployment patterns",
                                     "Cross functional work", "Systems engineering methods", "Operational practices"])
        columns = evaluate(laid_out, POSTING)
        self.assertIn("column_reading_order", {item["code"] for item in columns["ats_readiness"]["issues"]})
        self.assertLess(columns["ats_readiness"]["score"], 100)
        tiny = evaluate(make_pdf(STRONG, font_points=4), POSTING)
        self.assertIn("hidden_or_tiny_text", {item["code"] for item in tiny["ats_readiness"]["issues"]})
        self.assertEqual(tiny["job_match"]["score"], 0)
        damaged = make_pdf([*STRONG, "Character layer: □ □ □ � � �"])
        report = evaluate(damaged, POSTING, expected=("missing fragment",))
        self.assertIn("garbled_characters", {item["code"] for item in report["ats_readiness"]["issues"]})
        self.assertEqual(report["ats_readiness"]["source_text_check"]["missing"], ["missing fragment"])
        no_expectation = evaluate(damaged, POSTING)
        self.assertEqual(report["overall"], no_expectation["overall"])

    def test_english_only_and_protected_content_excluded(self):
        with self.assertRaisesRegex(CareerError, "job posting must be supplied in English"):
            evaluate(self.strong_pdf, FOREIGN.encode("utf-8"))
        with self.assertRaisesRegex(CareerError, "resume PDF must be supplied in English"):
            evaluate(make_pdf([*HEADER, "Experiencia", FOREIGN]), POSTING)
        protected = evaluate(self.strong_pdf, POSTING + b"\nRequired: Nationality must be Canadian.\n")
        row = by_text(protected, "Nationality")
        self.assertEqual(row["status"], "NOT_APPLICABLE")
        self.assertEqual(protected["job_match"], evaluate(self.strong_pdf, POSTING)["job_match"])
        sparse = ["Ellis Example", "Experience", "Engineer", "Skills", "Python"]
        baseline = evaluate(make_pdf(sparse), POSTING)
        added = evaluate(make_pdf([sparse[0], "Date of birth 1988-05-04", "Nationality Canadian", *sparse[1:]]), POSTING)
        self.assertEqual(added["overall"], baseline["overall"])
        self.assertEqual(added["ats_readiness"]["contact_channels"], [])

    def test_scores_are_reproducible_and_semantic_is_separate(self):
        first = evaluate(self.strong_pdf, POSTING)
        second = evaluate(self.strong_pdf, POSTING)
        first.pop("evaluation_timestamp")
        second.pop("evaluation_timestamp")
        self.assertEqual(first, second)
        deterministic_only = evaluate(self.strong_pdf, POSTING, semantic=False)
        self.assertIsNone(deterministic_only["semantic_fit"])
        self.assertEqual(first["overall"], deterministic_only["overall"])
        self.assertEqual(first["inputs"]["pdf_sha256"], digest(self.strong_pdf))

    def test_baseline_comparison_rejects_different_posting_or_configuration(self):
        baseline = evaluate(self.partial_pdf, POSTING)
        tailored = evaluate(self.strong_pdf, POSTING)
        comparison = compare(baseline, tailored)
        self.assertGreater(comparison["scores"]["job_match"]["delta"], 0)
        self.assertTrue(comparison["newly_demonstrated_requirements"])
        self.assertIn("Kubernetes", comparison["newly_demonstrated_skills"])
        self.assertGreater(comparison["scores"]["semantic_fit"]["delta"], 0)
        self.assertTrue(compare(tailored, baseline)["regressed_scores"])
        with self.assertRaisesRegex(CareerError, "same original posting"):
            compare(baseline, evaluate(self.strong_pdf, POSTING + b"\n"))
        custom = self.rubric.model_dump()
        custom["weights"]["overall"] = {"readiness": 30, "job_match": 70}
        with self.assertRaisesRegex(CareerError, "configuration"):
            compare(baseline, evaluate(self.strong_pdf, POSTING, Rubric.model_validate(custom)))

    def test_reports_preserve_evidence_and_cli_is_append_only(self):
        report = evaluate(self.strong_pdf, POSTING)
        markdown = evaluation_markdown(report)
        self.assertIn("Requirement evidence", markdown)
        self.assertIn("Page 1, line", markdown)
        self.assertIn("Prioritized improvements", markdown)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf, posting = root / "resume.pdf", root / "posting.txt"
            pdf.write_bytes(self.strong_pdf)
            posting.write_bytes(POSTING)
            command = [sys.executable, "-m", "evaluation", "--root", str(root), "score", "baseline",
                       "--pdf", str(pdf), "--posting", str(posting)]
            subprocess.run(command, check=True, capture_output=True)
            target = root / "evaluations" / "baseline"
            original = (target / "ats-evaluation.json").read_bytes()
            again = subprocess.run(command, check=False, capture_output=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual((target / "ats-evaluation.json").read_bytes(), original)
            self.assertTrue((target / "ats-evaluation.md").is_file())


if __name__ == "__main__":
    unittest.main()
