"""
Catalog YAML Sync Service.

The database is the source of truth for the agent catalog; the
config/agents/**/agent.yaml files are the version-controlled seed. When the
catalog changes at runtime (admin API, ``catalog set-provider``) the YAML falls
behind, and a later ``seed-catalog --force`` would silently revert the change.

This service reports that drift and writes the database values back into the
existing YAML files. It edits only the fields in ``_FIELDS``, keeps comments and
formatting (ruamel round-trip), and refuses to write a file that would stop
validating against AgentConfigSchema or would not converge. It never creates or
deletes a file, and it does not touch system prompts, which live in
config/prompts as separate markdown files.
"""

import io
import math
import os
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import ScalarString
from sqlalchemy.ext.asyncio import AsyncSession

from modules.backend.core.agent_files import find_agent_files
from modules.backend.core.config import find_project_root, get_app_config
from modules.backend.core.exceptions import ValidationError
from modules.backend.core.logging import get_logger
from modules.backend.schemas.agent_config import (
    AgentConfigSchema,
    AgentModelSchema,
    FileScopeConfigSchema,
)
from modules.backend.schemas.catalog_yaml_sync import (
    AgentDrift,
    FieldChange,
    SyncFailure,
    YamlSyncReport,
)
from modules.backend.services.agent_catalog import AgentCatalogService
from modules.backend.services.base import BaseService

logger = get_logger(__name__)


def _schema_default(schema: type, name: str) -> Callable[[], Any]:
    """The default a schema gives field ``name``, read when needed so it cannot drift."""
    return lambda: schema.model_fields[name].get_default(call_default_factory=True)


def _timeout_default() -> int:
    """The task timeout an agent gets when its YAML sets none (application.yaml)."""
    return get_app_config().application.timeouts.agent_task


@dataclass(frozen=True)
class _SyncedField:
    """A YAML field that mirrors a catalog column.

    ``default`` gives what the YAML means when the key is absent, so a database
    value equal to the default does not force a key into the file. Every default
    comes from a schema or from config; none is written here.
    """

    path: tuple[str, ...]
    database: Callable[[Any], Any]
    default: Callable[[], Any] = lambda: None


def _model_config(row: Any) -> dict:
    return row.model_config_json or {}


# Fields the admin API can change, in YAML terms. Not synced: agent_type,
# invocation, execution, produces_artifact (not editable at runtime), visibility
# (derived), and cache_ttl (never seeded).
_FIELDS: tuple[_SyncedField, ...] = (
    _SyncedField(("description",), lambda r: r.description),
    _SyncedField(("enabled",), lambda r: r.enabled),
    _SyncedField(
        ("chat_enabled",),
        lambda r: r.chat_enabled,
        default=_schema_default(AgentConfigSchema, "chat_enabled"),
    ),
    _SyncedField(
        ("version",),
        lambda r: r.version,
        default=_schema_default(AgentConfigSchema, "version"),
    ),
    _SyncedField(
        ("keywords",),
        lambda r: list(r.keywords or []),
        default=_schema_default(AgentConfigSchema, "keywords"),
    ),
    _SyncedField(
        ("tools",),
        lambda r: list(r.tools or []),
        default=_schema_default(AgentConfigSchema, "tools"),
    ),
    _SyncedField(("model", "name"), lambda r: _model_config(r).get("name")),
    _SyncedField(
        ("model", "temperature"),
        lambda r: _model_config(r).get(
            "temperature", _schema_default(AgentModelSchema, "temperature")()
        ),
        default=_schema_default(AgentModelSchema, "temperature"),
    ),
    _SyncedField(
        ("model", "max_tokens"),
        lambda r: (
            _model_config(r).get("max_tokens") or _schema_default(AgentModelSchema, "max_tokens")()
        ),
        default=_schema_default(AgentModelSchema, "max_tokens"),
    ),
    _SyncedField(
        ("scope", "read"),
        lambda r: list((r.scope or {}).get("read", [])),
        default=_schema_default(FileScopeConfigSchema, "read"),
    ),
    _SyncedField(
        ("scope", "write"),
        lambda r: list((r.scope or {}).get("write", [])),
        default=_schema_default(FileScopeConfigSchema, "write"),
    ),
    _SyncedField(("interface",), lambda r: r.interface),
    _SyncedField(
        ("engine",),
        lambda r: r.engine,
        default=_schema_default(AgentConfigSchema, "engine"),
    ),
    _SyncedField(("effort",), lambda r: r.effort),
    # An empty budget means no thinking, the same as no key.
    _SyncedField(("thinking_budget",), lambda r: r.thinking_budget_json or None),
    _SyncedField(("max_budget_usd",), lambda r: r.max_budget_usd),
    _SyncedField(("max_input_length",), lambda r: r.max_input_length),
    _SyncedField(
        ("timeout_seconds",),
        lambda r: (r.constraints or {}).get("timeout_seconds"),
        default=_timeout_default,
    ),
)


