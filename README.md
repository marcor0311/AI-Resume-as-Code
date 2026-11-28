# Career as Code

Career as Code keeps professional history in modular YAML records. Codex or Claude Code can tailor an English résumé to an English posting, trace claims to verified sources, and render a reviewed PDF with RenderCV. An independent evaluator reads the delivered PDF and original posting to report readability, job match, and contextual fit.

## Setup

Use Python 3.12–3.14 and `uv`. Run from the repository root.

```sh
uv sync --locked
uv run --locked --offline career setup-renderer
uv run --locked --offline career validate
uv run --locked --offline pytest
```

The first command installs the locked Python environment. `setup-renderer` downloads the checksum-pinned Typst package once. In an offline setup, pass its local copy with `--archive`. After setup, career commands use local files and bundled fonts. See [dependency and testing procedures](docs/workflows.md#dependencies-and-tests).

Keep this engine checkout separate from your private career repository. Run commands from the engine checkout and select the private directory with `--root` or set `CAREER_DATA_ROOT` for both CLIs. Personal input and output directories are ignored in the engine checkout.

```sh
export CAREER_DATA_ROOT=/path/to/private-career
uv run --locked --offline career init      # create the private layout and its CI workflow
uv run --locked --offline career validate
```

## Use

1. Open Codex or Claude Code at the repository root. Use `maintain-career` to import or add facts supplied by the owner.
2. Supply an English posting as pasted text or a local file and invoke `tailor-resume`. It starts with `career gaps` to show which requirements your verified facts cover, and `career run` takes the draft from preview through sealing, stopping for review. `career letter` builds a cover letter from the same cited facts. Translate any non-English posting before supplying it. The draft includes evidence citations.
3. Use `review-resume` on the frozen draft and preview. Finalization verifies the rendered PDF and saves a new version with both ATS reports.
4. Track what happened with `career apply <version> <status>` and `career applications`. `career-eval calibrate` checks the scores against those outcomes.
5. Use `evaluate-resume` on an existing English PDF, `improve-resume` to review verified opportunities, or `compare-resume-versions` to compare PDFs evaluated against the same posting.

Usage, file contracts, scoring rules, and design decisions are documented in the [workflow guide](docs/workflows.md), [evaluator guide](docs/evaluation.md), and [architecture decisions](docs/architecture/decisions/).

| Path | Purpose |
| --- | --- |
| `knowledge/<kind>/` | Canonical career records |
| `knowledge/attachments/` | Optional supporting documents |
| `knowledge/index.json` | Regenerated discovery metadata |
| `work/` | In-progress drafts, previews, and cover letters |
| `applications/` | Application events per version, outside the sealed archive |
| `resumes/<version>/` | Inputs, PDF, evidence, evaluation reports, and integrity metadata for one historical version |
| `evaluations/<id>/` | Standalone evaluation reports for an existing English PDF |
| `career/` | Deterministic validation and rendering commands |
| `evaluation/` | Independent PDF evaluator and versioned scoring rubric |
| `.claude/skills/` | Shared skills, exposed to Codex through `.agents/skills` |
| `tests/fixtures/demo/` | Synthetic records, posting and draft examples |

For Git-based personal history, version the records and sealed artifacts in the separate private repository.
