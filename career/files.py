"""Local parsing and content identity utilities."""

import hashlib
import io
import json
import re
import unicodedata
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from pathlib import Path

from ruamel.yaml import YAML


class CareerError(Exception):
    """A failure the CLI can present without a traceback."""


def parse_yaml(raw: bytes):
    yaml = YAML(typ="safe", pure=True)
    return yaml.load(raw.decode("utf-8-sig"))


def dump_yaml(value) -> str:
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    yaml.sort_base_mapping_type_on_output = False
    yaml.allow_unicode = True
    stream = io.StringIO()
    yaml.dump(value, stream)
    return stream.getvalue()


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_json(path: Path, value) -> None:
    path.write_text(json_text(value), encoding="utf-8")


def digest(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def identity(value) -> str:
    return digest(json_text(value))


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(text.split())


def contains(text: str, phrase: str) -> bool:
    phrase = normalized(phrase)
    return bool(phrase and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normalized(text)))


def require_unique(values, context: str) -> None:
    values = list(values)
    if len(set(values)) != len(values):
        raise CareerError(f"{context} contains duplicates")


@contextmanager
def new_directory(destination: Path):
    """Publish a completed directory by rename, serializing writers for the same name."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.with_name(f".{destination.name}.lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise CareerError(f"another operation holds {lock}") from error
    try:
        if destination.exists() or destination.is_symlink():
            raise CareerError(f"{destination} already exists")
        with TemporaryDirectory(prefix=f".{destination.name}.", dir=destination.parent) as stage:
            path = Path(stage)
            yield path
            path.rename(destination)
    finally:
        lock.rmdir()
