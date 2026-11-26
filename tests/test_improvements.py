"""Gap analysis, applications, calibration, cover letters, scaffolding, and score regressions."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from career.files import CareerError, dump_yaml
from career.gaps import gaps
from career.knowledge import load_knowledge
from career.letter import build_letter
from career.models import Letter
from evaluation.calibration import auc, calibrate
from evaluation.crosscheck import cross_check, order_agreement
from evaluation.engine import evaluate
from evaluation.reporting import write_evaluation

from test_evaluation import PARTIAL, POSTING, STRONG, STUFFED, UNRELATED, make_pdf

FIXTURE = Path(__file__).parent / "fixtures" / "demo"

# Changing these values requires a deliberate rubric or engine version bump.
EXPECTED_SCORES = {
    "strong": (STRONG, 100.0, 100, 94.84),
    "partial": (PARTIAL, 34.11, 12.15, 20.94),
    "unrelated": (UNRELATED, 31.75, 9.0, 12.5),
    "stuffed": (STUFFED, 54.17, 38.9, 20.0),
}


class Root(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        shutil.copytree(FIXTURE / "knowledge", self.root / "knowledge")

    def run_cli(self, module, *args, ok=True):
        result = subprocess.run([sys.executable, "-m", module, *map(str, args)],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result.stdout if ok else result.stderr


class ScoreRegression(unittest.TestCase):
    def test_fixture_scores_are_stable(self):
        for name, (lines, overall, job, semantic) in EXPECTED_SCORES.items():
            with self.subTest(name):
                report = evaluate(make_pdf(lines), POSTING, as_of=date(2024, 12, 1))
                self.assertEqual(report["overall"]["score"], overall)
                self.assertEqual(report["job_match"]["score"], job)
                self.assertEqual(report["semantic_fit"]["score"], semantic)

    def test_strong_outranks_every_weaker_fixture(self):
        scores = {name: evaluate(make_pdf(spec[0]), POSTING, as_of=date(2024, 12, 1))["overall"]["score"]
                  for name, spec in EXPECTED_SCORES.items()}
        self.assertEqual(max(scores, key=scores.get), "strong")
        self.assertGreater(scores["partial"], scores["unrelated"])


class CliTests(Root):
    def test_root_is_accepted_after_the_subcommand(self):
        before = json.loads(self.run_cli("career", "--root", self.root, "validate"))
        after = json.loads(self.run_cli("career", "validate", "--root", self.root))
        self.assertEqual(before, after)

    def test_evaluator_refuses_unreadable_pdf_unless_allowed(self):
        pdf = self.root / "blank.pdf"
        pdf.write_bytes(make_pdf([]))
        error = self.run_cli("evaluation", "score", "blank", "--pdf", pdf, "--posting", FIXTURE / "posting.txt",
                             "--root", self.root, ok=False)
        self.assertIn("no extractable text", error)
        self.assertFalse((self.root / "evaluations" / "blank").exists())
        self.run_cli("evaluation", "score", "blank", "--pdf", pdf, "--posting", FIXTURE / "posting.txt",
                     "--root", self.root, "--allow-unreadable")

    def test_init_creates_layout_without_overwriting(self):
        target = self.root / "private"
        first = json.loads(self.run_cli("career", "--root", target, "init"))
        self.assertIn(".github/workflows/career-data.yml", first["created"])
        (target / "README.md").write_text("mine", encoding="utf-8")
        second = json.loads(self.run_cli("career", "--root", target, "init"))
        self.assertEqual(second["created"], [])
        self.assertEqual((target / "README.md").read_text(encoding="utf-8"), "mine")
        self.run_cli("career", "--root", target, "validate")

    def test_run_stops_for_missing_inputs(self):
        self.run_cli("career", "--root", self.root, "start", "job", FIXTURE / "posting.txt")
        result = json.loads(self.run_cli("career", "--root", self.root, "run", "job"))
        self.assertEqual(result["stopped"], "missing analysis.yaml")

    def test_applications_track_outcomes(self):
        (self.root / "resumes" / "job-v1").mkdir(parents=True)
        self.run_cli("career", "--root", self.root, "apply", "job-v1", "submitted", ok=False)
        self.run_cli("career", "--root", self.root, "apply", "job-v1", "submitted",
                     "--employer", "Juniper Research Lab", "--date", "2026-01-02")
        self.run_cli("career", "--root", self.root, "apply", "job-v1", "rejected", "--date", "2026-01-01", ok=False)
        self.run_cli("career", "--root", self.root, "apply", "job-v1", "interview", "--date", "2026-01-09")
        summary = json.loads(self.run_cli("career", "--root", self.root, "applications"))
        self.assertEqual((summary["total"], summary["advanced"]), (1, 1))
        self.assertEqual(summary["applications"][0]["latest"], "interview")


class GapTests(Root):
    def test_gaps_use_only_verified_facts(self):
        result = gaps(load_knowledge(self.root), (FIXTURE / "posting.txt").read_text(encoding="utf-8"))
        rows = {row["requirement"]: row for row in result["requirements"]}
        python = rows["Required: Develop data workflows using Python."]
        self.assertEqual(python["status"], "MET")
        self.assertIn("experience-observatory#ingestion", python["sources"])
        kubernetes = rows["Required: Operate production Kubernetes clusters."]
        # The orchestration fact needs confirmation, so it cannot satisfy the requirement.
        self.assertNotEqual(kubernetes["status"], "MET")
        self.assertNotIn("experience-observatory#orchestration", kubernetes["sources"])


class LetterTests(Root):
    def letter(self, text, evidence):
        return Letter.model_validate({
            "profile": "profile-morgan", "as_of": "2026-01-01",
            "paragraphs": [[{"text": text, "evidence": evidence}]],
        })

    def test_letter_cites_verified_facts(self):
        text, evidence = build_letter(load_knowledge(self.root), self.letter(
            "I automated a Python ingestion workflow that cut processing time by 25%.",
            ["experience-observatory#ingestion"]))
        self.assertIn("cut processing time by 25%", text)
        self.assertIn("experience-observatory#ingestion", evidence["claims"]["/paragraphs/0/0"]["evidence"])

    def test_letter_rejects_changed_numbers_and_unconfirmed_facts(self):
        knowledge = load_knowledge(self.root)
        with self.assertRaisesRegex(CareerError, "numbers"):
            build_letter(knowledge, self.letter("I cut processing time by 40%.", ["experience-observatory#ingestion"]))
        with self.assertRaisesRegex(CareerError, "needs confirmation"):
            build_letter(knowledge, self.letter("I operated Kubernetes.", ["experience-observatory#orchestration"]))


class CalibrationTests(unittest.TestCase):
    def test_auc(self):
        self.assertEqual(auc([90, 80], [10, 20]), 1.0)
        self.assertEqual(auc([10], [90]), 0.0)
        self.assertEqual(auc([50], [50]), 0.5)
        self.assertIsNone(auc([], [1]))

    def test_calibrate_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            cases = []
            for name, lines, advanced in (("strong", STRONG, True), ("unrelated", UNRELATED, False)):
                path = Path(directory) / name
                path.mkdir()
                write_evaluation(path, evaluate(make_pdf(lines), POSTING, as_of=date(2024, 12, 1)))
                cases.append({"id": name, "report": path / "ats-evaluation.json", "advanced": advanced})
            result = calibrate(cases)
        self.assertEqual(result["metrics"]["overall"]["auc"], 1.0)
        self.assertTrue(any("anecdotal" in warning for warning in result["warnings"]))


class CrossCheckTests(unittest.TestCase):
    def test_single_column_pdf_agrees(self):
        pdf = make_pdf(STRONG)
        text = "\n".join(STRONG)
        result = cross_check(pdf, text)
        self.assertTrue(result["readers"]["pypdf-plain"]["available"])
        self.assertFalse(result["warning"])

    def test_order_agreement(self):
        self.assertEqual(order_agreement("a b c".split(), "a b c".split()), 1.0)
        self.assertEqual(order_agreement("a b c".split(), "c b a".split()), 0.0)


class RunPipelineTests(unittest.TestCase):
    def test_run_previews_waits_for_review_then_seals(self):
        from test_workflow import WorkflowTests, reviewed

        case = WorkflowTests("test_end_to_end_render_verify_diff_and_reproduce")
        case.setUp()
        self.addCleanup(case.doCleanups)
        work = case.work()
        first = json.loads(case.cli("run", "sample"))
        self.assertEqual(first["stopped"], "awaiting review")
        packet = json.loads(case.cli("inspect", "sample"))
        (work / "review.yaml").write_text(dump_yaml(reviewed(packet)), encoding="utf-8")
        ready = json.loads(case.cli("run", "sample"))
        self.assertEqual(ready["stopped"], "ready to finish")
        self.assertTrue(ready["preview"]["reused"])
        done = json.loads(case.cli("run", "sample", "--version", "sample-v1"))
        self.assertIsNone(done["stopped"])
        self.assertEqual(done["verify"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
