"""Compare pypdf text with independent extractors. Diagnostic only: it never changes a score."""

import shutil
import subprocess
import tempfile
from pathlib import Path

from .text import tokens

MIN_AGREEMENT = 0.9


def pdftotext(raw: bytes) -> str | None:
    """Poppler's reader, when installed, approximates a second ATS parser."""
    binary = shutil.which("pdftotext")
    if not binary:
        return None
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "resume.pdf"
        source.write_bytes(raw)
        result = subprocess.run([binary, "-layout", "-enc", "UTF-8", str(source), "-"],
                                capture_output=True, timeout=60, check=False)
    return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else None


def plain_reading(raw: bytes) -> str | None:
    """pypdf without layout heuristics: the most literal content-stream order."""
    import io

    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(raw), strict=False)
        return "\n".join(page.extract_text(extraction_mode="plain") or "" for page in reader.pages)
    except (PyPdfError, ValueError, KeyError, TypeError, OSError):
        return None


def agreement(reference: set[str], other: set[str]) -> float:
    if not reference and not other:
        return 1.0
    return len(reference & other) / len(reference | other)


def order_agreement(first: list[str], second: list[str]) -> float:
    """Share of first-occurrence word pairs that both readings place in the same order."""
    def positions(words):
        seen = {}
        for index, word in enumerate(words):
            seen.setdefault(word, index)
        return seen

    a, b = positions(first), positions(second)
    shared = sorted(set(a) & set(b), key=a.get)
    if len(shared) < 2:
        return 1.0
    agree = sum(b[x] < b[y] for x, y in zip(shared, shared[1:]))
    return agree / (len(shared) - 1)


def cross_check(raw: bytes, reference_text: str) -> dict:
    reference = tokens(reference_text)
    reference_order = reference_text.split()
    readers = {"pypdf-plain": plain_reading(raw), "pdftotext": pdftotext(raw)}
    results = {}
    for name, text in readers.items():
        if text is None:
            results[name] = {"available": False}
            continue
        results[name] = {
            "available": True,
            "token_agreement": round(agreement(reference, tokens(text)), 3),
            "order_agreement": round(order_agreement(reference_order, text.split()), 3),
        }
    measured = [row for row in results.values() if row["available"]]
    warning = any(min(row["token_agreement"], row["order_agreement"]) < MIN_AGREEMENT for row in measured)
    return {
        "readers": results,
        "warning": warning,
        "note": "Different parsers read this PDF differently. Check reading order and columns." if warning else None,
    }
