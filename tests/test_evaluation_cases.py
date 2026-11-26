"""Evidence expectations for posting formats found in the three-case evaluation."""

import unittest

from evaluation.engine import evaluate
from tests.test_evaluation import HEADER, by_text, make_pdf

CLINICAL_POSTING = b"""Work Mode: Hybrid
Three days per week at the regional office.
About the role:
We are seeking a Clinical Data Engineer II to maintain clinical study integrations.

**Your responsibilities will include:**
* Develop **clinical data pipelines** for a regulated environment.
* Build cloud infrastructure using AWS Lambda and Amazon S3.

Required qualifications:
- 3+ years of software engineering or platform engineering experience.
- Backend development with Python.
- SQL development skills.

Preferred qualifications:
- Experience supporting clinical trials.

Requisition ID: TST-101
As a leader in clinical research, we are expanding our teams.
"""
CLINICAL_UNRELATED = [
    *HEADER, "Experience", "Hotel Receptionist 2019/01 - 2025/01",
    "Managed guest check-ins and resolved booking disputes for a busy hotel.",
    "Skills", "Reservations and customer service",
]

PIPELINE_POSTING = b"""Description
As a Data Engineer, you will build reliable analytics infrastructure.

Key Responsibilities:
- Design and optimize large-scale data pipelines.
- Mentor junior engineers.

Qualifications:
- Experience with ETL processes, data warehousing, and big data technologies.
- Programming in Python, Java, or Scala.
- Familiarity with cloud platforms and services for data processing and storage.

We welcome candidates who are passionate about our mission and encourage you to apply.
"""
PIPELINE_PARTIAL = [
    *HEADER, "Experience", "Data Integration Analyst 2023/01 - 2025/07",
    "Built scheduled Python ETL pipelines to process inventory records.",
    "Used AWS services for data processing and storage of inventory feeds.",
    "Skills", "Python | SQL | AWS",
]

SOLUTIONS_POSTING = b"""Cloud Solutions Engineer

The impact you will have:
You will ensure clients have an excellent experience by providing technical assistance across their lifecycle.
You will work directly with multiple clients concurrently to provide technical solutions.

What we look for:
Excellent communication skills, with the ability to assess customer needs, foster relationships, and address objections.
2+ years of experience in a technical role, preferably in data or AI.
Knowledge of at least one of the following cloud platforms, AWS, Azure, or GCP, is required.
AI-driven development using Python or SQL.
Bonus: Experience in consulting or pre-sales roles.

About Example Company
Our engineers maintain partnerships across several regions.
"""
SOLUTIONS_STRONG = [
    *HEADER, "Experience", "Cloud Solutions Engineer 2020/01 - 2025/05",
    "Provided technical assistance across the client lifecycle from trial to production.",
    "Managed 8 concurrent client engagements through technical onboarding.",
    "Assessed customer needs and addressed objections in trial workshops.",
    "Built AWS onboarding services with four teams in a technical role with 4 years of experience.",
    "Developed AI-driven workflows in Python for technical consulting engagements.",
    "Skills", "AWS | Python",
]


