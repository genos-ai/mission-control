"""
Domain Tag Taxonomy.

Validates and normalizes domain tags used across learnings, intents,
decisions, milestones, and task executions. Tags are flat labels for
structured filtering — not an ontology.

Valid tags = CROSS_CUTTING_TAGS ∪ MCD architecture.components keys.
Invalid tags are logged and dropped, never rejected (per Plan 57 §4.2).
"""

import re
from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Standard tags that apply across all missions regardless of MCD content.
CROSS_CUTTING_TAGS: frozenset[str] = frozenset(
    {
        "auth",
        "api",
        "database",
        "testing",
        "deployment",
        "security",
        "performance",
        "documentation",
        "config",
        "infra",
        "backend",
        "frontend",
        "tui",
        "cli",
        "code",
        "implementation",
        "refactor",
        "bugfix",
        "feature",
        "migration",
        "quality",
        "observability",
    }
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_tag(raw: str) -> str:
    """Lowercase, strip whitespace, collapse non-alphanumeric to single hyphen.

    Examples:
        'Auth'          -> 'auth'
        'Bug Fix'       -> 'bugfix'
        ' deployment '  -> 'deployment'
        'code--quality' -> 'code-quality'
    """
    lowered = raw.strip().lower()
    # Remove spaces (common variant: "bug fix" -> "bugfix")
    collapsed = _SLUG_RE.sub("", lowered)
    return collapsed


def validate_tags(
    tags: list[str],
    mcd: dict | None = None,
) -> tuple[list[str], list[str]]:
    """Validate and normalize a list of domain tags.

    Args:
        tags: Raw tags to validate.
        mcd: Optional Mission Context Document. When provided, component
             keys from ``mcd.architecture.components`` are accepted as
             valid tags alongside the cross-cutting set.

    Returns:
        (valid_tags, invalid_tags) — both lists contain normalized tags.
        Duplicates are removed from the valid list.
    """
    # Build the allowlist for this invocation
    allowed = set(CROSS_CUTTING_TAGS)
    if mcd:
        components = _extract_component_keys(mcd)
        allowed.update(components)

    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for raw in tags:
        normalized = normalize_tag(raw)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)

        if normalized in allowed:
            valid.append(normalized)
        else:
            invalid.append(normalized)

    if invalid:
        logger.debug(
            "Invalid domain tags dropped",
            extra={"invalid_tags": invalid, "valid_tags": valid},
        )

    return valid, invalid


def infer_tags_from_manifest(
    file_manifest: Any,
    mcd: dict | None = None,
) -> list[str]:
    """Derive domain tags from file paths in a FileManifest.

    Uses the MCD ``identity.repo_structure`` mapping to infer which
    domain a file belongs to. Falls back to path-segment heuristics.

    Args:
        file_manifest: A ``FileManifest`` instance (or any object with
                       ``read_first``, ``modify``, ``read_for_pattern``
                       attributes containing ``FileManifestEntry`` items).
        mcd: Optional Mission Context Document for repo_structure lookup.

    Returns:
        Deduplicated list of normalized, valid tags.
    """
    if file_manifest is None:
        return []

    # Collect all file paths from the manifest
    paths: list[str] = []
    for attr in ("modify", "read_first", "read_for_pattern"):
        entries = getattr(file_manifest, attr, [])
        for entry in entries:
            path = getattr(entry, "path", None) or (entry if isinstance(entry, str) else "")
            if path:
                paths.append(path)

    if not paths:
        return []

    # Build repo_structure reverse map: directory prefix -> tag
    repo_map: dict[str, str] = {}
    if mcd:
        repo_structure = mcd.get("identity", {}).get("repo_structure", {})
        for prefix, description in repo_structure.items():
            # Derive tag from the prefix: "modules/backend/agents/" -> "agents"
            tag = normalize_tag(prefix.rstrip("/").split("/")[-1])
            if tag:
                repo_map[prefix.rstrip("/")] = tag

    # Infer tags from paths
    inferred: set[str] = set()
    for path in paths:
        # Try repo_structure mapping first
        for prefix, tag in repo_map.items():
            if path.startswith(prefix):
                inferred.add(tag)
                break
        else:
            # Heuristic: second-level directory as tag
            # e.g. "modules/backend/services/foo.py" -> "services"
            parts = path.split("/")
            if len(parts) >= 3:
                candidate = normalize_tag(parts[2])
                if candidate:
                    inferred.add(candidate)

    # Validate against allowlist
    valid, _ = validate_tags(list(inferred), mcd)
    return valid


def _extract_component_keys(mcd: dict) -> set[str]:
    """Extract component names from MCD architecture section.

    Normalizes component keys so they work as tags.
    """
    components = mcd.get("architecture", {}).get("components", {})
    return {normalize_tag(k) for k in components if normalize_tag(k)}
