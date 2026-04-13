"""
Workflow Template Seeder.

Seeds the workflow_definitions table from YAML template files on disk.
System templates have mission_id=NULL — they're global, not mission-scoped.

Runs once on first startup (when no system templates exist). Explicit
re-seeding via CLI uses force mode to delete and reload.

Source files:
    config/workflow_templates/**/*.yaml
"""

import yaml
from pydantic import ValidationError

from modules.backend.core.config import find_project_root, get_app_config
from modules.backend.core.logging import get_logger
from modules.backend.schemas.workflow import WorkflowSchema
from modules.backend.services.workflow_definition import WorkflowDefinitionService

logger = get_logger(__name__)


async def seed_workflows(
    service: WorkflowDefinitionService,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Seed workflow_definitions from YAML templates.

    Scans config/workflow_templates/**/*.yaml (excluding examples/).
    Skips if system templates already exist (unless force=True).
    Each template creates a workflow_definition with:
      - mission_id = NULL (system template)
      - designed_by = "import:yaml_seed"

    Args:
        service: A WorkflowDefinitionService with an active DB session.
        force: If True, delete existing system templates before seeding.

    Returns:
        Dict with counts: {"seeded": N, "skipped": M, "errors": E}
    """
    project_root = find_project_root()
    app_config = get_app_config()
    templates_dir = project_root / app_config.workflows.workflows_dir

    if not templates_dir.exists():
        logger.warning(
            "Workflow templates directory not found",
            extra={"path": str(templates_dir)},
        )
        return {"seeded": 0, "skipped": 0, "errors": 0}

    # Guard: skip if system templates already exist (unless force)
    if not force:
        existing = await service.list_templates()
        if existing:
            logger.info(
                "Workflow templates already seeded, skipping",
                extra={"existing_count": len(existing)},
            )
            return {"seeded": 0, "skipped": 0, "errors": 0}

    if force:
        # Delete existing system templates before re-seeding
        existing = await service.list_templates()
        for defn in existing:
            await service.delete_workflow(defn.id)
        logger.info(
            "Force mode: deleted existing system templates",
            extra={"deleted": len(existing)},
        )

    counts = {"seeded": 0, "skipped": 0, "errors": 0}

    for yaml_path in sorted(templates_dir.rglob("*.yaml")):
        # Skip example files
        if "examples" in yaml_path.parts:
            continue

        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not raw or not isinstance(raw, dict):
                counts["skipped"] += 1
                continue

            if not raw.get("workflow_name"):
                logger.warning(
                    "Workflow YAML missing workflow_name",
                    extra={"path": str(yaml_path)},
                )
                counts["skipped"] += 1
                continue

            # Validate against WorkflowSchema
            schema = WorkflowSchema(**raw)

            # Derive a clean name from the workflow_name
            name = schema.workflow_name
            if name.endswith(".workflow"):
                name = name[: -len(".workflow")]

            # Check for existing (shouldn't exist after force delete, but safety net)
            try:
                existing = await service.get_workflow(None, name)
                logger.debug(
                    "System template already exists, skipping",
                    extra={"name": name},
                )
                counts["skipped"] += 1
                continue
            except Exception:
                pass  # NotFoundError expected — proceed to create

            await service.create_workflow(
                mission_id=None,
                name=name,
                description=schema.description,
                objective=schema.objective.model_dump(),
                steps=[s.model_dump() for s in schema.steps],
                trigger_config=schema.trigger.model_dump(),
                budget_config=schema.budget.model_dump(),
                context=schema.context,
                designed_by="import:yaml_seed",
            )

            counts["seeded"] += 1
            logger.debug(
                "Workflow template seeded",
                extra={
                    "name": name,
                    "version": schema.version,
                    "steps": len(schema.steps),
                },
            )

        except (ValidationError, yaml.YAMLError) as e:
            logger.warning(
                "Failed to seed workflow template",
                extra={"path": str(yaml_path), "error": str(e)},
            )
            counts["errors"] += 1
        except Exception as e:
            logger.error(
                "Unexpected error seeding workflow template",
                extra={"path": str(yaml_path), "error": str(e)},
            )
            counts["errors"] += 1

    logger.info("Workflow template seeding complete", extra=counts)
    return counts