class ThreeCaseEvals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = ((CLINICAL_UNRELATED, CLINICAL_POSTING), (PIPELINE_PARTIAL, PIPELINE_POSTING),
                 (SOLUTIONS_STRONG, SOLUTIONS_POSTING))
        cls.low, cls.medium, cls.high = (evaluate(make_pdf(lines), posting) for lines, posting in cases)

    def test_low_fit_excludes_metadata_and_retains_duties(self):
        self.assertEqual(self.low["role"], "Clinical Data Engineer II")
        for phrase in ("Work Mode", "Requisition ID", "leader in clinical research"):
            self.assertEqual(by_text(self.low, phrase)["status"], "NOT_APPLICABLE")
        clinical = by_text(self.low, "clinical data pipelines")
        self.assertEqual((clinical["posting_line"], clinical["kind"]), (7, "responsibility"))
        self.assertEqual(self.low["coverage"]["required"]["statuses"], {"NOT_DEMONSTRATED": 5})

    def test_medium_fit_credits_etl_without_assuming_scale_or_mentoring(self):
        self.assertEqual(self.medium["role"], "Data Engineer")
        compound = by_text(self.medium, "ETL processes")
        self.assertEqual(compound["status"], "PARTIALLY_MET")
        self.assertIn("data warehousing", compound["explanation"].lower())
        self.assertTrue(any("Built scheduled Python ETL" in item["quote"] for item in compound["evidence"]))
        self.assertEqual(by_text(self.medium, "large-scale")["status"], "PARTIALLY_MET")
        self.assertEqual(by_text(self.medium, "Mentor junior")["status"], "NOT_DEMONSTRATED")
        self.assertEqual(by_text(self.medium, "cloud platforms")["status"], "MET")
        self.assertEqual(by_text(self.medium, "We welcome candidates")["status"], "NOT_APPLICABLE")

    def test_high_fit_counts_tenure_lifecycle_and_one_cloud_with_evidence(self):
        tenure = by_text(self.high, "2+ years")
        self.assertEqual((tenure["category"], tenure["status"]), ("required", "MET"))
        self.assertEqual(tenure["evidence"][0]["basis"], "explicit duration")
        self.assertIn("4 years", tenure["evidence"][0]["quote"])
        self.assertEqual(by_text(self.high, "across their lifecycle")["status"], "MET")
        self.assertEqual(by_text(self.high, "multiple clients")["status"], "PARTIALLY_MET")
        self.assertEqual(by_text(self.high, "foster relationships")["status"], "PARTIALLY_MET")
        self.assertEqual(by_text(self.high, "one of the following cloud platforms")["status"], "MET")
        self.assertIn({"terms": ["aws", "azure", "gcp"], "matched": ["aws"]}, self.high["keywords"]["groups"])
        self.assertFalse(any("azure" in term or "gcp" in term for term in self.high["keywords"]["missing"]))

    def test_job_match_orders_the_cases_at_equal_readiness(self):
        reports = (self.low, self.medium, self.high)
        self.assertEqual([report["ats_readiness"]["score"] for report in reports], [100, 100, 100])
        scores = [report["job_match"]["score"] for report in reports]
        self.assertEqual(scores[0], 0)
        self.assertLess(*scores[:2])
        self.assertLess(*scores[1:])

    def test_inventory_and_unrelated_tenure_do_not_satisfy_scope(self):
        pdf = make_pdf([
            *CLINICAL_UNRELATED[:4], "Managed reservations with 6 years of experience in hospitality.",
            "Skills", "AWS | Azure | GCP | Python | SQL | AI-driven development",
        ])
        report = evaluate(pdf, SOLUTIONS_POSTING)
        self.assertEqual(by_text(report, "2+ years")["status"], "NOT_DEMONSTRATED")
        self.assertEqual(by_text(report, "one of the following cloud platforms")["status"], "PARTIALLY_MET")
        self.assertEqual(by_text(report, "technical assistance")["status"], "NOT_DEMONSTRATED")
        self.assertLess(report["job_match"]["score"], self.medium["job_match"]["score"])

    def test_independent_cloud_requirement_still_applies(self):
        posting = SOLUTIONS_POSTING.replace(b"Bonus:", b"Azure experience is required.\nBonus:")
        report = evaluate(make_pdf(SOLUTIONS_STRONG), posting)
        self.assertEqual(by_text(report, "at least one")["status"], "MET")
        self.assertEqual(by_text(report, "Azure experience")["status"], "NOT_DEMONSTRATED")
        self.assertIn("azure", report["keywords"]["missing"])

    def test_different_field_retains_real_duties_and_qualified_tenure(self):
        pdf = make_pdf([
            *HEADER, "Experience", "Field Service Technician 2020/02 - 2024/06",
            "Wrote equipment calibration instructions for three workshops.",
            "Worked 4 years in electrical maintenance, servicing heavy equipment.",
            "Skills", "Electrical maintenance and equipment diagnostics",
        ])
        posting = b"""Field Service Technician
Key Responsibilities:
- Write equipment calibration instructions.
Required qualifications:
- 3+ years of electrical maintenance or instrument repair experience, preferably in a hospital.
- 3+ years of instrument repair experience.
"""
        report = evaluate(pdf, posting)
        self.assertEqual(by_text(report, "calibration instructions")["status"], "MET")
        self.assertEqual(by_text(report, "preferably in a hospital")["status"], "MET")
        self.assertEqual(by_text(report, "of instrument repair experience")["status"], "NOT_DEMONSTRATED")

    def test_named_degree_alternatives_and_unlisted_field(self):
        posting = b"Required: Undergraduate degree in Computer Science, Information Systems, or relevant experience."
        for field, expected in (("Information Systems", "MET"), ("History", "PARTIALLY_MET")):
            with self.subTest(field=field):
                pdf = make_pdf([*HEADER, "Education", f"Bachelor's degree in {field}", "Skills", "Research"])
                self.assertEqual(by_text(evaluate(pdf, posting), "Undergraduate degree")["status"], expected)


if __name__ == "__main__":
    unittest.main()
