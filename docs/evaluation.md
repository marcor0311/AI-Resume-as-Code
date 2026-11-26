# Independent ATS evaluation

The evaluator reads a final English PDF and the original English posting supplied by the owner. Translate a non-English posting before supplying it to the tool. The scorer uses English rules and rejects prose it can clearly identify as non-English. Short technical fragments and proper names are allowed through the coarse language check.

## Run an evaluation

Run from the engine's checkout. Use `--root` or `CAREER_DATA_ROOT` to direct personal outputs to the owner's private data root.

```sh
uv run --locked --offline python -m evaluation --root /path/to/private-career score platform-baseline \
  --pdf /path/to/private-career/original.pdf --posting /path/to/private-career/posting.txt
```

The command saves `ats-evaluation.json` and `ats-evaluation.md` under `evaluations/<id>/`. Both are saved together under a new ID. Use real files with the same bytes for a future repeat. Finalizing a generated résumé automatically saves both reports in that version's sealed directory. To evaluate legacy English versions, supply their archived `resume.pdf` and `posting.txt` to the standalone command.

An owner can select a trusted rubric with `--config PATH`. Use `python -m evaluation rubric --schema` to inspect its schema. Use `--as-of YYYY-MM-DD` to evaluate open employment periods or credential dates against a fixed reference date. Use `--no-semantic` to omit the optional contextual score. Use `--expected-text PATH` to check expected source phrases, one per line. Missing phrases are reported as a rendering diagnostic and leave the scores unchanged.

The command refuses a PDF without extractable text, such as a scanned image, or a file it cannot parse, and saves nothing. This prevents a misleading zero. Pass `--allow-unreadable` to save the report anyway. The library function `evaluate` still returns a zero-score report for such input.

Each standalone report includes a `cross_check` block. It compares the scored text with pypdf's plain reading mode and, when installed, Poppler's `pdftotext`, which approximates a second ATS parser. It reports token and reading-order agreement and warns below 90%. The cross-check is diagnostic and never changes a score.

## Calibration

The rubric is coherent on synthetic cases, and real outcomes are the remaining test. `python -m evaluation calibrate` reads `applications/` in the data root, keeps versions with a decided outcome and a sealed report, and reports, for each score, the AUC: the probability that an application that reached a screen, interview, or offer outscored one that did not. 0.5 means no separation. `--cases cases.yaml` accepts a list of `{id, report, advanced}` entries with report paths relative to the file. Results with fewer than 10 cases, or without both outcomes, carry warnings. Application outcomes also depend on factors the résumé cannot show, so treat the AUC as a check on the rubric, not a hiring forecast.

## Scoring methodology

Each component measures from 0 to 100. A component with insufficient applicable inputs is reported as N/A. The calculation is a weighted mean over applicable components, so an omitted component's weight is redistributed. The report includes the original weights, effective weights, component scores and their contributions.

| Layer | Default component weights |
| --- | --- |
| Overall deterministic compatibility | ATS Readiness 25%, Job Match 75% |
| ATS Readiness | Text extraction 25%, section structure 20%, contact 10%, date consistency 15%, layout 20%, character integrity 10% |
| Job Match | Required qualifications 45%, responsibilities 50%, preferred qualifications 5% |
| Semantic Fit | Demonstrated context 50%, direct or transferable evidence 25%, depth 25% |

For a component set with applicable scores \(s_i\) and percentage weights \(w_i\), the score is `sum(s_i * w_i) / sum(w_i)`. Job Match then applies the configured cap when no requirements were identified and subtracts the capped stuffing deduction. The default deduction is 7 points per triggered rule up to 20 points. The repetition rules look for identical lines, multiple occurrences of a term on one line, and dense posting-term lists in narrative sections. A term used once across different statements can earn its keyword credit without triggering a frequency penalty. Job Match is zero when no usable professional evidence is extractable. Overall uses the reported ATS Readiness and Job Match values, rounded to two decimal places. The Semantic Fit Score is always separate.

The default rubric reports role title and literal keyword coverage as zero-weight diagnostics. This keeps wording and historical job-title differences visible while Job Match uses qualification and responsibility evidence. The owner can inspect the weights, status and contextual points, language proficiency levels, section aliases, scope terms, equivalent names, related technologies and thresholds in [the default rubric](../evaluation/config/scoring.yaml). The engine records the scorer fingerprint, parser and Unicode versions, both input hashes, the full configuration and its hash, the optional reference date, and an evaluation timestamp. Repeat runs can differ in timestamp. The same eligible inputs and configuration produce the same scores and evidence.

### PDF parsing

The extractor reads selectable text and geometry using the existing pinned PDF library. Heading aliases segment work, projects, education, skills, credentials, and languages. The readiness report shows which recognized sections contain data, which contact channels were extractable, the dominant date format, invalid ranges, page estimates, garbled glyphs and layout warnings. Education and credentials contribute to readability when their heading is present. An empty declared section counts as an extraction problem. No OCR is performed. A PDF page with detected nonvisible or tiny text is excluded from job evidence.

