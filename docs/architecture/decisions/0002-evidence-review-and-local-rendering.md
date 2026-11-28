# ADR 0002 · Evidence review and local rendering

## Context and problem

Tailoring has to preserve facts while adapting emphasis. Historical resumes must be auditable and reproducible after the source records change.

## Considered alternatives

Hand-edited render input gives agents freedom but leaves dates, credentials, and claims hard to audit. A combined generation and grading call can hide missing evidence. A custom renderer offers control of typography at the cost of maintaining schema, templates, PDF compilation, and multilingual behavior.

## Decision and rationale

Use a typed draft to select canonical fields and cite a verified fact for each narrative claim. Project it into RenderCV through deterministic code. A review covers every resume claim and job requirement and is bound to the frozen posting, analysis, evidence, and projected content. Run RenderCV's model builder and Typst generator with a pinned compiler and checked local assets. Verify the resulting PDF text before atomically publishing a historical directory.

## Trade-offs and consequences

Literal checks catch changed numbers, references, and known terms. Scope, attribution, implied qualifications, and translations still require semantic review. A version packages only the selected evidence excerpts and hashes plus the content necessary for deterministic rerendering. HTML or PDF templates maintained outside the pinned renderer would need a new projection and verification contract. Page count and extracted text form the cross-run comparison, with byte equality reported when observed.
