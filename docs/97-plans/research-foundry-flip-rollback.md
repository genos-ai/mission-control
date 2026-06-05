# Research + Tier-1 Agents → Foundry (gpt-5.x) — Rollback Recipe

Migration performed **2026-06-05** in two waves:

- **Wave 1** (13:19 UTC): 5 research agents flipped from Copilot to Foundry. Smoke-tested first.
- **Wave 2** (13:38 UTC): 10 Tier-1 (mission/system) agents flipped per tier rule (opus→5.4, sonnet→5-mini, haiku→5-nano) with `mission.director.agent` (chat-facing) overridden to 5.4.

Cost basis: Copilot Enterprise was $0 subscription; Foundry is per-token billing on `gis-mission-control-resource` (Sweden Central, Entra auth, DataZoneStandard SKU).

**Prior context**: commits `f261dab` and `8a69d64` show a previous Plan-82 attempt to flip the same Tier-1 set to `foundry:gpt-4.1` was reverted. This migration targets the gpt-5.x family — different models, but same overall risk profile. Roll back fast if quality regresses.

## What changed — Wave 1 (research)

| Agent | Before | After | Why this tier |
|---|---|---|---|
| `research.strategist.agent` | `copilot:claude-sonnet-4.6` | `foundry:gpt-5.4` | Reasoning-critical — query decomposition cascades |
| `research.synthesizer.agent` | `copilot:claude-sonnet-4.6` | `foundry:gpt-5.4` | Quality-critical, long output (32K cap) |
| `research.searcher.agent` | `copilot:claude-sonnet-4.6` | `foundry:gpt-5-mini` | High-volume search/extract |
| `research.analyst.agent` | `copilot:claude-sonnet-4.6` | `foundry:gpt-5-mini` | Coverage classification |
| `research.verifier.agent` | `copilot:claude-haiku-4.5` | `foundry:gpt-5-nano` | Per-claim NLI — highest volume, simplest |

## What changed — Wave 2 (mission + system, Tier 1)

| Agent | Before | After | Tier rule applied |
|---|---|---|---|
| `mission.workflow.agent` | `copilot:claude-opus-4.6` | `foundry:gpt-5.4` | opus → 5.4 |
| `mission.workflow.architect` | `copilot:claude-opus-4.6` | `foundry:gpt-5.4` | opus → 5.4 |
| `mission.director.agent` ⚠️ chat | `copilot:claude-sonnet-4.6` | `foundry:gpt-5.4` | **override** — user-facing chat warrants top tier |
| `system.planning.agent` | `copilot:claude-sonnet-4.6` | `foundry:gpt-5-mini` | sonnet → 5-mini |
| `system.knowledge.officer.agent` | `copilot:claude-sonnet-4.6` | `foundry:gpt-5-mini` | sonnet → 5-mini |
| `mission.planning.agent` | `copilot:claude-haiku-4.5` | `foundry:gpt-5-nano` | haiku → 5-nano |
| `mission.supervisor.agent` | `copilot:claude-haiku-4.5` | `foundry:gpt-5-nano` | haiku → 5-nano |
| `system.summarization.agent` | `copilot:claude-haiku-4.5` | `foundry:gpt-5-nano` | haiku → 5-nano |
| `system.synthesis.agent` | `copilot:claude-haiku-4.5` | `foundry:gpt-5-nano` | haiku → 5-nano |
| `system.verification.agent` | `copilot:claude-haiku-4.5` | `foundry:gpt-5-nano` | haiku → 5-nano |

**Not flipped**: all `deliberation.*` agents (Think Tank) remain on Copilot. They are quality-sensitive and the Think Tank workflow is settled (`[[project_think_tank_validation]]`). Revisit only if a deliberate Think-Tank canary is planned.

Only the `name` field of `model_config_json` was changed in every case. `temperature`, `max_tokens`, and all other agent fields are untouched.

## Pre-flip snapshots

Captured from `agent_catalog` table immediately before each wave.

**Wave 1 — research:**

```json
[
  {"agent_name": "research.analyst.agent",     "model": "copilot:claude-sonnet-4.6", "max_tokens": 8192,  "temperature": 0.0},
  {"agent_name": "research.searcher.agent",    "model": "copilot:claude-sonnet-4.6", "max_tokens": 8192,  "temperature": 0.0},
  {"agent_name": "research.strategist.agent",  "model": "copilot:claude-sonnet-4.6", "max_tokens": 16384, "temperature": 0.0},
  {"agent_name": "research.synthesizer.agent", "model": "copilot:claude-sonnet-4.6", "max_tokens": 32768, "temperature": 0.0},
  {"agent_name": "research.verifier.agent",    "model": "copilot:claude-haiku-4.5",  "max_tokens": 8192,  "temperature": 0.0}
]
```

**Wave 2 — Tier 1:**

