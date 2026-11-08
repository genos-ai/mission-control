"""
Agent Catalog Seeder.

Seeds the agent_catalog table from YAML config files and system prompt
markdown files on disk. Runs once on first startup (when the table is
empty). Explicit re-seeding via CLI uses force mode to clear and reload.

Source files:
    config/agents/**/agent.yaml   -> agent configuration
    config/prompts/agents/{category}/{name}/system.md -> system prompt
"""

from pathlib import Path

import yaml
from pydantic import ValidationError

from modules.backend.core import agent_defaults
from modules.backend.core.agent_files import agents_dir, find_agent_files
from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger
from modules.backend.schemas.agent_config import AgentConfigSchema, AgentModelSchema
from modules.backend.services.agent_catalog import AgentCatalogService

logger = get_logger(__name__)


def _resolve_system_prompt(agent_name: str, project_root: Path) -> str:
    """Assemble the full layered system prompt from disk files.

    Always reads from disk (never DB) because the seeder is the process
    that WRITES to the DB. Uses _assemble_from_disk() which layers:
      1. Organization prompts (config/prompts/organization/*.md)
      2. Category prompt (config/prompts/categories/{category}.md)
      3. Agent system prompt (config/prompts/agents/{path}/system.md)

    The resulting assembled prompt is stored in agent_catalog.system_prompt
    so agents read from DB at runtime.
    """
    from modules.backend.agents.mission_control.helpers.prompt_builder import (
        _assemble_from_disk,
    )

    try:
        prompt = _assemble_from_disk(agent_name)
        if prompt:
            return prompt
    except Exception:
        logger.debug("prompt assembly from disk failed for %s", agent_name, exc_info=True)

    # Fallback: read just the agent's system.md (no layers)
    parts = agent_name.replace(".agent", "").split(".")
    if len(parts) < 2:
        return ""

    category = parts[0]
    name = parts[1]
    prompt_path = project_root / "config" / "prompts" / "agents" / category / name / "system.md"

    if not prompt_path.exists():
        logger.debug(
            "No system prompt file found",
            extra={"agent_name": agent_name, "expected_path": str(prompt_path)},
        )
        return ""

    return prompt_path.read_text(encoding="utf-8").strip()


def _extract_model_config(model_field: str | AgentModelSchema) -> dict:
    """Normalise the agent YAML model field to a dict, with the schema's defaults."""
    model = (
        model_field
        if isinstance(model_field, AgentModelSchema)
        else AgentModelSchema(name=model_field)
    )
    return {"name": model.name, "temperature": model.temperature, "max_tokens": model.max_tokens}


