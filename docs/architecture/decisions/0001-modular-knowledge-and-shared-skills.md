# ADR 0001 · Modular knowledge and shared skills

## Context and problem

Career information must support long-lived updates, stable citations, and targeted retrieval for two agent hosts. The collection will contain private career records with different structures and verification needs.

## Considered alternatives

A master resume offers a compact intake format but couples unrelated changes and tends to promote rendered copy into a source. An embedded database offers query power but introduces migrations and a secondary data interface. Per-host workflows would require synchronizing each change across instructions and skill implementations.

## Decision and rationale

Store typed YAML files by entity kind and use global record IDs, scoped fact IDs, and explicit links. Keep one canonical set of agent instructions. Use a relative skill-directory link for Codex and a native project skill directory and instruction import for Claude Code. Generate a sorted, content-hashed index of discovery metadata and let the agent read selected source files for semantic matching. A verified state records owner confirmation. The generated index remains a disposable derivative of those records.

## Trade-offs and consequences

Version control can review and merge individual records. Relationships and exact field constraints are enforced by Python. Lexical retrieval depends on descriptive titles, tags, aliases, and agent judgment. Windows checkouts without native symlink support require the local link setup described in the workflow guide.
