# Workflows and file contracts

Run `uv run --locked --offline career --help` from the engine checkout. In the commands below, `career` abbreviates `uv run --locked --offline career`, which is equivalent to `python -m career`. The evaluator is also installed as `career-eval`. Set `CAREER_DATA_ROOT` to your private career directory or pass `--root PATH` before or after the command.

## Private data setup

`career --root /path/to/private-career init` creates `knowledge/<kind>/`, `knowledge/attachments/`, `resumes/`, `applications/`, `evaluations/`, and `work/`, plus a `.gitignore`, a README, and a GitHub Actions workflow. Existing files are never overwritten. The workflow checks out the engine from the repository named in the `CAREER_ENGINE_REPOSITORY` Actions variable, then runs `validate` and `verify` for every sealed version on each push. Both the career CLI and independent evaluator use this setting.

## Career records and intake

Put each record in `knowledge/<kind>/<id>.yaml`. The `.yml` extension also works. Use `career schema record` for the discriminated JSON Schema and the synthetic fixture for copyable examples. An ID stays stable when a display name changes. A record has a `kind`, globally unique `id`, `title`, and `status`. Common optional fields are `tags`, `related` record IDs, and `facts`.

| Kind | Structured data used in the workflow |
| --- | --- |
| `profile` | Name as title, email, international phone, location, website |
| `experience` | Job title, organization, start and end, location |
| `volunteer` | Volunteer role, organization, optional dates and location |
| `education` | Field of study as title, institution, degree, dates, location |
| `project` | Project title, dates, location, and facts |
| `certification`, `training` | Credential title, issuer, issued date, optional expiration and aliases |
| `achievement`, `other` | Title, optional date, and facts |
| `skill` | Skill title and aliases |
| `language` | Language title and proficiency |
| `evidence` | Source title and a confirmed excerpt or local attachment path |

Use quoted `"YYYY"`, `"YYYY-MM"`, or `"YYYY-MM-DD"` dates. Use `present` explicitly for ongoing work. With an unknown end, the resume displays only the supplied date. `career validate` checks record shapes, file placement, duplicate IDs, references, calendar validity and ordering, and local attachment paths. It counts an empty knowledge directory as valid during initial setup. A draft needs a verified profile and at least one substantive entry.

A fact has an ID unique within its record, plain-text `text`, and an explicit `status`. Its `sources` may point to evidence records. Its `mentions` may point to skills or credentials the fact substantiates. A `verified` record or fact is an owner-confirmed source. Use `needs_confirmation` for plausible material that the owner has yet to confirm. Store attachments under `knowledge/attachments/` and reference them by path relative to that directory.

Use `career extract PATH` to read a text-based PDF or a local Markdown, UTF-8 text, or YAML document. Extracted text is a draft source for the agent. Reconcile it with existing records, preserve supplied precision, and confirm conflicts before recording them as verified. A source without extractable PDF text requires a readable copy or transcription.

Run `career index` after updating records and `career index --check` to detect stale or edited output. `career retrieve 'incident response' Python` refreshes the index and returns ranked IDs, relative paths, matching terms, and confirmed fact references. Ranking uses titles, tags, verified mentions, and organization names. Follow relevant relationship IDs and inspect the source text for synonyms and actual evidence. The index is derived and ignored by Git.

## Tailoring

Before drafting, run `career gaps path/to/posting.txt` to score the posting against every verified fact with the independent evaluator's matcher. Each requirement shows its status and the fact IDs that support it. Unconfirmed facts never count. Use the gaps to ask the owner for missing evidence with `maintain-career` before writing a draft.

1. Preserve the original English UTF-8 posting with `career start <draft-id> path/to/posting.txt`. That creates `work/<draft-id>/posting.txt` with the input bytes. For pasted text, place the supplied text in a local file first. Translate non-English postings before supplying them.
2. Write `analysis.yaml` in the work directory. Each requirement has its own ID, category, description, and direct quote. Record mandatory and preferred qualifications and responsibilities separately. Supply posting keywords as phrases for lexical comparison. `career schema analysis` exposes the full contract.
3. Retrieve relevant records and use the strongest verified facts. Draft `draft.yaml` in the same directory. The draft selects a profile, an as-of date, a language, an ordered list of records and highlights, and optional summary and technical skills. It references facts as `record-id#fact-id`. A highlight cites facts from its own entry. A technical skill must occur in facts used by the draft or in their typed mentions.
4. Use `career inspect <draft-id>` to validate the draft and print the evidence packet. `career preview <draft-id>` renders and verifies a PDF in a directory named from the packet hash. Reuse that directory if the same packet already has a preview.
5. Complete the review, run `career finish <draft-id> <version-id>`, then `career verify <version-id>`.

`career run <draft-id>` performs steps 4 and 5 in order and stops wherever a person must act. It reports `stopped` and `next`: missing inputs, `awaiting review`, `stale review` when the packet changed, `review requested revisions`, or `ready to finish`. With `--version <version-id>` and a current `ready` review it finishes and verifies the version.

### Cover letters