def _yaml() -> YAML:
    """A round-trip YAML handler matching the repository's agent file style."""
    handler = YAML(typ="rt")
    handler.preserve_quotes = True
    handler.width = 10_000
    handler.indent(mapping=2, sequence=4, offset=2)
    return handler


def _dump(doc: Any) -> str:
    buffer = io.StringIO()
    _yaml().dump(doc, buffer)
    return buffer.getvalue()


def _plain(value: Any) -> Any:
    """Plain Python for a ruamel node, so values compare and serialise cleanly."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, ScalarString):
        return str(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return value


def _same(a: Any, b: Any) -> bool:
    """Equality that treats 0.1 and 0.10 (and 1 and 1.0) as the same number.

    A boolean only equals a boolean, so ``True`` never matches ``1``.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def _read(doc: Mapping, synced: _SyncedField) -> Any:
    """The effective YAML value of a field: the key if present, else its default."""
    node: Any = doc
    for key in synced.path:
        if synced.path[0] == "model" and isinstance(node, str):
            # Flat spec (`model: provider:name`): the string is the name and the
            # rest of the model block is at its defaults.
            return node if synced.path[-1] == "name" else synced.default()
        if not isinstance(node, Mapping) or key not in node:
            return synced.default()
        node = node[key]
    return node


def _like(old: Any, value: Any) -> Any:
    """``value`` in the same quoting style as the scalar it replaces."""
    if isinstance(old, ScalarString) and isinstance(value, str):
        return type(old)(value)
    return value


def _set(doc: CommentedMap, path: tuple[str, ...], value: Any) -> None:
    """Set one field in place, keeping the comments and quoting around it."""
    if path[0] == "model" and isinstance(doc.get("model"), str):
        name = doc["model"]
        if path == ("model", "name"):
            doc["model"] = _like(name, value)
            return
        block = CommentedMap()
        block["name"] = name
        doc["model"] = block

    node: Any = doc
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, Mapping):
            child = CommentedMap()
            node[key] = child
        node = child

    leaf = path[-1]
    if value is None:
        node.pop(leaf, None)
        return
    old = node.get(leaf)
    if isinstance(old, CommentedSeq) and isinstance(value, list):
        # Edit in place so a comment stays with the items that remain.
        shared = min(len(old), len(value))
        for index in range(shared):
            if old[index] != value[index]:
                old[index] = _like(old[index], value[index])
        del old[shared:]
        old.extend(value[shared:])
        return
    node[leaf] = _like(old, value)


def diff_agent(row: Any, doc: Mapping) -> list[FieldChange]:
    """The synced fields where the YAML document differs from the catalog row."""
    changes = []
    for synced in _FIELDS:
        current = _plain(_read(doc, synced))
        wanted = _plain(synced.database(row))
        if not _same(current, wanted):
            changes.append(
                FieldChange(
                    field=".".join(synced.path),
                    yaml_value=current,
                    database_value=wanted,
                )
            )
    return changes


def apply_changes(doc: CommentedMap, changes: list[FieldChange]) -> None:
    """Write the database side of each change into the YAML document."""
    for change in changes:
        _set(doc, tuple(change.field.split(".")), change.database_value)


@dataclass
class _AgentFile:
    path: Path
    text: str
    doc: CommentedMap

    @property
    def stable(self) -> bool:
        """Whether a load and dump reproduces the file byte for byte."""
        return _dump(self.doc) == self.text


