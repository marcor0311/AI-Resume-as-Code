"""Run requirement-level evals on seeded synthetic posting and PDF pairs."""

import argparse
import json
from collections import Counter
from pathlib import Path

from career.files import CareerError, digest, new_directory, write_json
from evaluation.config import load_rubric
from evaluation.engine import ENGINE_VERSION, engine_identity, evaluate
from tests.semantic_profiles import generate
from tests.test_evaluation import make_pdf


def proof_text(text: str) -> str:
    return " ".join(text.replace("•", " ").split()).casefold()


def assess_profile(report: dict, lines: tuple[int, int], profile) -> list[dict]:
    scored = {row["posting_line"]: row for row in report["requirements"] if row["points"] is not None}
    results = []
    for kind, line, label, proof in zip(("duty", "qualification"), lines, profile.expected, profile.proof, strict=True):
        row = scored.get(line)
        actual = row["status"] if row else "MISSING_REQUIREMENT"
        expected_kind = "responsibility" if kind == "duty" else "qualification"
        kind_ok = bool(row and row["kind"] == expected_kind)
        evidence = row["evidence"] if row else []
        excerpts = " ".join(item["quote"] for item in sorted(evidence, key=lambda item: (item["page"], item["line"])))
        status_ok = (actual not in {"MET", "MISSING_REQUIREMENT"}) if label == "NO_FULL" else actual == label
        citation_ok = not proof or (bool(evidence) and proof_text(proof) in proof_text(excerpts))
        expected_met, actual_met = label == "MET", actual == "MET"
        result = {
            "kind": kind, "posting_line": line, "expected": label, "actual": actual,
            "status_ok": status_ok, "citation_ok": citation_ok, "kind_ok": kind_ok, "evidence": evidence,
            "coverage": ("true_positive" if actual_met else "false_negative") if expected_met else
                        ("false_positive" if actual_met else "true_negative"),
        }
        if row:
            result["explanation"] = row["explanation"]
        results.append(result)
    return results


def summarize(cases: list[dict]) -> dict:
    checks = [item for case in cases for profile in case["profiles"] for item in profile["checks"]]
    coverage = Counter(item["coverage"] for item in checks)
    tp, fp, fn = (coverage[key] for key in ("true_positive", "false_positive", "false_negative"))
    return {
        "postings": len(cases), "profiles": sum(len(case["profiles"]) for case in cases), "requirements": len(checks),
        "status_checks_passed": sum(item["status_ok"] for item in checks),
        "requirement_kinds_correct": sum(item["kind_ok"] for item in checks),
        "expected_met_with_correct_citation": sum(item["expected"] == "MET" and item["actual"] == "MET"
                                                  and item["citation_ok"] for item in checks),
        "expected_met": tp + fn,
        "met_precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "met_recall": round(tp / (tp + fn), 4) if tp + fn else None,
        "false_positives": fp, "false_negatives": fn,
        "ranking_checks_passed": sum(case["ranking_ok"] for case in cases),
    }


