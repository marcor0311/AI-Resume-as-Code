"""Create the layout of a private career data repository."""

from pathlib import Path

from .models import Kind
from typing import get_args

GITIGNORE = """# Derived or in-progress files
/work/
/knowledge/index.json
.DS_Store
"""

README = """# Private career data

Owner-confirmed career records for Career as Code. Run the engine with
`CAREER_DATA_ROOT` pointing here, or with `--root`.

| Path | Purpose |
| --- | --- |
| `knowledge/<kind>/` | One YAML record per entity |
| `knowledge/attachments/` | Supporting documents |
| `resumes/<version>/` | Sealed resume versions |
| `applications/` | What happened after each version was sent |
| `evaluations/` | Standalone evaluator reports |
"""

WORKFLOW = """name: career-data
on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          path: data
      - uses: actions/checkout@v4
        with:
          # Set the CAREER_ENGINE_REPOSITORY variable to owner/name of the engine repository.
          repository: ${{ vars.CAREER_ENGINE_REPOSITORY }}
          path: engine
      - uses: astral-sh/setup-uv@v6
      - name: Validate records and sealed versions
        working-directory: engine
        env:
          CAREER_DATA_ROOT: ${{ github.workspace }}/data
        run: |
          uv sync --locked
          uv run --locked career setup-renderer
          uv run --locked career validate
          for version in "$CAREER_DATA_ROOT"/resumes/*/; do
            [ -d "$version" ] || continue
            uv run --locked career verify "$(basename "$version")"
          done
"""


def init(root: Path) -> dict:
    created = []
    directories = [Path("knowledge") / kind for kind in get_args(Kind)]
    directories += [Path("knowledge/attachments"), Path("resumes"), Path("applications"), Path("evaluations"), Path("work")]
    for relative in directories:
        path = root / relative
        if not path.exists():
            path.mkdir(parents=True)
            (path / ".gitkeep").touch()
            created.append(relative.as_posix() + "/")
    for relative, content in {
        ".gitignore": GITIGNORE, "README.md": README, ".github/workflows/career-data.yml": WORKFLOW,
    }.items():
        path = root / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            created.append(relative)
    return {"root": str(root), "created": created}
