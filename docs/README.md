# Documentation

This directory contains all project documentation.

## Structure

| Directory | Purpose |
|-----------|---------|
| `01-overview/` | Vision and end-to-end platform flow — start here |
| `02-architecture/` | System design, ADRs, agent blueprint, provider/Copilot integration |
| `03-principles/` | Project-specific principles (P1–P18), non-negotiable for all plans/PRs |
| `04-rules/` | Coding rules, one JSONL file per family. 68 declared; 25 rule IDs are machine-checked by `scripts/code_rules_fast.py`, the remainder (including all of `005_data_layer` and `007_principles`) are convention only |
| `06-prompts/` | Reusable prompt/skill definitions used by this repo's Claude Code setup |
| `07-skills/` | Skill definitions available to AI assistants working in this repo |
| `08-plans/` | Implementation plans — numbered, `-[X]` suffix marks completion |
| `09-research/` | Research and investigation write-ups |
| `10-reference-architecture/` | Universal architecture/coding standards (numbered `core-*`/`opt-*`/`agentic-*`) |
| `99-archive/` | Superseded plans and docs, kept for history — not current |

## Quick Links

- [Vision](01-overview/001-vision.md)
- [Platform Flow](01-overview/002-platform-flow.md)
- [Architecture](02-architecture/README.md)
- [Project Principles](03-principles/01-project-principles.md)
- [Reference Architecture Overview](10-reference-architecture/00-overview.md)