def run(seeds: list[int], count: int, directory: Path | None = None, *, replay: Path | None = None) -> dict:
    rubric = load_rubric()
    cases = []
    # Generate every expected outcome before evaluating an input.
    plans = [case for seed in seeds for case in generate(seed, count)]
    for plan in plans:
        posting = plan.posting.encode("utf-8")
        source = replay / plan.key if replay else None
        if source and (source / "posting.txt").read_bytes() != posting:
            raise CareerError(f"the posting for {plan.key} changed since the saved run")
        case_dir = directory / plan.key if directory else None
        if case_dir:
            case_dir.mkdir()
            (case_dir / "posting.txt").write_bytes(posting)
        profiles = []
        for profile in plan.profiles:
            pdf = (source / f"{profile.key}.pdf").read_bytes() if source else make_pdf(list(profile.lines))
            report = evaluate(pdf, posting, rubric)
            profiles.append({
                "profile": profile.key, "pdf_sha256": digest(pdf), "job_match": report["job_match"]["score"],
                "readiness": report["ats_readiness"]["score"],
                "checks": assess_profile(report, plan.requirement_lines, profile),
            })
            if case_dir:
                (case_dir / f"{profile.key}.pdf").write_bytes(pdf)
        scores = {item["profile"]: item["job_match"] for item in profiles}
        ranking_ok = (
            scores["direct"] == scores["paraphrase"] > scores["partial"]
            > max(scores[key] for key in ("inventory", "wrong-action", "negated", "unrelated"))
        )
        cases.append({"case": plan.key, "family": plan.family, "posting_sha256": digest(posting),
                      "ranking_ok": ranking_ok, "profiles": profiles})
    report = {
        "engine_version": ENGINE_VERSION, "engine_sha256": engine_identity(), "rubric": rubric.version,
        "seeds": seeds, "postings_per_family": count, "summary": summarize(cases),
        "families": {family: summarize([case for case in cases if case["family"] == family])
                     for family in sorted({case["family"] for case in cases})},
        "cases": cases,
    }
    if directory:
        write_json(directory / "report.json", report)
    return report


def same_inputs(baseline: dict, current: dict) -> bool:
    def fingerprints(report: dict) -> dict:
        return {case["case"]: (case["posting_sha256"], {p["profile"]: p["pdf_sha256"] for p in case["profiles"]})
                for case in report["cases"]}
    return fingerprints(baseline) == fingerprints(current)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, action="append", help="repeat to run multiple seeds; defaults to 17")
    parser.add_argument("--postings-per-family", type=int, help="defaults to two or the saved baseline's count")
    parser.add_argument("--output", type=Path, help="save the synthetic PDFs, postings, and JSON diagnostics")
    parser.add_argument("--baseline", type=Path, help="replay the saved PDFs and posting files next to an earlier report.json")
    args = parser.parse_args()
    try:
        baseline = json.loads(args.baseline.read_bytes()) if args.baseline else None
        seeds = list(dict.fromkeys(args.seed or (baseline["seeds"] if baseline else [17])))
        count = args.postings_per_family
        if count is None:
            count = baseline["postings_per_family"] if baseline else 2
        if count < 1:
            parser.error("--postings-per-family must be positive")
        replay = args.baseline.parent if args.baseline else None
        if args.output:
            with new_directory(args.output) as directory:
                report = run(seeds, count, directory, replay=replay)
                if baseline and not same_inputs(baseline, report):
                    raise CareerError("saved inputs do not match the baseline hashes")
        else:
            report = run(seeds, count, replay=replay)
            if baseline and not same_inputs(baseline, report):
                raise CareerError("saved inputs do not match the baseline hashes")
    except (CareerError, OSError, ValueError) as error:
        parser.error(str(error))
    summary = report["summary"]
    if baseline:
        print(f"Same inputs as evaluator {baseline['engine_version']}")
        for metric in ("status_checks_passed", "false_positives", "false_negatives", "ranking_checks_passed"):
            print(f"{metric}: {baseline['summary'][metric]} -> {summary[metric]}")
    print(json.dumps(summary, indent=2))
    for case in report["cases"]:
        for profile in case["profiles"]:
            for check in profile["checks"]:
                if not (check["status_ok"] and check["citation_ok"] and check["kind_ok"]):
                    print(f"{case['case']} / {profile['profile']} / {check['kind']}: "
                          f"expected {check['expected']}, got {check['actual']}, "
                          f"citation ok={check['citation_ok']}, kind ok={check['kind_ok']}")
    success = (summary["status_checks_passed"] == summary["requirements"]
               and summary["requirement_kinds_correct"] == summary["requirements"]
               and summary["expected_met_with_correct_citation"] == summary["expected_met"]
               and summary["ranking_checks_passed"] == summary["postings"])
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
