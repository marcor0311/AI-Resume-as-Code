---
name: improve-resume
description: Use an independent ATS report to propose or make an evidence-backed improvement to an English resume.
---

# Improve a resume

1. Use the original English posting, final PDF, and independent JSON report. Run `evaluate-resume` if a current report is absent. Confirm that the posting and PDF hashes correspond to the files being used.
2. Address extraction and formatting findings first. For qualification gaps, retrieve targeted career records and find verified evidence for the exact scope of the requirement. Separate suggestions the verified record supports from qualifications that still need the owner's confirmation. Keep the original posting, evidence records, evaluator, and reports read-only.
3. If the owner requests a revision, use `tailor-resume` and `review-resume` and then save a fresh version. Reevaluate with the baseline's posting bytes, rubric, evaluator, and reference date. Use `compare-resume-versions` to report changed evidence, readability, and scores.
4. For automatic retries within this request, read `configuration.rubric.refinement.max_iterations` in the baseline report. Count each newly generated revision against that cap. Stop sooner when the remaining changes require new verified facts or would harm clarity. Score changes alone do not justify a revision.

Report which evidence was added and which gaps remain. [Evaluation and refinement guide](../../../docs/evaluation.md)
