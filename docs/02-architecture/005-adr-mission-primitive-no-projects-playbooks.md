# ADR-005: Mission as Domain Primitive — Removing Projects and Playbooks

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-18 |
| **Deciders** | Platform team |
| **Supersedes** | Plan 18 Sub-Phase 1 (Project entity), Plan 17 (Playbooks & Missions — playbook layer), Plan 21 (Decouple Playbooks from Projects) |

---

## Context

The original BFA (Building From Architecture) design specified a five-layer execution chain:

```
Project → Playbook → Mission → Mission Control → Agents
```

- **Projects** were the top-level organizational boundary. All missions, playbook runs, context, and history belonged to a project. The PCD (Project Context Document) was scoped to the project.
- **Playbooks** were multi-step YAML recipes. Each step spawned a mission. Steps formed a DAG with data flow between them via `output_mapping` and `upstream_context`.

This design was documented in [002-platform-flow.md](../01-overview/002-platform-flow.md), [Plan 17](../97-plans/17-plan-playbooks-missions-[X].md), [Plan 18](../97-plans/18-plan-project-context-layer-[X].md), and [reference architecture doc 48](../99-reference-architecture/48-agentic-project-context.md).

### What happened during implementation

As the platform was built (Plans 10–57), neither the Project entity nor the Playbook layer was implemented:

1. **Missions became the domain primitive.** AGENTS.md §Design Principles declares: "The mission is the domain primitive. The session is the transport primitive." All context, knowledge, team, workflows, and history are mission-scoped.

2. **MCD replaced PCD.** The Mission Context Document (mission-scoped) was implemented instead of the Project Context Document (project-scoped). Plan 57 extended it with learnings, intents, and embeddings — all mission-scoped with platform promotion for cross-mission visibility.

3. **Workflows replaced playbooks.** Multi-step orchestration moved from filesystem YAML (`config/playbooks/*.yaml`) to DB-stored workflow definitions (`workflow_definitions` table) that are:
   - Mission-scoped (each mission owns its workflows)
   - Agent-designable (Workflow Architect creates them in conversation)
   - Template-seeded (system templates in `config/workflow_templates/` seed on boot, cloned into missions)
   - Integrated with the plan/dispatch pipeline

4. **Cross-mission knowledge uses platform promotion**, not project grouping. A learning becomes platform-visible via `platform_promoted=true`, not by sharing a project_id.

The `config/playbooks/` directory, `PlaybookSchema`, `PlaybookRunService`, `PlaybookRun` model, `ProjectService`, and `Project` model were never created or were removed. No code references them.

### Why the original design was wrong for this platform

| BFA concept | Problem | What replaced it |
|---|---|---|
| **Project** — organizational boundary | Added a layer of indirection without clear value. Missions already carry context, team, workflows, and history. Projects would have required every query to join through `project_id`, every permission check to resolve project membership, and every context operation to scope at the project level instead of the mission level. | **Mission** — the domain primitive. Cross-mission visibility via `platform_promoted` on learnings. |
| **PCD** — project-scoped context | A single PCD shared across many missions would grow unbounded and become a bottleneck. Each mission's context needs are different — a quality-focused mission doesn't need the architecture decisions from a deployment mission. | **MCD** — mission-scoped. Each mission has its own context document, sized for its needs. Fractal summarization compresses old history. |
| **Playbook** — filesystem YAML recipe | Static YAML recipes can't be designed in conversation, can't be versioned per-mission, can't be cloned from templates, and couple the recipe to a filesystem path. | **Workflows** — DB-stored, agent-designable, template-seeded, mission-scoped. |
| **PlaybookRun** — execution of a recipe | Required a separate lifecycle model, FK relationships, and cross-step data flow (`output_mapping`). | **WorkflowRun** — simpler model. Steps execute sequentially within a single mission's execution context. |
| **project_id** — FK on every entity | Would have been on missions, sessions, execution records, context, history. Every query would need a project scope filter. | Not needed. Mission-scoped queries are sufficient. Platform-promoted learnings use a boolean flag. |

## Decision

**The mission is the domain primitive. There is no Project entity. There are no Playbooks.**

The execution chain is:

```
Mission → Mission Control → Agents
```

Multi-step orchestration is handled by **Workflows** (DB-stored, template-seeded, agent-designable).

Cross-mission knowledge is handled by **platform promotion** (`platform_promoted=true` on learnings, sysadmin-gated).

### What this means

- No `projects` table. No `project_id` on any entity.
- No `playbooks/` directory. No `PlaybookSchema`. No `PlaybookRunService`.
- The reference architecture docs (40, 48) that describe projects remain as reference standards for platforms that need project scoping — this platform doesn't.
- [002-platform-flow.md](../01-overview/002-platform-flow.md) updated to reflect the three-layer model.
- Plan 18 marked as done (MCD, ContextAssembler, etc. shipped — Project entity deliberately skipped).
- Plan 21 (Decouple Playbooks from Projects) marked as superseded — both layers removed.

## Consequences

**Positive:**
- Simpler data model — no `project_id` FK on every table
- Simpler queries — no project scope filter on every query
- Simpler permissions — no project membership layer
- Missions are self-contained — context, team, workflows, history all on the mission
- Workflows are more flexible than playbooks — agent-designable, DB-stored, versioned

**Negative:**
- No built-in organizational grouping above the mission level. If a user has 100 missions, there's no folder/project structure. Mitigation: tags, search, and the platform knowledge view.
- No cross-mission data flow (playbook `output_mapping`). Mitigation: workflows handle multi-step within a mission. Cross-mission orchestration is a future need (Plan 46 autonomous roadmap) and would be a new design, not a resurrection of playbooks.
- Reference architecture divergence — docs 40/48 describe a project-scoped model. This platform's implementation is mission-scoped. The reference docs are generic standards; this is a platform-specific decision.

**If cross-mission orchestration is needed later:**
Build it as a new primitive (e.g. "Campaign" — a sequence of missions with data handoff) rather than resurrecting the Project/Playbook model. The mission remains the domain primitive; the campaign is a coordination layer above it.

## References

- AGENTS.md §Design Principles — "The mission is the domain primitive"
- Plan 18 (Project Context Layer) — MCD/ContextAssembler shipped, Project entity skipped
- Plan 17 (Playbooks & Missions) — playbook execution model, superseded by workflows
- Plan 21 (Decouple Playbooks from Projects) — superseded by this decision
- Plan 53 (Workflow DB) — workflows replace playbooks
- Plan 57 (Knowledge Platform) — knowledge is mission-scoped + platform-promoted
- Doc 48 (Agentic Project Context) — generic reference standard, not adopted
