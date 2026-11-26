# ADR 0003 · Independent English PDF evaluation

## Context and problem

A tailored draft can pass its evidence review and still omit characters, scramble reading order, or foreground keywords without demonstrating the requested work. An owner comparing versions needs the same evaluator to read the actual delivered PDF and the same English posting.

## Considered alternatives

A weighted scorer over structured profile and posting data is straightforward to inspect but can count content that never reaches the PDF. A second PDF extraction stack offers different geometry behavior at the cost of a second parser and runtime. Model-generated ratings can help with nuanced equivalence and context but vary across executions and require a model and a distinct review context.

## Decision and rationale

Use the pinned PDF library for text and geometry. Make the evaluator independently executable and give it only the PDF and exact English posting bytes for scoring. Use an explicit versioned rubric with applicable-weight normalization, separate readability and requirement scores, and a separately reported contextual score. Match observed job evidence to page and line coordinates. A vetted alias can establish the same concept. Adjacent technologies can inform contextual relevance while leaving the exact qualification gap visible.

Save both reports inside each new sealed résumé version after rendering. Older archives remain readable and reproducible. Standalone runs preserve separate reports for external baselines. Comparisons require an identical posting and equivalent engine and configuration.

## Trade-offs and consequences

Conservative rules are reproducible, produce auditable decisions, and avoid extra services. They can miss unusual terminology and cannot verify facts outside the submitted PDF. Rich layout elements are diagnosed heuristically. PDF source assertions help assess missing text without changing scores. The document is advisory and factual review remains the publication gate for claims.

The checkout contains the engine and synthetic tests. Point both CLIs at the owner's separate private data root for records, postings, reports, and history.