Text points are the usable page fraction times the capped ratio of readable characters to the configured target. Structure uses the rubric's section weights. Contact is an extractable header channel check. Dates use the share of recognizable dates in the dominant format, with zero for invalid or inverted ranges. Layout uses the fraction of pages without detected columns or hidden text. Character points decline linearly as the suspicious character fraction approaches the configured cutoff.

Parallel text regions with enough overlapping rows warn about reading order. A format with coordinates the parser cannot evaluate reliably can still produce an incomplete diagnosis. Selectable text does not establish semantic accuracy, prove every graphical element survived, or certify compatibility across Workday, Greenhouse, Taleo, or any other system.

### Requirements and semantic fit

Posting headings and explicit cues identify required, preferred, duty, and informational clauses. The parser recognizes bullets and unbulleted sections and can extract a role stated in introductory prose. Work mode, requisition metadata, and recruiting boilerplate are informational. Requirements are reported in posting order with their original wording, importance, citations, and an improvement when applicable. Protected and demographic posting criteria are informational. CV header information can establish a readable contact channel and supplies no qualification evidence.

| Status | Meaning | Default Job Match points |
| --- | --- | ---: |
| MET | The PDF demonstrates the scope the rule can verify | 100 |
| PARTIALLY_MET | A mention, limited example, or some parts of the requirement are visible | 45 |
| NOT_DEMONSTRATED | The submitted PDF supplies no adequate evidence | 0 |
| NOT_MET | The PDF explicitly indicates a conflicting qualification, such as a lower stated proficiency | 0 |
| UNCERTAIN | Available evidence is ambiguous or unusable | 0 |
| NOT_APPLICABLE | Informational or excluded input | N/A |

Known aliases, such as Kubernetes and K8s, can match a concept without a literal keyword match. Adjacent technologies, such as OpenTofu for Terraform, can improve the separate contextual score while leaving the exact Job Match gap. A clearly stated choice among known alternatives counts as one group for literal keyword coverage. Independently required terms are still assessed against their own requirements. Examples in experience and projects score higher than skill inventory mentions. Each recognizable action in a compound responsibility needs evidence for full credit. Each named degree field in a list of alternatives is checked against the education entry.

Dates establish conservative, non-overlapping duration for work roles. Recognizable dated technical titles can establish a general technical tenure minimum. A technology-specific role interval supplies partial evidence of time spent on that technology. An explicit duration must match the required experience scope. A separate preference introduced by language like “preferably” does not restrict the required minimum. Open periods require a reference date. Degree abbreviations are recognized, and closely related disciplines can be credited when the posting allows related qualifications. A posting's target title is compared to historical titles in the PDF.

The practice rules recognize observable parts of duties such as client support from trial to production and data workflows from source through validation to reporting. They use the text of complete wrapped bullets and cite the contributing PDF lines. A claim about an end-to-end workflow needs evidence linking its stages. A client guidance example and an independent AI project provide partial coverage for a duty that specifically requires using AI in that guidance.

For tools and technologies, the evaluator checks the individual statement that mentions the tool. A neighboring accomplishment supplies no evidence of use in a separate coursework statement. An inventory mention stays partial even when the tool name wraps across lines. Comma-separated actions in an experience bullet can supply evidence when the text describes distinct actions.

The optional contextual layer uses rules and recorded PDF examples. It can surface stated outcomes and related technology and has no model version. It cannot infer unstated experience, verify credentials externally, reliably parse every conjunction, or certify real-world truth. Informational classifications, qualifiers, custom language and synonym coverage may need human review. The engine does not change career records, draft content, or the rubric.

## Compare and refine

Use the same original English posting, evaluator and rubric for each version, including an original PDF baseline or PDFs created by different agents.

```sh
uv run --locked --offline python -m evaluation compare baseline/ats-evaluation.json candidate/ats-evaluation.json
```

Add `--output-id <fresh-id>` to retain Markdown and JSON under `comparisons/`, or `--json` for machine-readable stdout. The command checks posting byte hashes, evaluator identity, parser, and configuration identity. A mismatch explains which settings differ and requires a new evaluation before a numeric comparison.

Use the shared `evaluate-resume`, `improve-resume`, and `compare-resume-versions` skills from Codex or Claude Code. The generation skill selects verified evidence and saves a new version. It uses the shipped evaluator for each saved version and leaves its config and previous reports untouched. A trusted custom rubric is an explicit owner input to standalone evaluation. Keep the engine checkout and evaluator config under owner control if the generating agent needs a narrower write boundary.

First fix clear readability problems, then consider gaps that the verified knowledge can support. Reevaluate after each accepted revision. For an automatic refinement request, the skill uses the baseline rubric's `refinement.max_iterations` cap, default 2. If a gap requires new facts, leave it visible. A score gain alone is insufficient grounds for changing a résumé.

