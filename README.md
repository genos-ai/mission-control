# Mission Control

**An autonomous AI platform for work that runs for days or weeks, under human control.**

Designed, architected and written by **Herman Young**, January to November 2026.

---

## At a glance

| Item | Detail |
|---|---|
| **Author** | Herman Young: sole designer, architect and developer |
| **Built** | January 2026 to present, alongside a full-time role as Global Chief Information Security Officer of an international bank |
| **Commits** | More than 1,300, all by the author, each timestamped by GitHub |
| **Code** | About 130,000 lines of application code (Python and TypeScript), excluding tests, blank lines and comment lines |
| **Tests** | More than 3,400 automated tests |
| **AI agents** | 31 specialist agents across research, deliberation, security assessment, software quality and platform health |
| **AI providers** | Anthropic, OpenAI, Microsoft Azure AI Foundry, GitHub Copilot and Claude Code, selected by configuration |

---

## 1.0 What it is

Mission Control lets a person hand a goal to a team of AI agents and leave it to run. You set the objective, the budget and how much freedom the agents have. The platform plans the work, assigns it to specialist agents, checks every result, remembers what it learned, and comes back to a human only when a decision is needed.

The aim is simple to state: give an AI team a goal on Monday and read a checked result on Friday.

## 2.0 Why it matters

Organisations want AI to take on sustained work: research that runs for weeks, recurring security reviews, ongoing software maintenance. Most AI agents today are built for short tasks with a person watching. Left alone, they lose track of the goal, repeat work after a failure, overspend, and leave no reliable record of what they did. That gap matters most in banking, insurance, government and critical infrastructure, where an unexplained action is not acceptable.

Mission Control treats an AI team the way a regulated bank treats any critical system. Work must survive failure. Output must be checked by someone other than its author. Spending needs a ceiling, actions need a contained blast radius, and every decision needs a record.

It is built to answer the question that decides whether an organisation can trust autonomous AI: **what happens at hour 40, after a crash, over budget, with nobody watching?**

## 3.0 What it does today

**Works across days, weeks and months.** A mission keeps its goal, team, plan, history and cost for as long as it runs. It can be scheduled (every Monday at 06:00 for six months, for example), and each run opens with a summary of the last one, so the platform builds on its own earlier work instead of starting again.

**Survives failure.** Missions run on Temporal, a durable workflow engine (software that records every step so work can resume after a crash). Finished work is never repeated or billed twice. Deliberate crash and failure drills, in which a worker is shut down mid-run, passed in November 2026.

**Checks every result independently.** No agent marks its own work. Each result passes a structural check, a rule-based check and a separate AI evaluator. The supervisor that decides what happens next runs mostly on fixed rules rather than AI judgement, so most decisions are repeatable.

**Contains what agents can do.** Agents that write code run in isolated containers (sealed, disposable computing environments). If a container cannot start, the task stops. It never falls back to running on the host machine.

**Explains its own failures.** Every failed task records where it failed, what kind of failure it was and the evidence. The classification is assigned by fixed rules, not by an AI model, so a person can see why something failed without reading a transcript.

**Closed by default.** Access lists start empty and deny everyone. New channels ship switched off. A missing setting stops the platform from starting; nothing is guessed.

Current mission types: Think Tank structured debate, deep research, software architecture review, and web application security assessment (static code analysis).

## 4.0 Evidence, not assertion

The Think Tank mission puts a contested question to four AI debaters with deliberately different reasoning styles, an independent critic, and a synthesiser that must preserve genuine disagreement rather than average it away.

It was tested against a single advanced AI model answering the same three contested questions in one pass. Both sets of answers were anonymised and shuffled before scoring, so the scorer did not know which system produced which. The first Think Tank design lost and was shelved. Its simplified successor won on every scoring dimension for all three questions: nine of nine comparisons.

The limits are recorded next to the result: one run per system per question, and cost was not measured.

## 5.0 How it is built

- **One engine, several interfaces.** The command line, terminal interface, Telegram and web app contain no business logic. All of them call the same services, so behaviour cannot diverge between them.
- **Rules enforced by machine.** 68 architecture rules are checked by an automated script rather than by manual review.
- **Agents that understand the codebase.** A generated code map and a 0 to 100 quality index give coding agents the structure of a codebase up front, instead of costly exploration.
- **Any model, any provider.** Changing AI provider is a configuration choice, not a rewrite.
- **Documented.** More than 120 architecture, design and research documents.

## 6.0 Status and roadmap

| Capability | Status |
|---|---|
| Planning, task assignment, independent checking, supervision | Working |
| Think Tank, deep research, architecture review | Working |
| Web application security assessment | Working (static code analysis) |
| Recurring missions: schedules, crash recovery, memory between runs | Working; crash and failure drills passed, November 2026 |
| Spending caps, pause and cancel, human approval gates, Telegram approvals | Being completed, November 2026 |
| 7-day and 4-week unattended endurance runs | Next milestone, once approval gates are complete |
| Hypothesis-driven security code review | Designed, not yet built |

## 7.0 About the author

Herman Young has worked in cyber security since 1995 and has been Global Chief Information Security Officer of an international bank since 2013. He was named in the HotTopics Global CISO 100 four years running (2021 to 2024), and earlier trained security professionals at Black Hat in Las Vegas, Seattle, Amsterdam and Johannesburg.

He still writes code every day. Mission Control was designed, architected and written by him alone over ten months, alongside his executive role. Nearly a third of its more than 1,300 commits were made at weekends.

---

For engineers: installation in `INSTALL.md`, usage in `USAGE.md`, architecture and design in `docs/`.
