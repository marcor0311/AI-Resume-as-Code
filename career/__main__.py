"""Run local career and resume workflows with `python -m career`."""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from pydantic import TypeAdapter
from pypdf.errors import PyPdfError
from ruamel.yaml.error import YAMLError

from evaluation.text import require_english

from . import applications, artifacts
from .files import CareerError, json_text, parse_yaml, write_json
from .gaps import gaps
from .knowledge import RECORD, load_knowledge, retrieve, sync_index
from .letter import build_letter, letter_evidence_text
from .models import Analysis, ApplicationEvent, Draft, Id, Letter, Review
from .scaffold import init
from .tailoring import check_review, project, review_input, validate_analysis

SCHEMAS = {"record": RECORD, "analysis": Analysis, "draft": Draft, "review": Review, "letter": Letter}
ID = TypeAdapter(Id)


def slug(value: str) -> str:
    try:
        return ID.validate_python(value, strict=True)
    except ValueError as error:
        raise argparse.ArgumentTypeError("use a lowercase ID such as platform-engineer-v1") from error


ROOT_HELP = "private data root (defaults to CAREER_DATA_ROOT or the current directory)"


def accept_root_anywhere(commands) -> None:
    """Let --root follow the subcommand as well as precede it."""
    for command in commands.choices.values():
        command.add_argument("--root", type=Path, default=argparse.SUPPRESS, help=ROOT_HELP)


def day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("use a YYYY-MM-DD date") from error


def arguments(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="career", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("CAREER_DATA_ROOT", ".")), help=ROOT_HELP)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create the layout of a private career data directory")
    gap = commands.add_parser("gaps", help="show which posting requirements verified facts cover")
    gap.add_argument("posting", type=Path)
    gap.add_argument("--as-of", type=day, help="explicit date for active jobs or credentials")
    run = commands.add_parser("run", help="validate and preview a draft, then finish and verify once reviewed")
    run.add_argument("draft", type=slug)
    run.add_argument("--version", type=slug, help="version ID to save when review.yaml is ready")
    commands.add_parser("letter", help="validate letter.yaml and write an evidence-backed cover letter").add_argument(
        "draft", type=slug)
    apply = commands.add_parser("apply", help="record an application event for a saved version")
    apply.add_argument("version", type=slug)
    apply.add_argument("status", choices=["submitted", "screen", "interview", "offer", "rejected", "withdrawn", "no_response"])
    apply.add_argument("--date", type=day, default=None, help="event date (defaults to today)")
    apply.add_argument("--employer")
    apply.add_argument("--role")
    apply.add_argument("--note")
    commands.add_parser("applications", help="summarize recorded applications and their outcomes")
    commands.add_parser("setup-renderer", help="install and verify required Typst assets").add_argument(
        "--archive", type=Path, help="use an existing Typst registry archive for offline setup",
    )
    commands.add_parser("validate", help="validate canonical records and relationships")
    commands.add_parser("index", help="generate the local discovery index").add_argument("--check", action="store_true")
    find = commands.add_parser("retrieve", help="rank discovery metadata by words or phrases")
    find.add_argument("terms", nargs="*")
    find.add_argument("--limit", type=int, default=12)
    commands.add_parser("schema", help="print JSON Schema").add_argument("contract", choices=SCHEMAS)
    commands.add_parser("extract", help="read a local PDF, Markdown, text, or YAML file").add_argument("source", type=Path)
    start = commands.add_parser("start", help="preserve a manually supplied job posting")
    start.add_argument("draft", type=slug)
    start.add_argument("posting", type=Path)
    for name, help_text in {
        "inspect": "validate the draft and print the evidence packet for review",
        "preview": "render and verify a draft PDF in the work directory",
        "finish": "validate, render, and preserve a reviewed resume version",
    }.items():
        command = commands.add_parser(name, help=help_text)
        command.add_argument("draft", type=slug)
        if name == "finish":
            command.add_argument("version", type=slug)
    for name, help_text in {
        "verify": "verify the saved version and its PDF text",
        "reproduce": "render a historical version from its saved input",
        "compare": "show the text differences between two saved versions",
    }.items():
        command = commands.add_parser(name, help=help_text)
        command.add_argument("version", type=slug)
        if name == "compare":
            command.add_argument("other", type=slug)
        if name == "reproduce":
            command.add_argument("--output-id", type=slug, help="save to a fresh result directory with this ID")
    accept_root_anywhere(commands)
    return parser.parse_args(argv)


