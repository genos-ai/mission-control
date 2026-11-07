"""Locate the agent YAML files that seed the catalog.

One place for the layout (config/agents/**/agent.yaml) so the seeder, the
registry's YAML fallback and the catalog YAML sync cannot disagree about it.
"""

from pathlib import Path

AGENT_FILE_NAME = "agent.yaml"


def agents_dir(project_root: Path) -> Path:
    """The directory under ``project_root`` that holds the agent YAML files."""
    return project_root / "config" / "agents"


def find_agent_files(project_root: Path) -> list[Path]:
    """Every agent YAML file under ``project_root``, in a stable order."""
    return sorted(agents_dir(project_root).rglob(AGENT_FILE_NAME))
