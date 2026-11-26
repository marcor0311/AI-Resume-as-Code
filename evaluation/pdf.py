"""Extract bounded PDF text and layout indicators without consulting resume source files."""

import io
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .config import Rubric
from .text import BULLET, DATE_TOKEN, fold, hits, ranges, stamp, tokens

EMAIL = re.compile(r"[\w.!#$%&'*+/=?^_`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<!\w)\+?\d(?:[\d(). \-]{5,}\d)(?!\w)")
WEB = re.compile(r"(?:https?://|www\.)\S+|\b(?:[\w-]+\.)+(?:com|org|net|dev|io|me|co|cr)\b", re.I)
DANGER = {chr(0xfffd), chr(0x25a1), chr(0xfffe), chr(0xffff)}


@dataclass(frozen=True)
class Line:
    page: int
    number: int
    section: str
    text: str

    def evidence(self, basis: str) -> dict:
        return {"page": self.page, "line": self.number, "section": self.section, "quote": self.text, "basis": basis}


@dataclass
class Document:
    pages: int = 0
    extracted_characters: int = 0
    lines: list[Line] = field(default_factory=list)
    sections: dict[str, list[Line]] = field(default_factory=lambda: defaultdict(list))
    headings: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)
    hidden_pages: list[int] = field(default_factory=list)
    column_pages: list[int] = field(default_factory=list)
    graphical_pages: list[int] = field(default_factory=list)
    corrupt_characters: int = 0
    unreadable: bool = False

    def issue(self, code: str, detail: str, recommendation: str, *, severity: str = "warning", pages=()) -> None:
        self.issues.append({
            "code": code, "severity": severity, "detail": detail,
            "pages": list(pages), "recommendation": recommendation,
        })


def section_marker(text: str, aliases: dict[str, str]) -> tuple[str | None, str]:
    clean = text.strip().strip("#").strip()
    heading, separator, suffix = clean.partition(":")
    return aliases.get(fold(heading.rstrip(":"))), suffix.strip() if separator else ""


def contact_types(lines: list[Line]) -> list[str]:
    text = " ".join(line.text for line in lines)
    result = []
    if EMAIL.search(text):
        result.append("email")
    # Keep dates and ZIP codes out of the contact signal.
    for phone in PHONE.finditer(text):
        value = phone.group().strip()
        digits = re.sub(r"\D", "", value)
        is_date = DATE_TOKEN.fullmatch(value) or re.fullmatch(r"\d{1,2}[-.]\d{1,2}[-.]\d{4}|[12]\d{3}[ -]+[12]\d{3}", value)
        if 7 <= len(digits) <= 15 and not is_date:
            result.append("phone")
            break
    if WEB.search(EMAIL.sub("", text)):
        result.append("website")
    return result


def _has_graphics(page) -> bool:
    resources = page.get("/Resources")
    resources = resources.get_object() if resources else {}
    xobjects = resources.get("/XObject", {})
    xobjects = xobjects.get_object() if xobjects else {}
    return any(item.get_object().get("/Subtype") == "/Image" for item in xobjects.values())


def _columns(blocks: list[tuple[float, float, str]], left_edge: float, width: float, rubric: Rubric) -> bool:
    limits = rubric.thresholds
    cut = left_edge + width * limits.column_split_fraction
    left, right = set(), set()
    for x, y, text in blocks:
        # Short right-aligned dates are common in a clean one-column resume.
        if len(tokens(text)) < 2 or DATE_TOKEN.fullmatch(fold(text)):
            continue
        side = right if x >= cut else left
        side.add(round(y / limits.row_tolerance_points))
    overlap = left & right
    # Typst and PDF generators can stagger neighboring columns by part of a line.
    staggered = left & {row + offset for row in right for offset in (-1, 1)}
    return min(len(left), len(right), len(overlap | staggered)) >= limits.min_column_lines


def _page_text(page, rubric: Rubric) -> tuple[str, bool, bool]:
    blocks = []
    hidden = False
    render_mode = 0
    render_stack = []

    def operator(name, operands, cm, tm):
        nonlocal render_mode, hidden
        if name == b"q":
            render_stack.append(render_mode)
        elif name == b"Q" and render_stack:
            render_mode = render_stack.pop()
        elif name == b"Tr" and operands:
            render_mode = int(operands[0])
        elif name in {b"Tj", b"TJ", b"'", b'"'} and render_mode in {3, 7}:
            hidden = True

    def visit(text, cm, tm, font, font_size):
        nonlocal hidden
        clean = text.strip()
        if not clean:
            return
        if 0 < font_size < rubric.thresholds.min_readable_font_points:
            hidden = True
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        blocks.append((x, y, clean))

    text = page.extract_text(visitor_text=visit, visitor_operand_before=operator) or ""
    return text, hidden, _columns(blocks, float(page.cropbox.left), float(page.cropbox.width), rubric)


