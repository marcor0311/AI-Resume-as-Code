---
name: tailor-resume
description: Tailor an evidence-backed English resume to an English job posting and preserve a reviewed RenderCV PDF with an independent evaluation.
---

# Tailor a resume

Use the [workflow guide](../../../docs/workflows.md) and the `analysis` and `draft` schemas only for the artifacts you are writing. Run the commands in the locked Python environment.

1. Preserve the supplied English UTF-8 posting with `python -m career start <draft-id> <posting-file>`. For pasted text, first write it unchanged to a local text file. Ask for an English translation if needed. Save `analysis.yaml` next to `posting.txt` with stable requirement IDs, direct quotes, mandatory versus preferred qualifications, responsibilities, and posting terminology.
2. Run `python -m career gaps <posting-file>` to see which requirements verified facts already meet, which are partial, and which have no evidence. Report missing or unconfirmed evidence to the owner before drafting, and use `maintain-career` only for facts the owner confirms. Then run `python -m career retrieve <terms...>`. Follow the returned paths and relevant relationships to read a small set of records. For each requirement, prefer direct verified accomplishments over skill labels or incidental mentions. Rank evidence by relevance, level of ownership, and strength of outcome. Flag transferable experience, gaps, and pending facts for the review.
3. Write `draft.yaml` with the chosen profile, date, language, ordered entries, and exact fact references for each summary sentence or highlight. Preserve canonical titles, dates, organizations, certifications, and qualifications. Change emphasis or wording when the evidence supports the new phrasing. Keep the scope and metric context intact.
4. Run `python -m career run <draft-id>`. It validates, inspects, and previews, then reports where it stopped and the next step. `inspect` and `preview` remain available individually. Use the review skill with the frozen evidence packet, original posting, and preview. Prefer a fresh review context or an owner review when available.
5. Fix any rejected claim and repeat review against the new packet. Run `python -m career run <draft-id> --version <new-version-id>` to finish and verify, or run `finish` and `verify` individually. Return the PDF, gap summary, and the saved independent ATS report. Keep evaluation code, configuration, and historical reports read-only.

If the owner wants a cover letter, write `letter.yaml` in the same work directory (`python -m career schema letter`) with every sentence citing verified facts, and run `python -m career letter <draft-id>`. After the owner sends the resume, suggest `python -m career apply <version-id> submitted --employer <name>`.

Use a fresh version ID for every final version. Keep canonical records read-only throughout this workflow.