def read_input(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise CareerError(f"expected a regular local file at {path}")
    return path.read_bytes()


def local_directory(root: Path, parent: str, name: str) -> Path:
    container = root / parent
    path = container / name
    if container.is_symlink() or path.is_symlink():
        raise CareerError(f"expected local directories for {parent}/{name}")
    return path


def prepare(root: Path, directory: Path) -> tuple[dict, Analysis, dict[str, bytes]]:
    inputs = {
        name: read_input(directory / name) for name in ("posting.txt", "analysis.yaml", "draft.yaml")
    }
    posting = inputs["posting.txt"]
    require_english(posting.decode("utf-8-sig"), "The job posting")
    analysis = Analysis.model_validate(parse_yaml(inputs["analysis.yaml"]))
    draft = Draft.model_validate(parse_yaml(inputs["draft.yaml"]))
    validate_analysis(posting.decode("utf-8"), analysis)
    projection = project(load_knowledge(root), draft)
    return review_input(projection, posting, analysis), analysis, inputs


def preview_packet(directory: Path, packet: dict) -> dict:
    preview = directory / f"preview-{packet['input_sha256'][:16]}"
    if (preview / "validation.json").is_file():
        return {"input_sha256": packet["input_sha256"], "path": str(preview), "reused": True}
    with artifacts.new_directory(preview) as stage:
        report = artifacts.render(stage, packet)
        write_json(stage / "validation.json", report)
    return {"input_sha256": packet["input_sha256"], "path": str(preview), **report}


def run_pipeline(root: Path, directory: Path, version: str | None) -> dict:
    """Run every deterministic step and stop where a person must review."""
    steps = {"validate": {"records": len(load_knowledge(root).records)}}
    for name in ("posting.txt", "analysis.yaml", "draft.yaml"):
        if not (directory / name).is_file():
            return {**steps, "stopped": f"missing {name}",
                    "next": "Run career start, then write analysis.yaml and draft.yaml with tailor-resume."}
    packet, analysis, inputs = prepare(root, directory)
    steps["inspect"] = {"claims": len(packet["claims"]), "input_sha256": packet["input_sha256"]}
    steps["preview"] = preview_packet(directory, packet)
    review_path = directory / "review.yaml"
    if not review_path.is_file():
        return {**steps, "stopped": "awaiting review",
                "next": "Review the preview with review-resume and write review.yaml."}
    review_bytes = read_input(review_path)
    review = Review.model_validate(parse_yaml(review_bytes))
    if review.input_sha256 != packet["input_sha256"]:
        return {**steps, "stopped": "stale review",
                "next": "The draft or sources changed after review. Review the current packet again."}
    if review.disposition != "ready":
        return {**steps, "stopped": "review requested revisions", "next": "Revise the draft and review it again."}
    if not version:
        return {**steps, "stopped": "ready to finish", "next": "Run career run again with --version <version-id>."}
    coverage = check_review(packet, analysis, review)
    inputs["review.yaml"] = review_bytes
    local_directory(root, "resumes", version)
    steps["finish"] = {"saved": str(artifacts.seal(root, version, packet, inputs, coverage))}
    artifacts.load_archive(local_directory(root, "resumes", version))
    steps["verify"] = {"status": "passed", "version": version}
    return {**steps, "stopped": None, "next": f"Record the application with career apply {version} submitted --employer ..."}


def execute(args: argparse.Namespace) -> str:
    root = args.root.resolve()
    command = args.command
    if command == "init":
        return json_text(init(root))
    if command == "applications":
        return json_text(applications.summary(root))
    if command == "apply":
        event = ApplicationEvent(date=(args.date or date.today()).isoformat(), status=args.status, note=args.note)
        saved = applications.record(root, args.version, event, employer=args.employer, role=args.role)
        return json_text(saved.model_dump(mode="json", exclude_none=True))
    if command == "gaps":
        posting = read_input(args.posting).decode("utf-8-sig")
        return json_text(gaps(load_knowledge(root), posting, as_of=args.as_of))
    if command == "setup-renderer":
        return json_text({"assets": str(artifacts.install_assets(args.archive))})
    if command == "schema":
        schema = SCHEMAS[args.contract]
        return json_text(schema.json_schema() if args.contract == "record" else schema.model_json_schema())
    if command == "extract":
        if args.source.suffix.lower() == ".pdf":
            return artifacts.extract_pdf(args.source)[1]
        if args.source.suffix.lower() in {".md", ".markdown", ".txt", ".yaml", ".yml"}:
            return read_input(args.source).decode("utf-8")
        raise CareerError("extract supports PDF, Markdown, UTF-8 text, and YAML")
    if command in {"validate", "index", "retrieve"}:
        knowledge = load_knowledge(root)
        if command == "validate":
            return json_text({"status": "passed", "records": len(knowledge.records)})
        if command == "index":
            index = sync_index(root, knowledge, check=args.check)
            return json_text({"status": "current", "records": len(index["records"])})
        if args.limit < 1:
            raise CareerError("retrieve --limit must be positive")
        return json_text(retrieve(sync_index(root, knowledge), args.terms, args.limit))

    if command in {"verify", "reproduce", "compare"}:
        directory = local_directory(root, "resumes", args.version)
        if command == "verify":
            artifacts.load_archive(directory)
            return json_text({"status": "passed", "version": args.version})
        if command == "compare":
            return artifacts.compare(directory, local_directory(root, "resumes", args.other))
        local_directory(root, "work", "reproduced")
        return json_text(artifacts.reproduce(root, directory, output_id=args.output_id))

    directory = local_directory(root, "work", args.draft)
    if command == "start":
        raw = read_input(args.posting)
        posting = raw.decode("utf-8-sig")
        if not posting.strip():
            raise CareerError("posting is empty")
        require_english(posting, "The job posting")
        with artifacts.new_directory(directory) as stage:
            (stage / "posting.txt").write_bytes(raw)
        return json_text({"posting": str(directory / "posting.txt")})

    if command == "letter":
        letter = Letter.model_validate(parse_yaml(read_input(directory / "letter.yaml")))
        text, evidence = build_letter(load_knowledge(root), letter)
        (directory / "letter.md").write_text(text, encoding="utf-8")
        (directory / "letter-evidence.json").write_text(letter_evidence_text(evidence), encoding="utf-8")
        return json_text({"letter": str(directory / "letter.md"), "claims": len(evidence["claims"])})
    if command == "run":
        return json_text(run_pipeline(root, directory, args.version))

    packet, analysis, inputs = prepare(root, directory)
    if command == "inspect":
        return json_text(packet)
    if command == "preview":
        return json_text(preview_packet(directory, packet))
    review_bytes = read_input(directory / "review.yaml")
    review = Review.model_validate(parse_yaml(review_bytes))
    coverage = check_review(packet, analysis, review)
    inputs["review.yaml"] = review_bytes
    local_directory(root, "resumes", args.version)
    return json_text({"saved": str(artifacts.seal(root, args.version, packet, inputs, coverage))})


def main() -> int:
    try:
        output = execute(arguments())
    except (CareerError, OSError, PyPdfError, ValueError, YAMLError, KeyError, TypeError) as error:
        print(f"career: {error}", file=sys.stderr)
        return 1
    print(output, end="" if output.endswith("\n") or not output else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