def extract(raw: bytes, rubric: Rubric) -> Document:
    doc = Document()
    aliases = {fold(alias): section for section, options in rubric.sections.items() for alias in options}
    if len(raw) > rubric.thresholds.max_pdf_bytes:
        doc.unreadable = True
        doc.issue("pdf_too_large", "The PDF exceeds the configured size limit.", "Export a smaller, text-based PDF.", severity="error")
        return doc
    if b"%PDF-" not in raw[:1024]:
        doc.unreadable = True
        doc.issue("unreadable_pdf", "The file does not have a readable PDF header.", "Export and check a new PDF.", severity="error")
        return doc
    try:
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise ValueError("encrypted PDF")
        doc.pages = len(reader.pages)
        if doc.pages > rubric.thresholds.max_pdf_pages:
            doc.unreadable = True
            doc.issue("page_limit", "The PDF exceeds the configured page limit.", "Evaluate a complete resume within the page limit.", severity="error")
            return doc
        active = "header"
        for page_number, page in enumerate(reader.pages, 1):
            text, hidden, columns = _page_text(page, rubric)
            if _has_graphics(page):
                doc.graphical_pages.append(page_number)
            if columns:
                doc.column_pages.append(page_number)
            if hidden:
                doc.hidden_pages.append(page_number)
            if not text.strip():
                doc.empty_pages.append(page_number)
            doc.extracted_characters += sum(not char.isspace() for char in text)
            doc.corrupt_characters += sum(
                char in DANGER or unicodedata.category(char) in {"Co", "Cs", "Cn"}
                for char in text
            ) + len(re.findall(r"\(cid:\d+\)", text))
            if hidden:
                continue
            for number, raw_line in enumerate(text.splitlines(), 1):
                clean = raw_line.strip()
                if not clean:
                    continue
                heading, suffix = section_marker(clean, aliases)
                if heading:
                    active = heading
                    doc.headings.append({"page": page_number, "line": number, "section": active})
                    clean = suffix
                if clean:
                    # A wrapped continuation can belong to the same bullet even on a narrow page.
                    row = Line(page_number, number, active, clean)
                    doc.lines.append(row)
                    doc.sections[active].append(row)
    except (PyPdfError, KeyError, TypeError, ValueError, IndexError, RecursionError, OSError, OverflowError) as error:
        failed = Document(pages=doc.pages, unreadable=True)
        failed.issue("unreadable_pdf", f"PDF extraction failed ({type(error).__name__}).", "Export and check a new text-based PDF.", severity="error")
        return failed
    if doc.hidden_pages:
        doc.issue("hidden_or_tiny_text", "Reading found hidden text or sub-readable type. These pages were excluded from job evidence.",
                  "Remove the hidden text and use readable type before re-exporting.", pages=doc.hidden_pages, severity="error")
    if doc.column_pages:
        doc.issue("column_reading_order", "Parallel text regions may be read in the wrong order.",
                  "Use a single reading column or check that extracted sections and bullets remain together.", pages=doc.column_pages)
    if doc.empty_pages:
        doc.issue("empty_text_pages", "These pages have no extractable text.",
                  "Remove blank pages or re-export scanned pages as selectable text.", pages=doc.empty_pages, severity="error")
    if doc.graphical_pages:
        doc.issue("image_elements", "Image elements are present. Content inside images is invisible to text extraction.",
                  "Place any qualifications shown in images in ordinary searchable text.", pages=doc.graphical_pages, severity="info")
    return doc


def date_quality(doc: Document, rubric: Rubric) -> float | None:
    date_sections = {"experience", "education", "projects", "credentials"}
    rows = [line for line in doc.lines if line.section in date_sections and not hits(line.text, rubric.category_cues["excluded"])]
    spans = [span for line in rows for span in ranges(line.text)]
    if any(not span.valid for span in spans):
        pages = sorted({line.page for line in rows if any(not span.valid for span in ranges(line.text))})
        doc.issue("invalid_date_range", "A range contains an invalid date or ends before it begins.",
                  "Check the dates against the original record and correct the date range.", pages=pages, severity="error")
        return 0
    values = [stamp(match.group()) for line in rows if not BULLET.match(line.text) for match in DATE_TOKEN.finditer(fold(line.text))]
    if any(value is None for value in values):
        doc.issue("invalid_date", "A date could not be interpreted as a calendar date.", "Check the date against the original record.", severity="error")
        return 0
    if len(values) < 2:
        return None
    styles = Counter(value.style for value in values if value.style != "year")
    if len(styles) < 2:
        return 100
    doc.issue("mixed_date_styles", "The resume uses multiple month or date formats.",
              "Use one format while keeping each date's verified precision.")
    return 100 * max(styles.values()) / sum(styles.values())