async def seed_catalog(
    service: AgentCatalogService,
    *,
    force: bool = False,
    reset_prompts: bool = False,
) -> dict[str, int]:
    """Seed the agent catalog from YAML files on disk.

    Args:
        service: An AgentCatalogService with an active DB session.
        force: If True, update all agents from YAML (config fields).
            Preserves DB system_prompt unless reset_prompts is also set.
        reset_prompts: If True (requires force), also overwrite
            system_prompt from disk-assembled layers. Without this,
            prompts edited via the admin API are preserved.

    Returns:
        Dict with counts: {"seeded": N, "skipped": M, "errors": E}
    """
    project_root = find_project_root()
    agent_directory = agents_dir(project_root)

    if not agent_directory.exists():
        logger.warning("Agents config directory not found", extra={"path": str(agent_directory)})
        return {"seeded": 0, "skipped": 0, "errors": 0}

    # TODO(catalog-db-authoritative): Promote the DB to the sole source of
    # truth for agent catalog entries and retire the YAML-seeding flow.
    #
    # Current design: `config/agents/**/agent.yaml` is authoritative, seeded
    # into the DB on first boot (or via `admin seed-catalog --force`).
    # Problem: declarative YAML edits (e.g. `chat_enabled: true`) don't
    # reach the DB without a manual force re-seed, because this guard
    # short-circuits when the catalog is non-empty to avoid clobbering
    # admin-edited fields (system prompts, tools, model config).
    #
    # Target design:
    #   1. DB is authoritative. Agents are created/edited via the admin UI
    #      or the `/admin/catalog` API endpoints — no YAML round-trip.
    #   2. YAML files become optional bootstrap fixtures, used only for
    #      greenfield dev environments or to restore a known-good baseline.
    #   3. A CLI command `admin catalog export` round-trips DB → YAML for
    #      version-control snapshots, and `admin catalog import` applies a
    #      YAML snapshot back to the DB (with an explicit diff preview).
    #   4. Migrations handle schema changes; data changes go through the
    #      admin API with audit trails.
    #
    # Until then: either re-seed with `--force` after YAML edits, or use
    # the admin API to edit catalog rows directly.
    if not force and not await service.is_catalog_empty():
        logger.info("Catalog already seeded, skipping")
        return {"seeded": 0, "skipped": 0, "errors": 0}

    counts = {"seeded": 0, "skipped": 0, "errors": 0}

    for yaml_path in find_agent_files(project_root):
        try:
            with open(yaml_path) as f:
                raw = yaml.safe_load(f)

            if not raw or not isinstance(raw, dict):
                counts["skipped"] += 1
                continue

            if not raw.get("agent_name"):
                logger.warning("Agent YAML missing agent_name", extra={"path": str(yaml_path)})
                counts["skipped"] += 1
                continue

            config = AgentConfigSchema(**raw)
            system_prompt = _resolve_system_prompt(config.agent_name, project_root)

            fields = dict(
                agent_type=config.agent_type,
                version=config.version,
                description=config.description,
                system_prompt=system_prompt,
                model_config_json=_extract_model_config(config.model),
                tools=config.tools,
                scope={"read": config.scope.read, "write": config.scope.write},
                interface=(
                    {"input": config.interface.input, "output": config.interface.output}
                    if config.interface
                    else None
                ),
                constraints={
                    "timeout_seconds": getattr(config, "timeout_seconds", None)
                    or agent_defaults.task_timeout_seconds(),
                    "cost_ceiling_usd": config.max_budget_usd,
                    "retry_budget": (
                        config.retry_budget
                        if config.retry_budget is not None
                        else agent_defaults.retry_budget()
                    ),
                },
                keywords=config.keywords,
                enabled=config.enabled,
                chat_enabled=config.chat_enabled,
                visibility=config.visibility,
                engine=config.engine,
                effort=config.effort,
                # Registry-critical fields (Plan 59)
                invocation_tier=config.invocation.tier,
                invocation_required_role=config.invocation.required_role,
                execution_mode=config.execution.mode,
                thinking_budget_json=config.thinking_budget,
                max_input_length=config.max_input_length,
                max_budget_usd=config.max_budget_usd,
                produces_artifact=config.produces_artifact,
                artifact_type=config.artifact_type,
            )

            # Upsert: update existing entry or create new one.
            # Never delete — that would cascade to mission team members.
            existing = await service.get_by_name_or_none(config.agent_name)
            if existing:
                # Preserve the DB system_prompt unless reset_prompts
                # is explicitly set. This protects admin API edits
                # from being overwritten by a routine seed-catalog.
                if not reset_prompts and existing.system_prompt:
                    fields.pop("system_prompt", None)
                await service.update_entry(config.agent_name, **fields)
                logger.debug("Agent updated", extra={"agent_name": config.agent_name})
            else:
                await service.create_entry(agent_name=config.agent_name, **fields)
                logger.debug("Agent seeded", extra={"agent_name": config.agent_name})

            counts["seeded"] += 1

        except (ValidationError, yaml.YAMLError) as e:
            logger.warning(
                "Failed to seed agent",
                extra={"path": str(yaml_path), "error": str(e)},
            )
            counts["errors"] += 1
        except Exception as e:
            logger.error(
                "Unexpected error seeding agent",
                extra={"path": str(yaml_path), "error": str(e)},
            )
            counts["errors"] += 1

    logger.info("Catalog seeding complete", extra=counts)
    return counts
