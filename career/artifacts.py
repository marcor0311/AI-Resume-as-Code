"""Render, verify, and publish local resume versions."""

import difflib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tomllib
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from urllib.request import urlopen

import rendercv_fonts
import typst
from pypdf import PdfReader
from rendercv.exception import RenderCVInternalError, RenderCVUserError, RenderCVUserValidationError
from rendercv.renderer.pdf_png import get_package_path
from rendercv.renderer.typst import generate_typst
from rendercv.schema.rendercv_model_builder import build_rendercv_dictionary_and_model
from typst import TypstError

from evaluation.engine import evaluate
from evaluation.reporting import JSON_REPORT, MARKDOWN_REPORT, read_report, write_evaluation

from .files import CareerError, contains, digest, dump_yaml, identity, new_directory, normalized, parse_yaml, write_json
from .models import Analysis, Review
from .tailoring import check_review, validate_analysis

LEGACY_ARTIFACTS = frozenset({
    "posting.txt", "analysis.yaml", "draft.yaml", "review.yaml", "evidence.json",
    "validation.json", "resume.yaml", "resume.pdf", "resume.txt",
})
ARTIFACTS = LEGACY_ARTIFACTS | {JSON_REPORT, MARKDOWN_REPORT}
FONT_AWESOME = "fontawesome-0.6.0.tar.gz"
ASSET_SHA256 = "31374c788d6850c7fd3da742a67e8a753e5644fa0c677b845f75be8aa488380c"
PROJECT_DIR = Path(__file__).resolve().parents[1]
ASSET_DIR = PROJECT_DIR / ".render-assets"
LOCKFILE = PROJECT_DIR / "uv.lock"
TYPOGRAPHY = str.maketrans("‘’“”–—−", "''\"\"---")


def check_assets(raw: bytes) -> bytes:
    if digest(raw) != ASSET_SHA256:
        raise CareerError(f"checksum mismatch for {FONT_AWESOME}")
    return raw


def install_assets(archive: Path | None) -> Path:
    destination = ASSET_DIR / FONT_AWESOME
    if archive is None and destination.is_file():
        check_assets(destination.read_bytes())
        return destination
    if archive is None:
        with urlopen(f"https://packages.typst.org/preview/{FONT_AWESOME}", timeout=30) as response:
            raw = response.read(1_000_000)
    else:
        raw = archive.read_bytes()
    check_assets(raw)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
        path = Path(temporary.name)
        try:
            temporary.write(raw)
            temporary.flush()
            os.replace(path, destination)
        finally:
            path.unlink(missing_ok=True)
    return destination


def compile_typst(typst_path: Path, output: Path, *, format: str = "pdf") -> None:
    archive = ASSET_DIR / FONT_AWESOME
    if not archive.is_file():
        raise CareerError("rendering assets are missing. Run career setup-renderer once.")
    raw = check_assets(archive.read_bytes())
    with TemporaryDirectory(prefix="career-typst-") as directory:
        cache = Path(directory)
        package = cache / "preview" / "fontawesome" / "0.6.0"
        package.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as bundle:
            bundle.extractall(package, filter="data")
        typst.compile(
            input=typst_path, output=output, root=typst_path.parent, format=format,
            font_paths=rendercv_fonts.paths_to_font_folders, ignore_system_fonts=True,
            package_path=get_package_path(), package_cache_path=cache,
        )


def extract_pdf(path: Path) -> tuple[list[str], str]:
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    if not pages or any(not text.strip() for text in pages):
        raise CareerError(f"{path.name} has a blank or non-extractable PDF page")
    return pages, "\n\n".join(text.rstrip() for text in pages) + "\n"


def text_layer(text: str, *, keep_line_hyphens: bool = False) -> str:
    # Compare both spellings of a word that a line break split at a hyphen.
    replacement = "-" if keep_line_hyphens else ""
    text = re.sub(r"(?<=\w)-[ \t]*\r?\n[ \t]*(?=\w)", replacement, text)
    text = re.sub(r"\u00ad[ \t]*\r?\n[ \t]*", "", text)
    return normalized(text.translate(TYPOGRAPHY).replace("\u00ad", ""))


