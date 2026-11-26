"""Validate the canonical graph and build a small, derived discovery index."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import TypeAdapter

from .files import CareerError, contains, digest, json_text, normalized, parse_yaml, require_unique
from .models import Credential, DatedRecord, Evidence, Fact, Profile, Record

RECORD = TypeAdapter(Record)


@dataclass
class Knowledge:
    records: dict[str, Record]
    sources: dict[str, dict[str, str]]

    def verified(self, record_id: str) -> Record:
        record = self.records.get(record_id)
        if record is None or record.status != "verified":
            raise CareerError(f"record {record_id!r} is missing or needs confirmation")
        return record

    def fact(self, reference: str) -> Fact:
        record_id, _, fact_id = reference.partition("#")
        record = self.verified(record_id)
        fact = next((item for item in record.facts if item.id == fact_id), None)
        if fact is None or fact.status != "verified":
            raise CareerError(f"fact {reference!r} is missing or needs confirmation")
        for linked in [*fact.sources, *fact.mentions]:
            self.verified(linked)
        return fact


def load_knowledge(root: Path) -> Knowledge:
    records = {}
    sources = {}
    knowledge_dir = root / "knowledge"
    if knowledge_dir.is_symlink() or (knowledge_dir.exists() and not knowledge_dir.is_dir()):
        raise CareerError("knowledge must be a local directory")
    # Attachments are local source documents and may themselves be YAML input.
    paths = [*knowledge_dir.glob("*.yaml"), *knowledge_dir.glob("*.yml")]
    for directory in sorted(knowledge_dir.iterdir()) if knowledge_dir.exists() else []:
        if directory.is_symlink():
            raise CareerError(f"knowledge/{directory.name} must be local")
        if directory.is_dir() and directory.name != "attachments":
            paths.extend(directory.rglob("*.yaml"))
            paths.extend(directory.rglob("*.yml"))
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.resolve().is_relative_to(knowledge_dir.resolve()):
            raise CareerError(f"{relative}: expected a local record file")
        raw = path.read_bytes()
        try:
            record = RECORD.validate_python(parse_yaml(raw))
        except ValueError as error:
            raise CareerError(f"{relative}: {error}") from error
        if path.parent != knowledge_dir / record.kind or path.stem != record.id:
            raise CareerError(f"{relative}: expected knowledge/{record.kind}/{record.id}.yaml")
        if record.id in records:
            raise CareerError(f"duplicate record ID {record.id}")
        records[record.id] = record
        sources[record.id] = {"path": relative, "sha256": digest(raw)}
    for record in records.values():
        validate_record(root, records, record)
        if isinstance(record, Evidence) and record.attachment:
            attachment = knowledge_dir / "attachments" / record.attachment
            with attachment.open("rb") as document:
                sources[record.id]["attachment_sha256"] = hashlib.file_digest(document, "sha256").hexdigest()
    return Knowledge(records, sources)


def validate_record(root: Path, records: dict[str, Record], record: Record) -> None:
    require_unique(record.related, f"{record.id}.related")
    require_unique((fact.id for fact in record.facts), f"{record.id}.facts")
    for related in record.related:
        if related == record.id or related not in records:
            raise CareerError(f"{record.id}: invalid relationship {related!r}")
    if isinstance(record, DatedRecord) and record.start_date and record.end_date not in (None, "present"):
        # Compare at the common precision so an end year may include a known start month.
        precision = min(len(record.start_date), len(record.end_date))
        if record.start_date[:precision] > record.end_date[:precision]:
            raise CareerError(f"{record.id}: end_date precedes start_date")
    if isinstance(record, DatedRecord) and record.end_date == "present" and not record.start_date:
        raise CareerError(f"{record.id}: present requires a start_date")
    if isinstance(record, Credential) and record.expires:
        precision = min(len(record.date), len(record.expires))
        if record.expires[:precision] < record.date[:precision]:
            raise CareerError(f"{record.id}: expiry precedes issue date")
    if isinstance(record, Profile) and record.status == "verified" and not (record.email or record.phone or record.website):
        raise CareerError(f"{record.id}: a verified profile needs an email, phone, or website")
    if isinstance(record, Evidence):
        if not (record.excerpt or record.attachment):
            raise CareerError(f"{record.id}: evidence requires an excerpt or an attachment")
        if record.attachment:
            attachment = Path(record.attachment)
            base = (root / "knowledge" / "attachments").resolve()
            target = root / "knowledge" / "attachments" / attachment
            if attachment.is_absolute() or ".." in attachment.parts or not target.resolve().is_relative_to(base) or not target.is_file():
                raise CareerError(f"{record.id}: invalid or missing local attachment {record.attachment!r}")
    for fact in record.facts:
        label = f"{record.id}#{fact.id}"
        for field, allowed in (
            ("sources", {"evidence"}), ("mentions", {"skill", "certification", "training"}),
        ):
            values = getattr(fact, field)
            require_unique(values, f"{label}.{field}")
            for linked in values:
                if linked == record.id or linked not in records or records[linked].kind not in allowed:
                    raise CareerError(f"{label}: invalid {field} reference {linked!r}")
                if record.status == fact.status == "verified" and records[linked].status != "verified":
                    raise CareerError(f"{label}: verified facts require verified references ({linked!r})")


def build_index(knowledge: Knowledge) -> dict:
    entries = []
    for record_id, record in sorted(knowledge.records.items()):
        facts = [fact for fact in record.facts if record.status == fact.status == "verified"]
        tags = set(record.tags + getattr(record, "aliases", []))
        tags.update(knowledge.records[mention].title for fact in facts for mention in fact.mentions)
        row = {
            "id": record_id, "kind": record.kind, "title": record.title, "status": record.status,
            **knowledge.sources[record_id],
            "tags": sorted(tags, key=lambda tag: (normalized(tag), tag)),
            "related": sorted(record.related),
            "facts": [f"{record_id}#{fact.id}" for fact in sorted(facts, key=lambda item: item.id)],
        }
        for field in ("organization", "start_date", "end_date", "date"):
            if value := getattr(record, field, None):
                row[field] = value
        entries.append(row)
    return {"schema_version": 1, "records": entries}


def sync_index(root: Path, knowledge: Knowledge, check: bool = False) -> dict:
    index = build_index(knowledge)
    path = root / "knowledge" / "index.json"
    expected = json_text(index)
    if check:
        if not path.is_file() or path.read_bytes() != expected.encode("utf-8"):
            raise CareerError("knowledge index is missing or stale. Run career index.")
        return index
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            output.write(expected.encode("utf-8"))
            output.flush()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    return index


def retrieve(index: dict, terms: list[str], limit: int) -> list[dict]:
    """Rank title, tags, and organization matches. The agent reads only selected sources."""
    unique_terms = sorted({normalized(term) for term in terms if normalized(term)})
    ranked = []
    for record in index["records"]:
        if record["status"] != "verified" or record["kind"] in {"profile", "evidence"}:
            continue
        fields = [(record["title"], 3), (record.get("organization", ""), 1),
                  *((tag, 2) for tag in record["tags"])]
        matches = {
            term: max((weight for value, weight in fields if contains(value, term)), default=0)
            for term in unique_terms
        }
        score = sum(matches.values())
        if score or not unique_terms:
            ranked.append({**record, "score": score, "matched": [term for term, weight in matches.items() if weight]})
    return sorted(ranked, key=lambda row: (-row["score"], row["id"]))[:limit]