A readability fix may improve ATS Readiness by itself. For an otherwise strong match, foreground the demonstrated scope and outcomes using the posting's terminology where accurate. For a partial match, move verified skills into the experience or project bullets that show how they were used. For an unrelated profile, preserve accurate experience and verify missing qualifications before adding them. The report identifies which findings concern PDF formatting, evidence that can be clarified, and gaps that require verified facts.

## Benchmarks and dependencies

The synthetic benchmark uses Typst, the PDF library, and the checked-in fixture text. Run these commands in the locked project environment.

```sh
uv run --locked --offline pytest
uv run --locked --offline python -m tests.benchmark_evaluation
```

The benchmark checks aligned, partial and unrelated PDFs, keyword repetition, equivalent and adjacent concepts, unsupported or contradictory wording, invalid and open dates, malformed files, glyph corruption, columns, English input, and comparison between baseline and tailored content. It includes three posting formats with low, partial, and strong evidence, plus a tenure and duties case from field service. The regression tests assert the requirement classifications and cited evidence as well as score ordering. `tests/test_improvements.py` also pins the exact scores of four fixture PDFs, so a rubric or engine change that moves them fails until the expected values are updated deliberately. The results use synthetic cases.

| Synthetic case | Overall | Readiness | Job Match | Semantic Fit | Literal keyword coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Aligned | 100.00 | 100.00 | 100.00 | 94.84 | 88.89 |
| Partially aligned | 34.11 | 100.00 | 12.15 | 20.94 | 44.44 |
| Unrelated | 31.75 | 100.00 | 9.00 | 12.50 | 0.00 |
| Aligned, short posting | 100.00 | 100.00 | 100.00 | 94.75 | 100.00 |
| Stuffed, same short posting | 53.50 | 100.00 | 38.00 | 15.00 | 100.00 |
| Clinical data, unrelated candidate | 25.00 | 100.00 | 0.00 | 0.00 | 0.00 |
| Data pipelines, partial evidence | 62.90 | 100.00 | 50.53 | 55.58 | 38.46 |
| Cloud solutions, strong evidence | 85.05 | 100.00 | 80.06 | 79.46 | 45.00 |

The unrelated résumé satisfies the generic professional experience minimum, which accounts for its Job Match points. The two short-posting cases have the same literal keyword coverage and different levels of demonstrated work.

| Controlled revision | ATS Readiness before → after | Job Match before → after |
| --- | ---: | ---: |
| Unrelated profile, same text in one reading column | 80.00 → 100.00 | 0.00 → 0.00 |
| Partial fit, verified Python use stated in Experience | 100.00 → 100.00 | 41.84 → 50.53 |
| Strong fit, customer lifecycle scope stated explicitly | 100.00 → 100.00 | 66.31 → 80.06 |

When changing scoring rules, record the expected requirement outcomes before rerunning the same PDFs and postings. Include cases with absent evidence, a different job family, and equally readable PDFs with different qualifications. Preserve original reports. Save reevaluations under fresh IDs and compare the input hashes, individual findings, and actual score changes across engine versions. Use the regular comparison command for résumé changes scored by the same engine and rubric.

### Generated semantic evals

The generator varies English posting wording and headings, tools, candidate details, and PDF line wrapping across client implementation, data engineering, delivery coordination, and field service. Each posting gets seven profiles covering direct evidence, paraphrased evidence, partial scope, a skills inventory, an unrelated action next to a study claim, an explicit denial, and unrelated work. The generator creates the expected findings and proof excerpts before evaluation. Each evaluator call receives the PDF bytes and posting bytes. The suite checks requirement detection and type, full-credit precision and recall, agreement with the expected statuses, citations to the actual supporting text, and score ordering across the profiles.

```sh
uv run --locked --offline python -m tests.semantic_evals \
  --seed 104729 --seed 64151 --postings-per-family 3 --output work/semantic-evals/example
uv run --locked --offline python -m tests.semantic_evals \
  --baseline work/semantic-evals/example/report.json --output work/semantic-evals/example-replay
```

`--output` saves the generated English PDFs, postings, and `report.json`. Replay reads the saved files and checks their hashes against the previous report. A run returns a failing exit code for an incorrect requirement classification, missing expected citation, or incorrect ordering. New seeds vary examples from the same template families. Use archived CVs with their original postings to check prior agent outputs on the same evaluator. When testing a new authoring agent, give it the posting and available candidate facts, freeze the resulting PDF, and send the grader the final PDF and original posting. Keep reference labels and the authoring record outside the grading inputs.

The evaluator reuses the existing Python dependencies. No reference repository code is included. The architectural decision record describes the parser and scorer trade-offs. [Evaluator architecture decision](architecture/decisions/0003-independent-pdf-evaluation.md)
