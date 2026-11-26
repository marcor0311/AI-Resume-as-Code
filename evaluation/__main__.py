"""Evaluate and compare PDF resumes independently of generation."""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

from ruamel.yaml.error import YAMLError

from career.files import CareerError, json_text, new_directory, write_json

from .calibration import calibrate, cases_from_applications, cases_from_file
from .config import DEFAULT_CONFIG, Rubric, load_rubric
from .crosscheck import cross_check
from .engine import evaluate
from .pdf import extract
from .reporting import compare, comparison_markdown, read_report, write_evaluation


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value) or len(value) > 80:
        raise argparse.ArgumentTypeError("use an ID such as platform-engineer-v1")
    return value


ROOT_HELP = "private data root (defaults to CAREER_DATA_ROOT or the current directory)"


def arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="career-eval", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("CAREER_DATA_ROOT", ".")), help=ROOT_HELP)
    commands = parser.add_subparsers(dest="command", required=True)
    score = commands.add_parser("score", help="score a final PDF against its original English posting")
    score.add_argument("id", type=identifier)
    score.add_argument("--pdf", type=Path, required=True)
    score.add_argument("--posting", type=Path, required=True)
    score.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="trusted owner-selected rubric")
    score.add_argument("--as-of", type=date.fromisoformat, help="explicit date for active jobs or credentials")
    score.add_argument("--no-semantic", action="store_true")
    score.add_argument("--expected-text", type=Path, help="unscored checks of expected source phrases, one per line")
    score.add_argument("--allow-unreadable", action="store_true",
                       help="save a report even when the PDF has no extractable text")
    calibration = commands.add_parser("calibrate", help="check whether scores rank recorded application outcomes")
    calibration.add_argument("--cases", type=Path, help="YAML list of {id, report, advanced} instead of applications/")
    comparison = commands.add_parser("compare", help="compare reports for the same posting and evaluator")
    comparison.add_argument("baseline", type=Path)
    comparison.add_argument("candidate", type=Path)
    comparison.add_argument("--output-id", type=identifier)
    comparison.add_argument("--json", action="store_true", help="print the machine-readable comparison")
    rubric = commands.add_parser("rubric", help="show or validate a rubric")
    rubric.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    rubric.add_argument("--schema", action="store_true")
    for command in commands.choices.values():
        command.add_argument("--root", type=Path, default=argparse.SUPPRESS, help=ROOT_HELP)
    return parser.parse_args(argv)


def require_text(pdf: bytes, rubric: Rubric) -> str:
    """Refuse to score a PDF that no parser can read instead of reporting a misleading zero."""
    document = extract(pdf, rubric)
    if document.unreadable:
        detail = "; ".join(issue["detail"] for issue in document.issues if issue["severity"] == "error")
        raise CareerError(f"the PDF cannot be read ({detail}). Pass --allow-unreadable to save a report anyway")
    if document.extracted_characters == 0:
        raise CareerError("the PDF has no extractable text, as with a scanned image. Export a text-based PDF "
                          "or pass --allow-unreadable to save a report anyway")
    return "\n".join(line.text for line in document.lines)


def destination(root: Path, directory: str, name: str) -> Path:
    parent = root.resolve() / directory
    if parent.is_symlink():
        raise CareerError(f"expected a local directory at {parent}")
    return parent / name


def input_bytes(path: Path, maximum: int) -> bytes:
    if not path.is_file():
        raise CareerError(f"expected a local file at {path}")
    with path.open("rb") as source:
        content = source.read(maximum + 1)
    if len(content) > maximum:
        raise CareerError(f"{path.name} exceeds the configured size limit")
    return content


def main() -> int:
    args = arguments()
    try:
        if args.command == "score":
            path = destination(args.root, "evaluations", args.id)
            rubric = load_rubric(args.config)
            expected = ()
            if args.expected_text:
                expected = tuple(line.strip() for line in args.expected_text.read_text(encoding="utf-8-sig").splitlines()
                                 if line.strip())
            pdf = input_bytes(args.pdf, rubric.thresholds.max_pdf_bytes)
            posting = input_bytes(args.posting, rubric.thresholds.max_posting_bytes)
            text = "" if args.allow_unreadable else require_text(pdf, rubric)
            report = evaluate(pdf, posting, rubric, as_of=args.as_of,
                              semantic=not args.no_semantic, expected=expected)
            report["cross_check"] = cross_check(pdf, text)
            with new_directory(path) as staging:
                write_evaluation(staging, report)
            output = json_text({
                "saved": str(path), "parser_warning": report["cross_check"]["note"], "overall": report["overall"]["score"], "ats_readiness": report["ats_readiness"]["score"],
                "job_match": report["job_match"]["score"], "semantic_fit": (
                    report["semantic_fit"]["score"] if report["semantic_fit"] else None
                ),
            })
        elif args.command == "compare":
            report = compare(read_report(args.baseline), read_report(args.candidate))
            if args.output_id:
                path = destination(args.root, "comparisons", args.output_id)
                with new_directory(path) as staging:
                    write_json(staging / "comparison.json", report)
                    (staging / "comparison.md").write_text(comparison_markdown(report), encoding="utf-8")
            output = json_text(report) if args.json else comparison_markdown(report)
        elif args.command == "calibrate":
            cases = cases_from_file(args.cases) if args.cases else cases_from_applications(args.root.resolve())
            output = json_text(calibrate(cases))
        elif args.schema:
            output = json_text(Rubric.model_json_schema())
        else:
            output = json_text(load_rubric(args.config).model_dump(mode="json"))
    except (CareerError, OSError, YAMLError, KeyError, TypeError, ValueError) as error:
        print(f"evaluation: {error}", file=sys.stderr)
        return 1
    print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