def verify_pdf(path: Path, packet: dict) -> tuple[str, dict]:
    pages, raw_text = extract_pdf(path)
    text = text_layer(raw_text)
    literal_hyphens = text_layer(raw_text, keep_line_hyphens=True)
    headings = packet["section_order"]
    lines = iter(text_layer(line) for line in raw_text.splitlines())
    for heading in headings:
        if not any(line == text_layer(heading) for line in lines):
            raise CareerError(f"PDF section missing or out of order: {heading!r}")
    for claim_path, claim in packet["claims"].items():
        expected = claim["expected_pdf_text"]
        if claim_path == "/cv/phone":
            # Contact items are separated by pipes in the pinned design.
            header = raw_text.split(f"\n{headings[0]}\n", 1)[0]
            digits = re.sub(r"\D", "", expected)
            found = any(re.sub(r"\D", "", item) == digits for item in header.split("|"))
        else:
            phrase = text_layer(expected)
            found = contains(text, phrase) or contains(literal_hyphens, phrase)
        if not found:
            raise CareerError(f"PDF text omitted or changed {claim_path} ({expected!r})")
    for reference in packet["evidence"]:
        if "#" in reference and contains(text, reference):
            raise CareerError(f"internal evidence reference appeared in PDF text: {reference}")
    keywords = packet["analysis"]["keywords"]
    present = [
        term for term in keywords if contains(text, text_layer(term)) or contains(literal_hyphens, text_layer(term))
    ]
    long_claims = [
        path for path, claim in packet["claims"].items()
        if ("/highlights/" in path or any("#" in ref for ref in claim["evidence"]))
        and len(claim["text"].split()) > 30
    ]
    return raw_text, {
        "pages": len(pages), "text_chars": len(text), "verified_text_items": len(headings) + len(packet["claims"]),
        "keywords_present": present, "keywords_missing": [term for term in keywords if term not in present],
        "long_claims": long_claims,
    }


def render(directory: Path, packet: dict, *, input_yaml: bytes | None = None) -> dict:
    yaml_path = directory / "resume.yaml"
    data = input_yaml if input_yaml is not None else dump_yaml(packet["resume"]).encode("utf-8")
    yaml_path.write_bytes(data)
    # The programmatic APIs avoid the CLI's background update request.
    try:
        _, model = build_rendercv_dictionary_and_model(
            data.decode("utf-8"), input_file_path=yaml_path,
            output_folder=directory, typst_path=directory / ".resume.typ",
            pdf_path=directory / "resume.pdf",
        )
        typst_path = generate_typst(model)
        if typst_path is None:
            raise CareerError("RenderCV did not create Typst source")
        pdf = directory / "resume.pdf"
        compile_typst(typst_path, pdf)
    except RenderCVUserValidationError as error:
        errors = "; ".join(f"{item.schema_location}: {item.message}" for item in error.validation_errors)
        raise CareerError(f"RenderCV validation failed: {errors}") from error
    except (RenderCVInternalError, RenderCVUserError, TypstError) as error:
        raise CareerError(f"RenderCV rendering failed: {error}") from error
    if not pdf.is_file():
        raise CareerError("RenderCV did not create a PDF")
    raw_text, report = verify_pdf(pdf, packet)
    (directory / "resume.txt").write_text(raw_text, encoding="utf-8")
    (directory / ".resume.typ").unlink(missing_ok=True)
    return report


def tool_versions() -> dict:
    lock = tomllib.loads(LOCKFILE.read_text(encoding="utf-8"))
    toolchain = {FONT_AWESOME: ASSET_SHA256}
    for item in lock["package"]:
        if "registry" in item["source"]:
            name = item["name"]
            try:
                toolchain[name] = version(name)
            except PackageNotFoundError:
                # Some locked packages are selected only on other platforms.
                continue
    return toolchain


def git_revision(root: Path) -> str | None:
    if not (root / ".git").exists() or not shutil.which("git"):
        return None
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def seal(
    root: Path, version_id: str, packet: dict, inputs: dict[str, bytes], coverage: dict,
) -> Path:
    destination = root / "resumes" / version_id
    with new_directory(destination) as directory:
        pdf_checks = render(directory, packet)
        expected = tuple(
            claim["expected_pdf_text"] for path, claim in packet["claims"].items()
            if path != "/cv/phone"
        )
        report = evaluate((directory / "resume.pdf").read_bytes(), inputs["posting.txt"], expected=expected)
        write_evaluation(directory, report)
        for filename, raw in inputs.items():
            (directory / filename).write_bytes(raw)
        write_json(directory / "evidence.json", packet)
        write_json(directory / "validation.json", {
            "deterministic": {"status": "passed", **pdf_checks},
            "semantic": {"status": "reviewed", "requirement_coverage": coverage},
        })
        write_json(directory / "manifest.json", {
            "schema_version": 2, "version_id": version_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_git_revision": git_revision(root),
            "input_sha256": packet["input_sha256"],
            "lock_sha256": digest(LOCKFILE.read_bytes()),
            "python": platform.python_version(), "platform": platform.system(),
            "toolchain": tool_versions(),
            "sha256": {name: digest((directory / name).read_bytes()) for name in ARTIFACTS},
        })
    return destination


