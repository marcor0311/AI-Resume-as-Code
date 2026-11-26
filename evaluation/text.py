"""English text and date rules, with a coarse input-language check."""

import re
import unicodedata
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from career.files import CareerError

DASHES = str.maketrans("’‘–—−", "''---")
WORD = re.compile(r"[^\W_]+(?:[+#]+)?", re.UNICODE)
STOP = frozenset("""
a an the and or of on as at if for in into to with by from via using is are be it its our your
their you we they do will has have must needs need able required preferred desirable minimum
qualification qualifications experience experienced responsibility responsibilities knowledge strong excellent familiarity
proficiency proficient demonstrated ability skills including such plus years year least more than
""".split())
MONTHS = {
    term: index for index, names in enumerate((
        "jan january", "feb february", "mar march", "apr april", "may", "jun june",
        "jul july", "aug august", "sep sept september", "oct october", "nov november", "dec december",
    ), 1) for term in names.split()
}
YEAR = r"(?:19|20)\d{2}"
MONTH = "|".join(sorted(MONTHS, key=lambda month: (-len(month), month)))
ISO = rf"{YEAR}[/.\-]\d{{1,2}}(?:[/.\-]\d{{1,2}})?"
US_MONTH = rf"\d{{1,2}}[/.]{YEAR}"
TEXT_MONTH = rf"(?:{MONTH})\.?\s+{YEAR}"
DATE = rf"(?:{ISO}|{US_MONTH}|{TEXT_MONTH}|{YEAR})"
CURRENT = r"present|current|now"
RANGE = re.compile(rf"(?<!\w)(?P<start>{DATE})\s*(?:-|\bto\b|\bthrough\b)\s*(?P<end>{DATE}|{CURRENT})(?!\w)")
DATE_TOKEN = re.compile(rf"(?<!\w){DATE}(?!\w)")
BULLET = re.compile(r"^\s*(?:(?:[-•▪●◦‣]|\*(?!\*))\s*|\d+[.)]\s+)")
YEARS = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)(?:\s*(?:[-–]\s*\d+(?:[.,]\d+)?|\+))?\s*(?:years?)(?!\w)")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.translate(DASHES).casefold())
    return " ".join("".join(char for char in text if not unicodedata.combining(char)).split())



ENGLISH_SIGNALS = set("and the with for from our you your work skills experience required preferred responsibilities years education summary projects".split())
OTHER_LANGUAGE_SIGNALS = (
    set("los las una para del con por somos buscamos requisitos responsabilidades habilidades experiencia anos formacion deseable requieren profesional conocimientos funciones".split()),
    set("une les des pour avec vous votre nous poste requise competences annees professionnels formation missions".split()),
    set("uma com dos das que vaga requisitos experiencia anos conhecimentos formacao obrigatorio qualificacoes responsabilidades".split()),
    set("und mit eine einen fur der die das von berufserfahrung kenntnisse voraussetzungen jahre aufgaben team".split()),
)


def require_english(text: str, subject: str) -> None:
    """Reject strongly identifiable other-language prose while allowing terse technical input."""
    words = set(WORD.findall(fold(text)))
    signals = len(words & ENGLISH_SIGNALS)
    foreign = max(len(words & markers) for markers in OTHER_LANGUAGE_SIGNALS)
    letters = [char for char in text if char.isalpha()]
    non_latin = sum("LATIN" not in unicodedata.name(char, "") for char in letters)
    if (foreign >= 4 and foreign >= signals + 3) or (
        len(letters) >= 30 and non_latin * 2 > len(letters) and signals < 3
    ):
        raise CareerError(f"{subject} must be supplied in English. Translate it before evaluation.")


@lru_cache(maxsize=1024)
def term_pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<![\w+#])" + re.escape(fold(term)) + r"(?![\w+#])")


def matches(text: str, term: str) -> bool:
    return bool(term_pattern(term).search(fold(text)))


def hits(text: str, terms: list[str] | tuple[str, ...]) -> bool:
    normalized = fold(text)
    return any(term_pattern(term).search(normalized) for term in terms)


def tokens(text: str) -> set[str]:
    return {word for word in WORD.findall(fold(text)) if len(word) > 1 and word not in STOP and not word.isdigit()}


def body(line: str) -> str:
    return BULLET.sub("", line.strip()).strip()


@dataclass(frozen=True)
class Stamp:
    earliest: date
    latest: date
    style: str


def stamp(value: str) -> Stamp | None:
    try:
        if value.isdigit():
            year = int(value)
            return Stamp(date(year, 1, 1), date(year, 12, 31), "year")
        parts = re.split(r"[-/.\s]+", value)
        if parts[0] in MONTHS:
            style = "named month"
            year, month, day = int(parts[1]), MONTHS[parts[0]], None
        elif len(parts[0]) == 4:
            style = "year first"
            year, month = map(int, parts[:2])
            day = int(parts[2]) if len(parts) > 2 else None
        else:
            style = "month first"
            year, month, day = int(parts[1]), int(parts[0]), None
        if day is not None:
            precise = date(year, month, day)
            return Stamp(precise, precise, style)
        return Stamp(date(year, month, 1), date(year, month, monthrange(year, month)[1]), style)
    except (IndexError, ValueError):
        return None


@dataclass(frozen=True)
class DateRange:
    start: Stamp | None
    end: Stamp | None
    open_end: bool

    @property
    def valid(self) -> bool:
        return self.start is not None and (
            self.open_end or (self.end is not None and self.start.earliest <= self.end.latest)
        )

    def bounds(self, as_of: date | None) -> tuple[date, date] | None:
        if not self.valid:
            return None
        end = as_of if self.open_end else self.end.earliest
        # Lower-bound experience using the latest possible start and earliest end.
        if end is None or end <= self.start.latest:
            return None
        return self.start.latest, end


def ranges(text: str) -> list[DateRange]:
    result = []
    for match in RANGE.finditer(fold(text)):
        end = match["end"]
        ongoing = bool(re.fullmatch(CURRENT, end))
        result.append(DateRange(stamp(match["start"]), None if ongoing else stamp(end), ongoing))
    return result


def experience_days(intervals: list[tuple[date, date]]) -> int:
    if not intervals:
        return 0
    start, end = sorted(intervals)[0]
    total = 0
    for next_start, next_end in sorted(intervals)[1:]:
        if next_start > end:
            total += (end - start).days
            start, end = next_start, next_end
        else:
            end = max(end, next_end)
    return total + (end - start).days