```json
[
  {"agent_name": "mission.director.agent",          "model": "copilot:claude-sonnet-4.6", "max_tokens": 16384, "temperature": 0.0},
  {"agent_name": "mission.workflow.agent",          "model": "copilot:claude-opus-4.6",   "max_tokens": 16384, "temperature": 1.0},
  {"agent_name": "mission.workflow.architect",      "model": "copilot:claude-opus-4.6",   "max_tokens": 16384, "temperature": 1.0},
  {"agent_name": "mission.planning.agent",          "model": "copilot:claude-haiku-4.5",  "max_tokens": 16000, "temperature": 0.2},
  {"agent_name": "mission.supervisor.agent",        "model": "copilot:claude-haiku-4.5",  "max_tokens": 1000,  "temperature": 0.0},
  {"agent_name": "system.planning.agent",           "model": "copilot:claude-sonnet-4.6", "max_tokens": 16384, "temperature": 0.2},
  {"agent_name": "system.knowledge.officer.agent",  "model": "copilot:claude-sonnet-4.6", "max_tokens": 4096,  "temperature": 0},
  {"agent_name": "system.summarization.agent",      "model": "copilot:claude-haiku-4.5",  "max_tokens": 4096,  "temperature": 0.0},
  {"agent_name": "system.synthesis.agent",          "model": "copilot:claude-haiku-4.5",  "max_tokens": 4096,  "temperature": 0.0},
  {"agent_name": "system.verification.agent",       "model": "copilot:claude-haiku-4.5",  "max_tokens": 4096,  "temperature": 0.0}
]
```

Full JSON snapshots (with all fields) were written at migration time to:
- `/tmp/research-agents-snapshot-20260605T091903Z.json`
- `/tmp/tier1-agents-snapshot-20260605T093754Z.json`

Those paths are ephemeral — this doc is the authoritative record.

## Rollback — one command per agent

The API server must be running (`python admin.py server start`). Each `set-model` call is independent — stop after any one if you only need a partial rollback. **Then bounce the server** so `get_app_config()`'s `@lru_cache` rebuilds against any companion config changes (cost rows etc.).

### Full rollback (all 15)

```bash
# Wave 1 — research
python admin.py catalog set-model research.strategist.agent      copilot:claude-sonnet-4.6
python admin.py catalog set-model research.synthesizer.agent     copilot:claude-sonnet-4.6
python admin.py catalog set-model research.searcher.agent        copilot:claude-sonnet-4.6
python admin.py catalog set-model research.analyst.agent         copilot:claude-sonnet-4.6
python admin.py catalog set-model research.verifier.agent        copilot:claude-haiku-4.5

# Wave 2 — Tier 1
python admin.py catalog set-model mission.director.agent         copilot:claude-sonnet-4.6
python admin.py catalog set-model mission.workflow.agent         copilot:claude-opus-4.6
python admin.py catalog set-model mission.workflow.architect     copilot:claude-opus-4.6
python admin.py catalog set-model mission.planning.agent         copilot:claude-haiku-4.5
python admin.py catalog set-model mission.supervisor.agent       copilot:claude-haiku-4.5
python admin.py catalog set-model system.planning.agent          copilot:claude-sonnet-4.6
python admin.py catalog set-model system.knowledge.officer.agent copilot:claude-sonnet-4.6
python admin.py catalog set-model system.summarization.agent     copilot:claude-haiku-4.5
python admin.py catalog set-model system.synthesis.agent         copilot:claude-haiku-4.5
python admin.py catalog set-model system.verification.agent      copilot:claude-haiku-4.5

python admin.py server restart
```

### Partial rollback — wave only

To roll back **just the Tier-1 wave** (research stays on Foundry), run only the Wave 2 block. To roll back **just research**, run only the Wave 1 block.

Verify:
```bash
python admin.py catalog models | grep -E "research\.|mission\.|system\."
python mc.py team list
```

## Pricing (verified 2026-06-05)

Sources: [techcommunity.microsoft.com — Introducing GPT-5.4 in Microsoft Foundry](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/introducing-gpt-5-4-in-microsoft-foundry/4499785) and Azure rate sheets. Pricing rows live in `config/agents/mission_control.yaml`.

| Model | Input / 1M | Cached / 1M | Output / 1M |
|---|---|---|---|
| `foundry:gpt-5.4` (≤272K) | $2.50 | $0.25 | $15.00 |
| `foundry:gpt-5-mini` | $0.25 | $0.025 | $2.00 |
| `foundry:gpt-5-nano` | $0.05 | $0.005 | $0.40 |

Smoke-test confirmed `compute_cost_usd` reads these rows correctly (no silent zero fallback).

## Companion config changes

Two YAML edits made alongside the flip — these stay even after rollback:

1. **`config/settings/models.yaml`** — added `gpt-5.4`, `gpt-5-mini`, `gpt-5-nano` to `registry.foundry` so future catalog edits pass validation.
2. **`config/agents/mission_control.yaml`** — added pricing rows above. Without these, cost reporting would silently return $0.

Neither edit needs to be reverted on rollback. They simply make the models available for future use.

## Pre-flip smoke results

All three deployments passed mandatory tests against `gis-mission-control-resource` (Sweden Central, Entra auth, DataZoneStandard SKU):

| Model | Tool mode | Tool calls | Streaming | Cost row applied |
|---|---|---|---|---|
| `gpt-5.4` | PASS | PASS | PASS | $0.000782 (vs $0.000855 fallback) |
| `gpt-5-mini` | PASS | PASS | PASS | $0.000488 (vs $0.003825 fallback) |
| `gpt-5-nano` | PASS | PASS | PASS | $0.000482 (vs $0.018225 fallback) |

Reproduce: `python scripts/foundry_smoke.py --deployment <name> --verbose`.

Test 5 (PydanticAI's stock OpenAI profile recognizing native JSON-schema support) advisory-failed on all three. Tests 6/7 confirmed native mode works at the wire level — to enable it per-agent later, set `output_mode: native` on the agent's `model:` block, which routes through `_build_profile` in `model_builder.py`. Current flip stays in tool mode (P17 default).
