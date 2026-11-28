"""Check evidence recognition across phrases, work examples, and irrelevant claims."""

import unittest

from evaluation.engine import evaluate
from tests.test_evaluation import HEADER, by_text, make_pdf


class EvidencePracticeEvals(unittest.TestCase):
    def test_technical_tenure_uses_dated_titles_and_keeps_unrelated_work_out(self):
        posting = b"Required: 2+ years of experience in a technical role, preferably with distributed systems."
        for title, expected in (("Systems Developer", "MET"), ("Reservations Clerk", "NOT_DEMONSTRATED")):
            with self.subTest(title=title):
                pdf = make_pdf([*HEADER, "Experience", f"{title}, Example Engineering 2021/02 - 2024/06"])
                row = by_text(evaluate(pdf, posting), "2+ years")
                self.assertEqual(row["status"], expected)
                if expected == "MET":
                    self.assertEqual(row["evidence"][0]["basis"], "employment dates")

    def test_degree_abbreviation_and_related_field_depend_on_posting_scope(self):
        pdf = make_pdf([*HEADER, "Education", "B.S. in Software Engineering, Example University 2021"])
        exact = b"Required: Undergraduate degree in Computer Science."
        related = b"Required: Undergraduate degree in Computer Science or a related field."
        self.assertEqual(by_text(evaluate(pdf, exact), "Undergraduate degree")["status"], "PARTIALLY_MET")
        row = by_text(evaluate(pdf, related), "Undergraduate degree")
        self.assertEqual(row["status"], "MET")
        self.assertEqual(row["evidence"][0]["basis"], "degree and comparable field")

    def test_lifecycle_support_can_be_demonstrated_in_other_words(self):
        posting = b"Responsibilities: Provide technical support across the client lifecycle."
        for statement, expected in (
            ("Supported clients from pilot through production as the implementation lead.", "MET"),
            ("Supported clients during production incidents as the on-call lead.", "PARTIALLY_MET"),
        ):
            with self.subTest(statement=statement):
                pdf = make_pdf([*HEADER, "Experience", statement])
                self.assertEqual(by_text(evaluate(pdf, posting), "client lifecycle")["status"], expected)

    def test_pipeline_evidence_cites_linked_stages_even_when_the_bullet_wraps(self):
        posting = b"Required: Understand the end-to-end data engineering and analytics workflow."
        examples = (
            (["Built an end-to-end data engineering and analytics workflow."], "PARTIALLY_MET"),
            (["• Built jobs that imported meter readings from message queues,",
              "validated reading timestamps, and published rollups for fleet reports."], "MET"),
            (["• Built pipelines that ingested meter readings from message queues.",
              "• Validated sensor codes in a training dataset.",
              "• Published stock movements for inventory reporting."], "PARTIALLY_MET"),
        )
        for example, expected in examples:
            with self.subTest(example=example):
                row = by_text(evaluate(make_pdf([*HEADER, "Experience", *example]), posting), "end-to-end")
                self.assertEqual(row["status"], expected)
                if expected == "MET":
                    self.assertEqual(len(row["evidence"]), 2)
                    self.assertIn("published rollups", row["evidence"][1]["quote"])

    def test_client_guidance_and_a_separate_ai_project_leave_a_linkage_gap(self):
        posting = b"Responsibilities: Guide clients in technical decisions through AI-assisted workflows."
        separated = [*HEADER, "Experience", "Advised clients on production deployment options.",
                     "Projects", "Piloted an AI-assisted workflow to draft internal diagnostics."]
        connected = [*HEADER, "Experience",
                     "Advised clients on production deployments using diagnostics from an AI-assisted workflow."]
        self.assertEqual(by_text(evaluate(make_pdf(separated), posting), "Guide clients")["status"], "PARTIALLY_MET")
        self.assertEqual(by_text(evaluate(make_pdf(connected), posting), "Guide clients")["status"], "MET")

    def test_terminology_and_title_are_diagnostics_for_the_default_rubric(self):
        posting = b"""Job Title: Operations Data Engineer
Required: Python.
Responsibilities: Build client billing dashboards.
"""
        example = "Built client billing dashboards with Python to reconcile monthly invoicing."
        reports = [evaluate(make_pdf([*HEADER, "Experience", f"{title} 2020/01 - 2024/03", example]), posting)
                   for title in ("Operations Data Engineer", "Reporting Developer")]
        self.assertGreater(reports[0]["job_match"]["components"]["title"]["score"],
                           reports[1]["job_match"]["components"]["title"]["score"])
        self.assertEqual(reports[0]["job_match"]["score"], reports[1]["job_match"]["score"])
        self.assertEqual(reports[0]["job_match"]["components"]["keywords"]["weight"], 0)


if __name__ == "__main__":
    unittest.main()
