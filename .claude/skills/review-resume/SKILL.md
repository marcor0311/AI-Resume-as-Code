---
name: review-resume
description: Review a frozen tailored resume against its job posting, cited canonical facts, and RenderCV preview, and write a reproducible review decision.
---

# Review a resume

Use the [review contract](../../../docs/workflows.md#review-and-quality) and `python -m career schema review`. Read the original posting and the packet from `python -m career inspect <draft-id>`. Read the matching preview PDF and extracted text.

1. Give every claim path a verdict and concrete reason. Check facts against their cited sources and supporting excerpts. Confirm attribution, scope, technologies, credentials, dates, and the meaning of each quantity. Mark an unchanged source value `verbatim`, a faithful restatement or local display transformation `supported_reformulation`, and unresolved claims `unsupported` or `needs_confirmation`.
2. Give every job requirement a coverage verdict. Cite relevant resume claim paths for covered and partial requirements. Check the original quote to preserve scope. Record gaps, partial matches, and missing confirmation explicitly. Use the lexical keyword results to spot omissions and keep phrase matches distinct from qualification evidence.
3. Assess relevance, evidence strength, clarity, action-oriented language, quantification, conciseness, consistency, readability, and formatting. Inspect the page for clipping, dense layout, and visit order. Select `revise` for any issue that needs a change before finalization.
4. Save `review.yaml` next to the draft with the packet's exact `input_sha256`, reviewer identity or role, all decisions, and the disposition. Review a new packet whenever the inputs change. This skill writes the review and leaves the draft frozen.

Use a fresh review context or an owner review when available. A separate pass in the current session can complete the workflow when only that session is available.
