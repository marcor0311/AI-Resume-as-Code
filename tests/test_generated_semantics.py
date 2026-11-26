"""Keep the seeded benchmark and the semantic evidence assertions in the test suite."""

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from tests.semantic_evals import run, same_inputs
from tests.semantic_profiles import generate


class GeneratedSemanticEvals(unittest.TestCase):
    def test_seed_repeats_the_plan_and_other_seeds_change_inputs(self):
        first = generate(17, 2)
        self.assertEqual(first, generate(17, 2))
        self.assertNotEqual([case.posting for case in first], [case.posting for case in generate(8331, 2)])
        self.assertTrue(all(len(case.profiles) == 7 for case in first))

    def test_generated_evidence_checks_and_relative_order(self):
        report = run([17, 8331], 2)
        for case in report["cases"]:
            with self.subTest(case=case["case"]):
                self.assertTrue(case["ranking_ok"])
                for profile in case["profiles"]:
                    for check in profile["checks"]:
                        self.assertTrue(check["status_ok"] and check["citation_ok"] and check["kind_ok"],
                                        (profile["profile"], check))

    def test_replay_preserves_pdf_and_posting_hashes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            first = run([17], 1, path)
            replay = run([17], 1, replay=path)
            self.assertTrue(same_inputs(first, replay))
            self.assertEqual(first["summary"], replay["summary"])


if __name__ == "__main__":
    unittest.main()
