---
name: compare-resume-versions
description: Compare English resume versions or outputs from different agents under the same independent ATS evaluation criteria.
---

# Compare resume versions

1. Identify the baseline and candidate. An original English PDF can be the baseline. Use their saved evaluator reports or run `evaluate-resume` on both with the same original English posting and trusted rubric.
2. Run `python -m evaluation compare <baseline-json> <candidate-json>`. To preserve the comparison, pass `--output-id <fresh-id>`. If the engine reports different postings or methods, explain the difference and reevaluate with equivalent settings before comparing scores.
3. Report score deltas, changed requirement evidence, remaining gaps, and changes in parsing and context. Use both report evidence and the actual PDFs when explaining a regression.

Keep the historical versions untouched. [Comparison details](../../../docs/evaluation.md#compare-and-refine)
