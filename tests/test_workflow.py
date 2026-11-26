import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from career import artifacts
from career.__main__ import prepare
from career.files import CareerError, digest, dump_yaml, parse_yaml, write_json
from career.knowledge import load_knowledge, retrieve, sync_index
from career.models import Draft, Review
from career.tailoring import QUALITY_DIMENSIONS, check_review, project

FIXTURE = Path(__file__).parent / "fixtures" / "demo"


def load_fixture(name):
    return parse_yaml((FIXTURE / name).read_bytes())


def reviewed(packet):
    """Frozen synthetic decisions. Changed draft claims use explicit rejection tests."""
    platform_path = "/cv/sections/Experience/0/highlights/0"
    dashboard_path = "/cv/sections/Experience/0/highlights/1"
    playbook_path = "/cv/sections/Projects/0/highlights/0"
    dashboards = dashboard_path in packet["claims"]
    coverage = [
        {"requirement": "python", "status": "covered", "claims": [platform_path],
         "reason": "The draft describes an automated Python ingestion workflow."},
        {"requirement": "kubernetes", "status": "needs_confirmation", "claims": [],
         "reason": "The owner has yet to confirm production Kubernetes experience."},
        {"requirement": "dashboards", "status": "covered" if dashboards else "gap",
         "claims": [dashboard_path] if dashboards else [],
         "reason": "The dashboard fact supports this only when the resume includes it."},
        {"requirement": "playbooks", "status": "partial", "claims": [playbook_path],
         "reason": "The project documents rollback procedures and supplies no direct rollback operation evidence."},
    ]
    claims = []
    for path, item in packet["claims"].items():
        source = [packet["evidence"][ref]["text"] for ref in item["evidence"]]
        unchanged = item["text"] in source
        claims.append({
            "path": path, "verdict": "verbatim" if unchanged else "supported_reformulation",
            "reason": "Copied from the cited source." if unchanged else
                      "The fixture preserves source meaning and precision in translation, wording, or display.",
        })
    notes = (
        "The resume foregrounds workflow reliability.",
        "Experience facts give direct evidence and the release note corroborates the 25% result.",
        "The bullets describe specific work and outcomes.",
        "Each narrative highlight begins with an action.",
        "Both percentages retain their original units and meaning where selected.",
        "The draft keeps brief bullets and avoids repeated outcomes.",
        "Titles and dates derive from the confirmed records.",
        "The PDF text follows the section order.",
        "The single-column preview is legible.",
    )
    return {
        "input_sha256": packet["input_sha256"], "reviewer": "Synthetic fixture review",
        "claims": claims, "coverage": coverage, "disposition": "ready",
        "quality": dict(zip(QUALITY_DIMENSIONS, notes, strict=True)),
    }


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        shutil.copytree(FIXTURE / "knowledge", self.root / "knowledge")

    def cli(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, "-m", "career", "--root", str(self.root), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result.stdout if ok else result.stderr

    def work(self, name="sample", draft="draft.yaml"):
        self.cli("start", name, FIXTURE / "posting.txt")
        work = self.root / "work" / name
        shutil.copyfile(FIXTURE / "analysis.yaml", work / "analysis.yaml")
        shutil.copyfile(FIXTURE / draft, work / "draft.yaml")
        return work

    def test_index_is_reproducible_and_excludes_pending_fact(self):
        knowledge = load_knowledge(self.root)
        first = sync_index(self.root, knowledge)
        index_path = self.root / "knowledge" / "index.json"
        original = index_path.read_bytes()
        self.assertEqual(first, sync_index(self.root, knowledge, check=True))
        sync_index(self.root, knowledge)
        self.assertEqual(original, index_path.read_bytes())
        entries = retrieve(first, ["Python", "incident response"], 10)
        self.assertEqual(entries[0]["id"], "experience-observatory")
        self.assertEqual(entries[0]["facts"], [
            "experience-observatory#ingestion", "experience-observatory#latency",
        ])
        index_path.write_text("{}")
        with self.assertRaisesRegex(CareerError, "stale"):
            sync_index(self.root, knowledge, check=True)

    def test_bad_record_shape_date_relationship_and_duplicate_keys(self):
        path = self.root / "knowledge" / "experience" / "experience-observatory.yaml"
        valid = path.read_text()
        for bad, match in (
            (valid.replace('"2022-04"', '"2022-02-30"'), "day is out of range|day 30"),
            (valid.replace("end_date: present", 'end_date: "2021"'), "precedes start"),
            (valid.replace("project-reliability", "project-unknown"), "invalid relationship"),
            (valid.replace("mentions: [skill-python]", "mentions: [project-reliability]"), "invalid mentions"),
            (valid + "title: Duplicate\n", "duplicate key"),
            (valid + "salary: 42\n", "Extra inputs"),
        ):
            with self.subTest(match=match):
                path.write_text(bad)
                self.assertRegex(self.cli("validate", ok=False), match)

    def test_job_quotes_come_from_the_supplied_bytes(self):
        work = self.work()
        analysis = load_fixture("analysis.yaml")
        analysis["requirements"][0]["quote"] = "Python is mandatory but this was never written."
        (work / "analysis.yaml").write_text(dump_yaml(analysis))
        self.assertIn("quote must appear", self.cli("inspect", "sample", ok=False))
        self.assertEqual((work / "posting.txt").read_bytes(), (FIXTURE / "posting.txt").read_bytes())
        self.assertIn("already exists", self.cli("start", "sample", FIXTURE / "posting.txt", ok=False))

    def test_volunteer_entry_has_its_own_section_and_evidence(self):
        record = self.root / "knowledge" / "volunteer" / "workshop-mentor.yaml"
        record.parent.mkdir()
        record.write_text(dump_yaml({
            "kind": "volunteer", "id": "workshop-mentor", "title": "Workshop Mentor",
            "organization": "Example Community Centre", "status": "verified",
            "start_date": "2024-01", "end_date": "2025-01",
            "facts": [{"id": "sessions", "status": "verified", "text": "Led weekend workshops."}],
        }), encoding="utf-8")
        draft = Draft.model_validate({
            "profile": "profile-morgan", "as_of": "2026-01-01",
            "entries": [{"record": "workshop-mentor", "highlights": [
                {"text": "Led weekend workshops.", "evidence": ["workshop-mentor#sessions"]},
            ]}],
        })
        projection = project(load_knowledge(self.root), draft)
        self.assertEqual(projection.document["cv"]["sections"], {"Volunteer Experience": [{
            "position": "Workshop Mentor", "company": "Example Community Centre",
            "date": "2024/01 - 2025/01", "highlights": ["Led weekend workshops."],
        }]})
        path = "/cv/sections/Volunteer Experience/0/highlights/0"
        self.assertEqual(projection.claims[path]["evidence"], ["workshop-mentor#sessions"])

    def test_rejects_non_english_posts_and_new_drafts(self):
        posting = self.root / "translated-first.txt"
        posting.write_text("Buscamos una persona con experiencia para las funciones. "
                           "Los requisitos incluyen conocimientos y habilidades profesionales.", encoding="utf-8")
        self.assertIn("posting must be supplied in English", self.cli("start", "foreign", posting, ok=False))
        self.assertFalse((self.root / "work" / "foreign").exists())
        draft = load_fixture("draft.yaml")
        draft["language"] = "spanish"
        with self.assertRaises(ValidationError):
            Draft.model_validate(draft)

    def test_unsupported_numbers_missing_facts_and_known_inventions(self):
        examples = [
            ("Increased efficiency by 250%.", "experience-observatory#ingestion", "unsupported numeric"),
            ("Improved the workflow by 25.", "experience-observatory#ingestion", "unsupported numeric"),
            ("Operated K8s.", "experience-observatory#ingestion", "unverified term 'Kubernetes'"),
            ("Operated Kubernetes.", "experience-observatory#orchestration", "needs confirmation"),
            ("Earned Certified Systems Operator.", "experience-observatory#ingestion", "unverified term"),
            ("Created new workflows.", "experience-observatory#missing", "missing or needs confirmation"),
            ("Wrote runbooks.", "project-reliability#runbooks", "must cite facts recorded under"),
        ]
        knowledge = load_knowledge(self.root)
        for wording, reference, expected in examples:
            with self.subTest(wording=wording):
                data = load_fixture("draft.yaml")
                data["entries"][0]["highlights"][0] = {"text": wording, "evidence": [reference]}
                with self.assertRaisesRegex(CareerError, expected):
                    project(knowledge, Draft.model_validate(data))

    def test_refuses_unverified_structured_values_and_future_employment(self):
        knowledge = load_knowledge(self.root)
        fixture = load_fixture("draft.yaml")
        fixture["skills"] = ["skill-kubernetes"]
        with self.assertRaisesRegex(CareerError, "listed skill needs support"):
            project(knowledge, Draft.model_validate(fixture))
        fixture["skills"] = []
        fixture["as_of"] = "2021-12-01"
        with self.assertRaisesRegex(CareerError, "date follows"):
            project(knowledge, Draft.model_validate(fixture))
        fixture["entries"][0]["organization"] = "Another company"
        with self.assertRaises(ValidationError):
            Draft.model_validate(fixture)

    def test_review_rejects_missing_stale_and_unsupported_claims(self):
        packet, analysis, _ = prepare(self.root, self.work())
        accepted = reviewed(packet)
        check_review(packet, analysis, Review.model_validate(accepted))
        for mutation, expected in (
            ({"claims": accepted["claims"][1:]}, "address every current"),
            ({"coverage": accepted["coverage"][:-1]}, "address every job"),
            ({"input_sha256": "0" * 64}, "stale"),
            ({"disposition": "revise"}, "requests revision"),
            ({"claims": [{**accepted["claims"][0], "verdict": "unsupported"},
                         *accepted["claims"][1:]]}, "unsupported"),
        ):
            with self.subTest(expected=expected):
                review = Review.model_validate({**accepted, **mutation})
                with self.assertRaisesRegex(CareerError, expected):
                    check_review(packet, analysis, review)

    def test_changed_source_invalidates_review(self):
        work = self.work()
        old_packet, _, _ = prepare(self.root, work)
        evidence = self.root / "knowledge" / "evidence" / "evidence-release.yaml"
        evidence.write_text(evidence.read_text().replace("deploying", "releasing"))
        packet, analysis, _ = prepare(self.root, work)
        with self.assertRaisesRegex(CareerError, "stale"):
            check_review(packet, analysis, Review.model_validate(reviewed(old_packet)))

    def test_reordering_sections_requires_a_new_review(self):
        work = self.work()
        old_packet, _, _ = prepare(self.root, work)
        data = load_fixture("draft.yaml")
        data["entries"][0], data["entries"][1] = data["entries"][1], data["entries"][0]
        (work / "draft.yaml").write_text(dump_yaml(data))
        packet, analysis, _ = prepare(self.root, work)
        self.assertNotEqual(packet["section_order"], old_packet["section_order"])
        with self.assertRaisesRegex(CareerError, "stale"):
            check_review(packet, analysis, Review.model_validate(reviewed(old_packet)))

    def test_failed_render_leaves_no_version_and_releases_the_lock(self):
        work = self.work()
        packet, analysis, inputs = prepare(self.root, work)
        review = Review.model_validate(reviewed(packet))
        coverage = check_review(packet, analysis, review)
        with patch("career.artifacts.render", side_effect=CareerError("test render failure")):
            with self.assertRaisesRegex(CareerError, "test render failure"):
                artifacts.seal(self.root, "v-failed", packet, inputs, coverage)
        self.assertEqual(list((self.root / "resumes").iterdir()), [])

    def test_archive_rejects_concurrent_or_existing_version(self):
        destination = self.root / "resumes" / "v-one"
        with artifacts.new_directory(destination) as directory:
            (directory / "one.txt").write_text("first")
            with self.assertRaisesRegex(CareerError, "another operation"):
                with artifacts.new_directory(destination):
                    self.fail("second writer entered staging")
        with self.assertRaisesRegex(CareerError, "already exists"):
            with artifacts.new_directory(destination):
                self.fail("existing version was opened for a write")
        self.assertEqual((destination / "one.txt").read_text(), "first")

    def test_end_to_end_render_verify_diff_and_reproduce(self):
        for name in ("sample-en", "sample-en-short"):
            with self.subTest(version=name):
                work = self.work(name=name)
                if name.endswith("short"):
                    draft_path = work / "draft.yaml"
                    data = parse_yaml(draft_path.read_bytes())
                    data["entries"][0]["highlights"].pop()
                    draft_path.write_text(dump_yaml(data))
                packet = json.loads(self.cli("inspect", name))
                preview = json.loads(self.cli("preview", name))
                self.assertEqual(preview["input_sha256"], packet["input_sha256"])
                self.assertEqual(preview["pages"], 1)
                (work / "review.yaml").write_text(dump_yaml(reviewed(packet)))
                self.cli("finish", name, name)
                self.cli("verify", name)
                archive = self.root / "resumes" / name
                validation = json.loads((archive / "validation.json").read_bytes())
                self.assertEqual(validation["semantic"]["requirement_coverage"]["mandatory"],
                                 {"covered": 1, "needs_confirmation": 1})
                pdf_text = self.cli("extract", archive / "resume.pdf")
                self.assertNotIn("experience-observatory#", pdf_text)
                self.assertNotIn("Kubernetes", pdf_text)
                self.assertIn("+1 202-555-0123", pdf_text)
                self.assertIn("Information Systems 2020", pdf_text)
                self.assertNotIn("Jan 2020", pdf_text)
                self.assertIn("Expiration: 2025/02/15", pdf_text)
                evaluation = json.loads((archive / "ats-evaluation.json").read_bytes())
                self.assertEqual(evaluation["inputs"]["pdf_sha256"], digest((archive / "resume.pdf").read_bytes()))
                self.assertEqual(evaluation["inputs"]["posting_sha256"], digest((archive / "posting.txt").read_bytes()))
                self.assertTrue((archive / "ats-evaluation.md").is_file())
        text_diff = self.cli("compare", "sample-en", "sample-en-short")
        self.assertIn("-• Built service dashboards", text_diff)
        shutil.rmtree(self.root / "knowledge")
        result = json.loads(self.cli("reproduce", "sample-en"))
        self.assertTrue(result["normalized_text_matches"])
        self.assertEqual(result["pages"], 1)
        original_result = Path(result["path"]) / "reproduction.json"
        original_bytes = original_result.read_bytes()
        rerun = json.loads(self.cli("reproduce", "sample-en", "--output-id", "sample-en-rerun"))
        self.assertEqual(rerun["version_id"], "sample-en")
        self.assertEqual(Path(rerun["path"]).name, "sample-en-rerun")
        self.assertTrue(rerun["normalized_text_matches"])
        self.assertEqual(original_result.read_bytes(), original_bytes)
        self.assertIn("already exists", self.cli("reproduce", "sample-en", "--output-id", "sample-en-rerun", ok=False))
        archive = self.root / "resumes" / "sample-en"
        (archive / "resume.txt").write_text("tampered")
        self.assertIn("checksum mismatch", self.cli("verify", "sample-en", ok=False))

    def test_archive_revalidates_analysis_and_review_even_with_matching_file_hashes(self):
        work = self.work()
        packet, _, _ = prepare(self.root, work)
        (work / "review.yaml").write_text(dump_yaml(reviewed(packet)))
        self.cli("finish", "sample", "sample-v1")
        archive = self.root / "resumes" / "sample-v1"
        manifest_path = archive / "manifest.json"
        original_manifest = manifest_path.read_bytes()
        for name, key, value, error in (
            ("analysis.yaml", "role", "Another role", "inconsistent recorded inputs"),
            ("review.yaml", "input_sha256", "0" * 64, "review is stale"),
        ):
            with self.subTest(name=name):
                path = archive / name
                original = path.read_bytes()
                edited = parse_yaml(original)
                edited[key] = value
                path.write_text(dump_yaml(edited))
                manifest = json.loads(original_manifest)
                manifest["sha256"][name] = digest(path.read_bytes())
                write_json(manifest_path, manifest)
                self.assertIn(error, self.cli("verify", "sample-v1", ok=False))
                path.write_bytes(original)
                manifest_path.write_bytes(original_manifest)
        self.cli("verify", "sample-v1")
        manifest = json.loads(original_manifest)
        manifest["schema_version"] = 1
        for name in ("ats-evaluation.md", "ats-evaluation.json"):
            manifest["sha256"].pop(name)
            (archive / name).unlink()
        write_json(manifest_path, manifest)
        self.cli("verify", "sample-v1")

    def test_pdf_check_detects_omissions(self):
        packet, _, _ = prepare(self.root, self.work())
        output = self.root / "pdf"
        output.mkdir()
        artifacts.render(output, packet)
        altered = copy.deepcopy(packet)
        altered["claims"]["/cv/name"]["expected_pdf_text"] = "Different Person"
        with self.assertRaisesRegex(CareerError, "PDF text omitted"):
            artifacts.verify_pdf(output / "resume.pdf", altered)
        altered = {**packet, "section_order": packet["section_order"][::-1]}
        with self.assertRaisesRegex(CareerError, "missing or out of order"):
            artifacts.verify_pdf(output / "resume.pdf", altered)


if __name__ == "__main__":
    unittest.main()