@dataclass
class SyncPlan:
    """What a sync would do: the report, and the new text for each file to write."""

    report: YamlSyncReport
    writes: dict[Path, str] = field(default_factory=dict)


def _load_agent_files(project_root: Path) -> dict[str, _AgentFile]:
    """Every agent YAML under ``project_root``, by agent_name."""
    files: dict[str, _AgentFile] = {}
    for path in find_agent_files(project_root):
        text = path.read_text(encoding="utf-8")
        doc = _yaml().load(text)
        if not isinstance(doc, Mapping) or not doc.get("agent_name"):
            continue
        name = str(doc["agent_name"])
        if name in files:
            raise ValidationError(
                f"Agent '{name}' is defined in both {files[name].path} and {path}."
            )
        files[name] = _AgentFile(path=path, text=text, doc=doc)
    return files


def _rewrite(row: Any, agent: _AgentFile, changes: list[FieldChange]) -> str:
    """The new text for ``agent``, or raise ValueError if it must not be written."""
    if not agent.stable:
        raise ValueError("formatting would not be preserved (the file does not round-trip)")

    doc = _yaml().load(agent.text)
    apply_changes(doc, changes)
    text = _dump(doc)

    try:
        AgentConfigSchema(**yaml.safe_load(text))
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "config"
        raise ValueError(f"the result would not validate ({location}: {first['msg']})") from exc

    if diff_agent(row, _yaml().load(text)):
        raise ValueError("the result would still differ from the catalog")
    return text


class CatalogYamlSyncService(BaseService):
    """Compare the catalog with the agent YAML files and write the database back."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._catalog = AgentCatalogService(session)

    @staticmethod
    @asynccontextmanager
    async def factory() -> AsyncGenerator["CatalogYamlSyncService", None]:
        """Create a CatalogYamlSyncService with its own DB session."""
        from modules.backend.core.database import get_async_session

        async with get_async_session() as db:
            yield CatalogYamlSyncService(db)

    async def plan(self, *, agent_name: str | None = None) -> SyncPlan:
        """Compare every catalog row (or just ``agent_name``) with its YAML file."""
        root = find_project_root()
        rows = await self._catalog.list_catalog(enabled_only=False)
        if agent_name is not None:
            rows = [r for r in rows if r.agent_name == agent_name]
            if not rows:
                raise ValidationError(f"Agent '{agent_name}' is not in the catalog.")

        files = _load_agent_files(root)
        drifted: list[AgentDrift] = []
        failures: list[SyncFailure] = []
        writes: dict[Path, str] = {}
        database_only: list[str] = []
        in_sync = 0

        for row in rows:
            agent = files.get(row.agent_name)
            if agent is None:
                database_only.append(row.agent_name)
                continue

            changes = diff_agent(row, agent.doc)
            if not changes:
                in_sync += 1
                continue

            relative = str(agent.path.relative_to(root))
            try:
                writes[agent.path] = _rewrite(row, agent, changes)
            except ValueError as exc:
                failures.append(
                    SyncFailure(agent_name=row.agent_name, path=relative, reason=str(exc))
                )
                continue
            drifted.append(AgentDrift(agent_name=row.agent_name, path=relative, changes=changes))

        in_catalog = {r.agent_name for r in rows}
        yaml_only = [] if agent_name else sorted(set(files) - in_catalog)
        logger.info(
            "Catalog YAML comparison complete",
            extra={"drifted": len(drifted), "failures": len(failures), "in_sync": in_sync},
        )
        return SyncPlan(
            report=YamlSyncReport(
                drifted=drifted,
                failures=failures,
                in_sync=in_sync,
                database_only=sorted(database_only),
                yaml_only=yaml_only,
            ),
            writes=writes,
        )

    @staticmethod
    def apply(plan: SyncPlan) -> None:
        """Write the planned files. Each write replaces the file atomically."""
        for path, text in plan.writes.items():
            temporary = path.with_name(f".{path.name}.sync")
            try:
                temporary.write_text(text, encoding="utf-8")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            logger.info("Agent YAML updated", extra={"path": str(path)})
