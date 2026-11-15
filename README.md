# Mission Control

**Give an AI team a goal on Monday. Read the result on Friday.**

Mission Control is an autonomous agent platform for work that takes days, weeks or months. You state the objective and set the budget. It plans the work, assigns specialist agents, checks every output, remembers what it learned, and comes back to you only when it needs a decision.

Most agent frameworks answer "can a model do this task?" This one answers the question that decides whether you can trust it: **what happens at hour 40, after a crash, over budget, with nobody watching?**

---

## 1.0 What you get

**Work that outlasts the session.** A mission holds its goal, team, plan, history and cost for as long as it runs. Schedule it (every Monday at 06:00 for six months, say) and each run opens with a digest of the last one. The platform builds on its own earlier work instead of starting cold.

**Runs that survive failure.** Missions execute as Temporal workflows. Each task heartbeats, retries never repeat or re-bill finished work, and recorded run histories are replayed in CI so a code change cannot break a run in flight. Killing a worker mid-run is a drill, not an outage.

**Output that has been checked by someone else.** No agent grades its own work. Every result passes a structural check, a deterministic check and an independent AI evaluator. The supervisor that decides what happens next is mostly plain Python rules, so most decisions are repeatable.

**Autonomy you set, not autonomy you hope for.** Run fully autonomous, or require a human at every decision point. Human approvals wait durably, escalate after 4 hours and pause the mission after 24, rather than failing. Approve from the web, the CLI or Telegram; every approval is tied to a verified identity and logged the same way.

**Spend with a ceiling.** One ledger enforces caps per run, per month and per mission lifetime. Breach one and the run stops cleanly, the schedule pauses and the owner is told.

**A blast radius you can defend.** Agents that write run in isolated containers. If a container cannot start, the task fails. It never falls back to the host.

**Failures that explain themselves.** Every failed task records its origin, class and evidence, assigned by deterministic rules rather than by a model. You see why it failed without reading a transcript.

---

## 2.0 Evidence, not assertion

The Think Tank workflow (four debaters with deliberately different reasoning styles, an independent critic, and a schema that forces disagreement to survive) was tested against a single extended-thinking model call on three contested questions. The first, more elaborate design lost and was shelved. The simplified successor won on all nine rubric dimensions.

The limits: one run per system per question, and cost was not measured. We record that next to the result.

---

## 3.0 Built to be built on

- **One brain, many front ends.** CLI, terminal UI, Telegram and web app hold no business logic. They call the same services, so behaviour never diverges between them.
- **Rules enforced by machine.** 68 architecture rules are checked by script, not by review.
- **Agents that know the codebase.** A generated code map (tree-sitter and PageRank) and a 0 to 100 quality index give coding agents structure up front instead of costly exploration.
- **Self-describing interfaces.** `python mc.py tree` lists every command from the live parser. Nothing to go stale.
- **Any model, any provider.** Anthropic, OpenAI, Azure AI Foundry, GitHub Copilot SDK and Claude Code, selected in configuration. A missing setting stops startup; nothing falls back silently.
- **Closed by default.** Empty allowlists deny everyone. New channels ship disabled.

The agent catalogue holds 31 agents across research, deliberation, security assessment, software quality and platform health. About 112,000 lines of code, over 3,000 tests, 161 documents.

---

## 4.0 Where it stands

| Area | State |
|------|-------|
| Planning, dispatch, verification, supervision | Working |
| Think Tank, deep research, architecture review, web app security assessment | Working; security covers static analysis only |
| Recurring missions: schedules, durable execution, memory between runs | Built and checked live |
| Durable gates, budget caps, lifecycle control, Telegram approval | In progress |
| 7-day and 4-week unattended acceptance runs | Not yet run. Until they pass, long-run endurance is a design goal, not a result |
| Self-improving agent loop experiment | Proposed |

---

## 5.0 Next

- **Run it:** [INSTALL.md](INSTALL.md)
- **Use it:** [USAGE.md](USAGE.md)
- **Understand it:** [vision](docs/01-overview/001-vision.md), [why the mission is the primitive](docs/02-architecture/005-adr-mission-primitive-no-projects-playbooks.md), [principles](docs/03-principles/01-project-principles.md), [reference architecture](docs/10-reference-architecture/00-overview.md)
- **Known gaps:** [TODO.md](TODO.md)

Licence: to be confirmed.