def load_archive(directory: Path) -> tuple[dict, dict, bytes]:
    manifest_path = directory / "manifest.json"
    stored_names = {path.name for path in directory.iterdir()}
    for name in stored_names:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise CareerError(f"{directory.name}: expected a regular local file at {name}")
    manifest = json.loads(manifest_path.read_bytes())
    archive_version = manifest["schema_version"]
    if archive_version not in {1, 2} or manifest["version_id"] != directory.name:
        raise CareerError(f"{directory.name}: invalid archive manifest")
    artifacts = ARTIFACTS if archive_version == 2 else LEGACY_ARTIFACTS
    if stored_names != artifacts | {"manifest.json"}:
        raise CareerError(f"{directory.name}: unexpected or missing archive files")
    if manifest["sha256"].keys() != artifacts:
        raise CareerError(f"{directory.name}: manifest does not cover all artifacts")
    for name, expected in manifest["sha256"].items():
        if digest((directory / name).read_bytes()) != expected:
            raise CareerError(f"{directory.name}: checksum mismatch in {name}")
    packet = json.loads((directory / "evidence.json").read_bytes())
    input_yaml = (directory / "resume.yaml").read_bytes()
    parsed_yaml = parse_yaml(input_yaml)
    analysis = Analysis.model_validate(parse_yaml((directory / "analysis.yaml").read_bytes()))
    packet_contents = {key: value for key, value in packet.items() if key != "input_sha256"}
    if not (
        manifest["input_sha256"] == packet["input_sha256"] == identity(packet_contents)
        and packet["posting_sha256"] == manifest["sha256"]["posting.txt"]
        and analysis.model_dump(mode="json") == packet["analysis"]
        and parsed_yaml == packet["resume"]
        and list(parsed_yaml["cv"]["sections"]) == packet["section_order"]
    ):
        raise CareerError(f"{directory.name}: inconsistent recorded inputs")
    validate_analysis((directory / "posting.txt").read_text(encoding="utf-8"), analysis)
    review = Review.model_validate(parse_yaml((directory / "review.yaml").read_bytes()))
    coverage = check_review(packet, analysis, review)
    text, report = verify_pdf(directory / "resume.pdf", packet)
    validation = json.loads((directory / "validation.json").read_bytes())
    expected_validation = {
        "deterministic": {"status": "passed", **report},
        "semantic": {"status": "reviewed", "requirement_coverage": coverage},
    }
    if text != (directory / "resume.txt").read_bytes().decode("utf-8") or validation != expected_validation:
        raise CareerError(f"{directory.name}: stored PDF extraction or validation differs")
    if archive_version == 2:
        evaluation_inputs = read_report(directory / JSON_REPORT)["inputs"]
        expected_inputs = {"pdf_sha256": manifest["sha256"]["resume.pdf"],
                           "posting_sha256": manifest["sha256"]["posting.txt"]}
        if evaluation_inputs != expected_inputs:
            raise CareerError(f"{directory.name}: evaluation does not identify the archived PDF and posting")
    return manifest, packet, input_yaml


def reproduce(root: Path, directory: Path, *, output_id: str | None = None) -> dict:
    manifest, packet, input_yaml = load_archive(directory)
    runtime_tools = tool_versions()
    shared = manifest["toolchain"].keys() & runtime_tools.keys()
    required = {FONT_AWESOME, "rendercv", "rendercv-fonts", "typst", "pypdf"}
    if not required <= shared or any(manifest["toolchain"][name] != runtime_tools[name] for name in shared):
        raise CareerError("install the archive's rendering and extraction versions before reproducing")
    destination = root / "work" / "reproduced" / (output_id or directory.name)
    with new_directory(destination) as staged:
        report = render(staged, packet, input_yaml=input_yaml)
        original_pages, original = extract_pdf(directory / "resume.pdf")
        current_pages, current = extract_pdf(staged / "resume.pdf")
        if (len(original_pages) != len(current_pages) or text_layer(original) != text_layer(current)):
            raise CareerError("reproduced PDF differs in page count or normalized extracted text")
        byte_identical = digest((staged / "resume.pdf").read_bytes()) == manifest["sha256"]["resume.pdf"]
        result = {
            "path": str(destination), "version_id": directory.name,
            "pages": report["pages"], "normalized_text_matches": True,
            "pdf_bytes_match": byte_identical,
        }
        write_json(staged / "reproduction.json", result)
    return result


def compare(first: Path, second: Path) -> str:
    load_archive(first)
    load_archive(second)
    return "".join(difflib.unified_diff(
        (first / "resume.txt").read_text(encoding="utf-8").splitlines(keepends=True),
        (second / "resume.txt").read_text(encoding="utf-8").splitlines(keepends=True),
        fromfile=first.name, tofile=second.name,
    ))
