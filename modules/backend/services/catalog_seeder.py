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

from modules.backend.agents.config_schema import AgentConfigSchema, AgentModelSchema
from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger
from modules.backend.services.agent_catalog import AgentCatalogService

logger = get_logger(__name__)


def _resolve_system_prompt(agent_name: str, project_root: Path) -> str:
    """Load the system prompt markdown for an agent.

    Looks in config/prompts/agents/{category}/{name}/system.md.
    Returns empty string if the file is not found.
    """
    parts = agent_name.replace(".agent", "").split(".")
    if len(parts) < 2:
        return ""

    category = parts[0]
    name = parts[1]
    prompt_path = (
        project_root / "config" / "prompts" / "agents" / category / name / "system.md"
    )

    if not prompt_path.exists():
        logger.debug(
            "No system prompt file found",
            extra={"agent_name": agent_name, "expected_path": str(prompt_path)},
        )
        return ""

    return prompt_path.read_text(encoding="utf-8").strip()


def _extract_model_config(model_field: str | AgentModelSchema) -> dict:
    """Normalise the agent YAML model field to a dict."""
    if isinstance(model_field, AgentModelSchema):
        return {
            "name": model_field.name,
            "temperature": model_field.temperature,
            "max_tokens": model_field.max_tokens,
        }
    return {"name": model_field, "temperature": 0.0, "max_tokens": 4096}


def _infer_visibility(agent_type: str, agent_name: str) -> str:
    """Determine visibility from agent type and name."""
    if agent_type == "system":
        return "system"
    return "public"


async def seed_catalog(
    service: AgentCatalogService,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Seed the agent catalog from YAML files on disk.

    Args:
        service: An AgentCatalogService with an active DB session.
        force: If True, delete all existing rows before seeding.

    Returns:
        Dict with counts: {"seeded": N, "skipped": M, "errors": E}
    """
    project_root = find_project_root()
    agents_dir = project_root / "config" / "agents"

    if not agents_dir.exists():
        logger.warning("Agents config directory not found", extra={"path": str(agents_dir)})
        return {"seeded": 0, "skipped": 0, "errors": 0}

    if not force and not await service.is_catalog_empty():
        logger.info("Catalog already seeded, skipping")
        return {"seeded": 0, "skipped": 0, "errors": 0}

    counts = {"seeded": 0, "skipped": 0, "errors": 0}

    for yaml_path in sorted(agents_dir.rglob("agent.yaml")):
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
                    if config.interface else None
                ),
                constraints={
                    "timeout_seconds": getattr(config, "timeout_seconds", 120),
                    "cost_ceiling_usd": config.max_budget_usd,
                    "retry_budget": 2,
                },
                keywords=config.keywords,
                enabled=config.enabled,
                visibility=_infer_visibility(config.agent_type, config.agent_name),
            )

            # Upsert: update existing entry or create new one.
            # Never delete — that would cascade to mission team members.
            existing = await service.get_by_name_or_none(config.agent_name)
            if existing:
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
