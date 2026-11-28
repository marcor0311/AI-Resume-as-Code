"""Check targeted resume edits at three levels of evidence for the posting."""

import unittest

from evaluation.engine import evaluate
from evaluation.reporting import compare, evaluation_markdown
from tests.test_evaluation import by_text, make_pdf
from tests.test_evaluation_cases import (
    CLINICAL_POSTING,
    CLINICAL_UNRELATED,
    PIPELINE_PARTIAL,
    PIPELINE_POSTING,
    SOLUTIONS_POSTING,
    SOLUTIONS_STRONG,
)

HOSPITALITY_EXPERIENCE = [
    *CLINICAL_UNRELATED[:-2],
    "Documented hotel check-in procedures for the reception team.",
]
HOSPITALITY_SKILLS = [
    "Skills", "Reservations and customer service", "Room availability tracking", "Local travel information",
    "Daily occupancy reporting", "Booking reconciliation", "Guest feedback tracking",
]
PIPELINE_BEFORE = [
    line.replace("Python ETL pipelines", "ETL pipelines") for line in PIPELINE_PARTIAL
]
SOLUTIONS_BEFORE = [
    line.replace(" across the client lifecycle", "") for line in SOLUTIONS_STRONG
]


def refinement_reports() -> dict:
    pairs = (
        ("Unrelated profile, one reading column", CLINICAL_POSTING,
         make_pdf(HOSPITALITY_EXPERIENCE, HOSPITALITY_SKILLS),
         make_pdf([*HOSPITALITY_EXPERIENCE, *HOSPITALITY_SKILLS])),
        ("Partial fit, Python use in experience", PIPELINE_POSTING,
         make_pdf(PIPELINE_BEFORE), make_pdf(PIPELINE_PARTIAL)),
        ("Strong fit, explicit lifecycle evidence", SOLUTIONS_POSTING,
         make_pdf(SOLUTIONS_BEFORE), make_pdf(SOLUTIONS_STRONG)),
    )
    return {name: (evaluate(before, posting), evaluate(after, posting)) for name, posting, before, after in pairs}


class RefinementEvals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unrelated, cls.partial, cls.strong = refinement_reports().values()

    def test_one_column_improves_readiness_with_the_same_unrelated_experience(self):
        before, after = self.unrelated
        against_same_posting = compare(before, after)
        self.assertGreater(against_same_posting["scores"]["ats_readiness"]["delta"], 0)
        self.assertEqual(against_same_posting["scores"]["job_match"]["delta"], 0)
        self.assertEqual(after["job_match"]["score"], 0)
        self.assertEqual(before["recommendations"][0]["kind"], "format")
        self.assertIn("column_reading_order", {issue["code"] for issue in before["ats_readiness"]["issues"]})
        self.assertEqual({item["kind"] for item in after["recommendations"]}, {"verify_gap"})

    def test_partial_fit_credits_verified_use_and_keeps_warehouse_and_mentoring_gaps(self):
        before, after = self.partial
        self.assertGreater(compare(before, after)["scores"]["job_match"]["delta"], 0)
        inventory = by_text(before, "Programming in Python")
        self.assertEqual((inventory["status"], inventory["improvement_kind"]), ("PARTIALLY_MET", "clarify_evidence"))
        self.assertEqual(inventory["resume_sections"], ["skills"])
        demonstrated = by_text(after, "Programming in Python")
        self.assertEqual((demonstrated["status"], demonstrated["improvement_kind"]), ("MET", None))
        self.assertIn("Built scheduled Python ETL", demonstrated["evidence"][0]["quote"])
        self.assertEqual(by_text(after, "ETL processes")["status"], "PARTIALLY_MET")
        self.assertIn("Data warehousing", by_text(after, "ETL processes")["explanation"])
        self.assertEqual(by_text(after, "Mentor junior")["improvement_kind"], "verify_gap")

    def test_strong_fit_credits_a_clearer_description_of_the_same_lifecycle(self):
        before, after = self.strong
        result = compare(before, after)
        self.assertGreater(result["scores"]["job_match"]["delta"], 0)
        self.assertEqual(result["scores"]["ats_readiness"]["delta"], 0)
        self.assertEqual(by_text(before, "across their lifecycle")["status"], "PARTIALLY_MET")
        self.assertEqual(by_text(after, "across their lifecycle")["status"], "MET")
        self.assertEqual(by_text(after, "foster relationships")["status"], "PARTIALLY_MET")
        self.assertIn("Clarify evidence", evaluation_markdown(before))

    def test_a_relevant_word_can_recur_in_distinct_bullets(self):
        pdf = make_pdf([
            *SOLUTIONS_STRONG[:-2],
            "Documented customer feedback after trial workshops.",
            "Built customer onboarding templates for partner engineers.",
            "Maintained a customer escalation runbook for on-call staff.",
            "Tested customer data handoffs to ensure complete access.",
            "Configured alerts for customer adoption during trials.",
            *SOLUTIONS_STRONG[-2:],
        ])
        report = evaluate(pdf, SOLUTIONS_POSTING)
        self.assertIn("customer", report["keywords"]["matched"])
        self.assertEqual(report["job_match"]["stuffing_penalty"], 0)
        self.assertFalse(report["keyword_stuffing_warnings"])

    def test_a_concentrated_keyword_repetition_still_has_a_penalty(self):
        pdf = make_pdf([*SOLUTIONS_STRONG, "AWS AWS AWS AWS AWS AWS"])
        report = evaluate(pdf, SOLUTIONS_POSTING)
        notice, = report["keyword_stuffing_warnings"]
        self.assertEqual(notice["code"], "repeated_term")
        self.assertEqual(notice["evidence"]["quote"], "AWS AWS AWS AWS AWS AWS")
        self.assertGreater(report["job_match"]["stuffing_penalty"], 0)


if __name__ == "__main__":
    unittest.main()