Write `work/<draft-id>/letter.yaml` (`career schema letter`) with a profile, date, optional recipient and greeting, and paragraphs of sentences. Each sentence cites verified facts like a résumé highlight. `career letter <draft-id>` rejects unconfirmed facts and numbers absent from the cited facts, then writes `letter.md` and `letter-evidence.json`. Wording and meaning still need the same review as résumé claims.

The deterministic projection copies identity, organizations, titles, dates, credentials, and other structured fields directly from verified records. Write new résumé narrative in English and preserve official names and titles as recorded. The pinned engineering resume theme provides a plain, single-column layout. The standalone `resume.yaml` contains the RenderCV design, locale, and frozen reference date.

## Review and quality

Use `career schema review` for the full file contract. The `review.yaml` in the work directory must include the exact packet `input_sha256`, reviewer, claim decisions, coverage for all requirements, all quality dimension notes, and an explicit `ready` or `revise` disposition.

The packet indexes claims by their output path and shows exact source fields or cited verified facts. For every path, compare the entire assertion to the evidence. A translation, visual date conversion, or reworded bullet uses `supported_reformulation`. `verbatim` requires an exact text match. `unsupported` and `needs_confirmation` block finalization. A new source, edit, posting, or selection requires a current review.

For each requirement, use `covered`, `partial`, `gap`, or `needs_confirmation`. Cite claim paths for covered and partial requirements. Check that the claims convey the required depth, duration, context, or scope. A quality review also covers relevance, evidence strength, clarity, action language, quantification, conciseness, consistency, readability, and formatting. Review the preview PDF and its text layer. Choose a fresh context or owner review when available.

The deterministic checks enforce schema, provenance, verified status, known skill and credential terms, and matching numeric tokens. Numeric checks catch changed values and percentage markers. Attribution, units expressed in words, computed seniority, unknown technologies, paraphrase meaning, and skill depth require judgment. The semantic assessment is fallible and the reviewer can flag or reject claims. Keyword coverage is a literal text-layer diagnostic and has no relationship to a hiring probability or vendor-specific ATS score. PDF text checks detect expected text omissions, out-of-order section headings, and blank pages. Visual judgment still covers clipping, spacing, density, and reading order.

## History and regeneration

`resumes/<version-id>/` is created only after the checks pass. Concurrent writes to the same ID contend for a local lock and a finished version rejects overwrites. When an interrupted process leaves a dot-prefixed lock directory behind, confirm that the process is gone before removing that directory. A version retains:

- The original posting, structured analysis, draft, and review.
- The RenderCV YAML, rendered PDF, and extracted text.
- The evidence snapshot and source record hashes, plus deterministic and semantic results.
- Independent JSON and Markdown ATS reports for every new English version.
- The manifest with per-file SHA-256 digests, source Git revision when available, and the actual dependency versions and lockfile digest.

Use `career verify <version-id>` to check the archive, revalidate the recorded analysis and review against the evidence, and re-extract PDF text. `career compare <first-id> <second-id>` shows a unified text diff. The independent evaluator also compares qualification evidence and scores against the same posting. `career reproduce <version-id>` uses historical RenderCV YAML and the recorded toolchain and writes a separate result under `work/reproduced/`. Pass `--output-id <result-id>` to keep multiple reproduction runs. Each run checks page count and normalized PDF text and reports whether the local output also matches byte for byte. Earlier versions retain their original files and language. [Evaluator guide](evaluation.md)

## Applications and outcomes

`career apply <version-id> submitted --employer NAME [--role ROLE] [--date YYYY-MM-DD] [--note TEXT]` starts `applications/<version-id>.yaml`. Later calls append `screen`, `interview`, `offer`, `rejected`, `withdrawn`, or `no_response` events in date order. The file is outside the sealed version, so `verify` is unaffected. `career applications` summarizes the latest status, whether each application advanced, and the version's overall score. `career-eval calibrate` uses these outcomes to measure whether the scores separate advanced applications. [Calibration](evaluation.md#calibration)

## Dependencies and tests

`uv.lock` pins the Python environment. RenderCV validates its own YAML and generates Typst. Typst compiles with packaged fonts and a SHA-256-checked Font Awesome package from the Typst registry, which RenderCV imports for its templates. Running `career setup-renderer --archive <fontawesome-0.6.0.tar.gz>` uses a predownloaded registry package. The cache is ignored and the package license stays with the archive.

The engine is an installable package with `career` and `career-eval` scripts and a `dev` group that provides pytest. `.github/workflows/tests.yml` runs the suite on Linux and macOS for each supported Python version. Review `pyproject.toml` and `uv.lock` when upgrading dependencies. Re-run the integration suite and reproduce a saved version before changing renderer or extraction versions. To restore a prior toolchain, use the lockfile from its matching Git revision or the manifest's recorded versions.

```sh
uv sync --locked
uv run --locked --offline python -m career setup-renderer
uv run --locked --offline pytest
```

Codex discovers the relative symlink at `.agents/skills`. Claude Code discovers the canonical directories at `.claude/skills` and imports `AGENTS.md` through `CLAUDE.md`. Use a Git checkout that preserves symlinks. If a checkout flattened the symlink, use a symlink-capable checkout or configure an equivalent local directory link.
