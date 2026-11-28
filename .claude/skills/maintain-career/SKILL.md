---
name: maintain-career
description: Import owner-provided resumes or supporting documents and add or correct verified modular career records in this repository.
---

# Maintain career knowledge

Read the record and intake sections of [the workflow guide](../../../docs/workflows.md). Use `python -m career schema record` for exact field types.

1. Take local files or facts supplied by the owner. Accept English résumés and keep source names, organizations, and titles as recorded. Use `python -m career extract <file>` for a text-based PDF, Markdown, plain text, or YAML. Ask the owner for readable text if a source has no text layer. Capture the source and its relevant excerpt alongside any proposed fact.
2. Use the index and existing entity records to reconcile the source with existing facts. Preserve date precision and existing IDs. Present conflicts or ambiguous metrics, titles, responsibilities, and dates for owner confirmation. Keep pending material in `work/` or use `needs_confirmation` when the owner wants to remember an unresolved record.
3. Store each confirmed entity in its own YAML file. Record substantive facts with stable IDs and link related entities and relevant evidence. Supporting documents stay in `knowledge/attachments/` if the owner chooses to keep a local copy.
4. Run `python -m career validate`, then `python -m career index` and `python -m career index --check`. Report the records updated and any pending facts.

Use the repository's locked Python environment for each command.
