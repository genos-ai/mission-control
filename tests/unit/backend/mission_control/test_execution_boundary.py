"""Fail-closed execution boundary (Plan 88, 88.2.3a; contracts 3.8.5).

No isolated workspace means no execution, never local execution: every path
that used to fall back to the worker host now raises ExecutionEnvironmentError.
"""

import dataclasses
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError
from pydantic_ai import UsageLimits
from sqlalchemy.exc import SQLAlchemyError

from modules.backend.agents.mission_control import runtime
from modules.backend.agents.mission_control.dispatch.environment import resolve_execution_mode
from modules.backend.agents.mission_control.helpers.agent_executor import _make_agent_executor
from modules.backend.agents.mission_control.helpers.cli_executor import (
    CLAUDE_CODE_READ_TOOLS,
    execute_claude_code,
)
from modules.backend.agents.security.tool_runner import _run_tool_subprocess
from modules.backend.core.config import find_project_root, get_app_config
from modules.backend.core.exception_handlers import EXCEPTION_STATUS_MAP
from modules.backend.core.exceptions import ExecutionEnvironmentError, ValidationError
from modules.backend.models.execution_record import ExecutionRecordStatus
from modules.backend.schemas.agent_config import AgentConfigSchema
from modules.backend.schemas.workflow import WorkflowStepSchema
from modules.backend.services import execution_environment
from modules.backend.services.execution_environment import (
    CommandResult,
    EnvironmentHandle,
    ExecutionEnvironmentService,
    run_in_environment,
)
from modules.backend.services.mission import MissionService
from modules.backend.services.workflow_run_steps.helpers import DispatchParams
from modules.backend.services.workflow_run_waves import WorkflowRunWavesMixin
from modules.backend.tools import run_tests as run_tests_tool
from modules.backend.tools.run_command import run_command
from modules.backend.tools.run_tests import RUN_TESTS_ARGV, run_tests

_EXECUTOR = "modules.backend.agents.mission_control.helpers.agent_executor"
_WAVES = "modules.backend.services.workflow_run_waves"


def _handle(host_working_dir: Path | None = Path("/tmp/wt/workspace")) -> EnvironmentHandle:
    return EnvironmentHandle(
        environment_id="env-1",
        mode="container",
        working_dir=Path("/workspace"),
        host_working_dir=host_working_dir,
    )


# =============================================================================
# build_dispatch_runtime
# =============================================================================


async def _build(execution_mode: str, mission_repo_root: str | None, event_bus=None):
    services = runtime.ContextServices(
        roster=MagicMock(), context_curator=MagicMock(), context_assembler=MagicMock()
    )
    with patch.object(runtime, "build_context_services", AsyncMock(return_value=services)):
        return await runtime.build_dispatch_runtime(
            db_session=MagicMock(),
            event_bus=event_bus or AsyncMock(),
            mission_id="11111111-2222-3333-4444-555555555555",
            session_id=str(uuid.uuid4()),
            execution_mode=execution_mode,
            mission_repo_root=mission_repo_root,
            container_image=None,
            extra_volumes=None,
            mission_run_id=None,
            task_id=None,
        )


async def test_container_mode_without_repo_root_raises():
    with pytest.raises(ExecutionEnvironmentError, match="requires repo_root"):
        await _build("container", None)


async def test_provisioning_error_raises_not_local():
    event_bus = AsyncMock()
    boom = RuntimeError("docker daemon unreachable")
    with (
        patch("modules.backend.services.container_backend.ContainerBackend", MagicMock()),
        patch.object(
            ExecutionEnvironmentService,
            "get_or_create_for_mission",
            AsyncMock(side_effect=boom),
        ),
        pytest.raises(ExecutionEnvironmentError) as exc_info,
    ):
        await _build("container", "/repo", event_bus=event_bus)
    assert exc_info.value.__cause__ is boom
    event_bus.publish.assert_not_called()
    event_bus.publish_to_mission.assert_not_called()


async def test_container_without_worktree_raises():
    with (
        patch("modules.backend.services.container_backend.ContainerBackend", MagicMock()),
        patch.object(
            ExecutionEnvironmentService,
            "get_or_create_for_mission",
            AsyncMock(return_value=_handle(host_working_dir=None)),
        ),
        pytest.raises(ExecutionEnvironmentError, match="no host worktree"),
    ):
        await _build("container", "/repo")


def test_validate_mode_raises():
    with pytest.raises(ExecutionEnvironmentError, match="requires repo_root"):
        resolve_execution_mode(mission_environment="container", mission_repo_root=None)


# =============================================================================
# Workflow steps
# =============================================================================


def _waves_service() -> WorkflowRunWavesMixin:
    svc = WorkflowRunWavesMixin()
    svc._workflow_service = MagicMock()
    svc._workflow_service.resolve_upstream_context.return_value = {}
    svc._event_bus = AsyncMock()
    return svc


def _step_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.persistence.count_active = AsyncMock(return_value=0)
    ctx.persistence.save_execution = AsyncMock(return_value=MagicMock(id="rec-1"))
    ctx.persistence.complete_execution = AsyncMock()
    return ctx


def _run() -> MagicMock:
    run = MagicMock()
    run.id = "run-1"
    run.mission_id = "mission-1"
    run.context = {}
    return run


_STEP = WorkflowStepSchema(id="scan", capability="security.webapp", environment="container")


async def test_workflow_wave_passes_repo_root():
    outcome = MagicMock()
    outcome.status = "success"
    outcome.total_cost_usd = 0.0
    outcome.model_dump.return_value = {"task_results": []}
    handle_mission = AsyncMock(return_value=outcome)
    params = DispatchParams(
        execution_mode="container", roster_name="default", mission_repo_root="/repo"
    )
    with (
        patch(f"{_WAVES}.resolve_dispatch_params", AsyncMock(return_value=params)),
        patch(
            "modules.backend.agents.mission_control.mission_dispatch.handle_mission",
            handle_mission,
        ),
        patch("modules.backend.services.session.SessionService", MagicMock()),
    ):
        await _waves_service()._execute_step(_run(), _STEP, str(uuid.uuid4()), {}, _step_ctx())

    kwargs = handle_mission.call_args.kwargs
    assert kwargs["mission_repo_root"] == "/repo"
    assert kwargs["execution_mode"] == "container"


async def test_workflow_step_env_error_fails_step():
    """The env error goes through the step's handler: the step's record ends failed, not running.

    The handler re-raises as RuntimeError so WorkflowRunService's
    (RuntimeError, ValueError, OSError) handler also fails the run.
    """
    handle_mission = AsyncMock()
    svc = _waves_service()
    ctx = _step_ctx()
    env_error = ExecutionEnvironmentError("execution mode 'container' requires repo_root")
    with (
        patch(f"{_WAVES}.resolve_dispatch_params", AsyncMock(side_effect=env_error)),
        patch(
            "modules.backend.agents.mission_control.mission_dispatch.handle_mission",
            handle_mission,
        ),
        patch("modules.backend.services.session.SessionService", MagicMock()),
        pytest.raises(RuntimeError, match="requires repo_root") as exc_info,
    ):
        await svc._execute_step(_run(), _STEP, str(uuid.uuid4()), {}, ctx)

    assert exc_info.value.__cause__ is env_error
    handle_mission.assert_not_called()
    published = [c.args[1] for c in svc._event_bus.publish_to_mission.call_args_list]
    assert any(getattr(e, "level", None) == "error" for e in published)
    ctx.persistence.complete_execution.assert_awaited_once()
    call = ctx.persistence.complete_execution.call_args
    assert call.args == ("rec-1", ExecutionRecordStatus.FAILED.value)
    assert "requires repo_root" in call.kwargs["execution_outcome_json"]["error"]


async def test_workflow_step_record_close_failure_keeps_step_error():
    """A DB failure while closing the step record never masks the step's RuntimeError."""
    svc = _waves_service()
    ctx = _step_ctx()
    ctx.persistence.complete_execution = AsyncMock(side_effect=SQLAlchemyError("session dead"))
    env_error = ExecutionEnvironmentError("execution mode 'container' requires repo_root")
    with (
        patch(f"{_WAVES}.resolve_dispatch_params", AsyncMock(side_effect=env_error)),
        patch("modules.backend.services.session.SessionService", MagicMock()),
        pytest.raises(RuntimeError, match="requires repo_root"),
    ):
        await svc._execute_step(_run(), _STEP, str(uuid.uuid4()), {}, ctx)


# =============================================================================
# Missions
# =============================================================================


async def test_mission_worktree_rejected():
    service = MissionService(MagicMock())
    with pytest.raises(ValidationError, match="no worktree backend is registered"):
        await service.create_mission(
            name="m",
            description="d",
            owner_id="u",
            gate_mode="autonomous",
            execution_environment="worktree",
        )
    with pytest.raises(ValidationError, match="no worktree backend is registered"):
        await service.update_mission("mission-1", execution_environment="worktree")


# =============================================================================
# No host shell
# =============================================================================


async def test_run_command_without_handle_raises():
    with pytest.raises(ExecutionEnvironmentError):
        await run_command("echo hi", environment_handle=None)


async def test_run_tests_without_handle_raises():
    with pytest.raises(ExecutionEnvironmentError):
        await run_tests(None)


async def test_run_tests_uses_argv_constant_and_config_timeout():
    handle = _handle()
    result = CommandResult(exit_code=0, stdout="1 passed", stderr="")
    with patch.object(run_tests_tool, "run_in_environment", AsyncMock(return_value=result)) as m:
        out = await run_tests(handle)
    m.assert_awaited_once_with(
        handle,
        RUN_TESTS_ARGV,
        timeout_seconds=get_app_config().executions.run_tests_timeout_seconds,
    )
    assert RUN_TESTS_ARGV == ["python", "-m", "pytest", "tests/unit", "-v", "--tb=short"]
    assert run_tests_tool.TOOL_DEF["deps"] == ["environment_handle"]
    assert out == {"passed": True, "exit_code": 0, "output": "1 passed"}


async def test_security_tool_runner_without_handle_raises():
    with pytest.raises(ExecutionEnvironmentError):
        await _run_tool_subprocess(["semgrep", "--version"], timeout=5, environment_handle=None)


async def test_local_mode_handle_cannot_execute():
    local = EnvironmentHandle(environment_id="local-x", mode="local", working_dir=Path("/"))
    with pytest.raises(ExecutionEnvironmentError, match="no execution backend"):
        await ExecutionEnvironmentService().execute(local, ["true"])
    with (
        patch.object(execution_environment, "_command_service", None),
        patch("modules.backend.services.container_backend.ContainerBackend", MagicMock()),
        pytest.raises(ExecutionEnvironmentError, match="no execution backend"),
    ):
        await run_in_environment(local, ["true"], timeout_seconds=5)
    with pytest.raises(ExecutionEnvironmentError, match="no execution backend"):
        await ExecutionEnvironmentService().get_or_create_for_mission("m", mode="local")


async def test_run_in_environment_none_handle_raises():
    with pytest.raises(ExecutionEnvironmentError):
        await run_in_environment(None, ["true"], timeout_seconds=5)


# =============================================================================
# CLI engines
# =============================================================================


@pytest.mark.parametrize("engine", ["codex", "copilot"])
def test_codex_and_copilot_engines_rejected_by_schema(engine: str):
    with pytest.raises(PydanticValidationError, match="3.8.7"):
        AgentConfigSchema(
            agent_name="test.dummy.agent",
            agent_type="vertical",
            description="A test agent",
            model="anthropic:claude-haiku-4-5-20251001",
            engine=engine,
        )


async def test_chat_cli_engine_without_handle_raises():
    from modules.backend.agents.mission_control import chat_cli_handler

    session_service = MagicMock()
    session_service.get_messages = AsyncMock(return_value=([MagicMock()], 1))
    agent_config = MagicMock()
    agent_config.engine = "claude_code"
    agent_config.effort = None
    agent_config.scope.read = []
    agent_config.scope.write = []
    with (
        patch.object(chat_cli_handler, "load_agent_system_prompt", return_value="sp"),
        pytest.raises(ExecutionEnvironmentError, match="needs an environment handle"),
    ):
        async for _ in chat_cli_handler.handle_cli_chat(
            str(uuid.uuid4()),
            "hello",
            agent_name="test.cli.agent",
            agent_config=agent_config,
            mission_id="mission-1",
            session_service=session_service,
            event_bus=AsyncMock(),
        ):
            pass


async def test_claude_code_with_write_scope_raises_even_with_handle():
    with pytest.raises(ExecutionEnvironmentError, match="cannot write"):
        await execute_claude_code(
            "a",
            "do",
            {},
            system_prompt="sp",
            environment_handle=_handle(),
            scope_write=["src/"],
        )


@pytest.mark.parametrize("handle", [None, _handle(host_working_dir=None)])
async def test_claude_code_without_handle_raises(handle):
    with pytest.raises(ExecutionEnvironmentError, match="needs an environment handle"):
        await execute_claude_code("a", "do", {}, system_prompt="sp", environment_handle=handle)


async def test_claude_code_passes_read_tools_and_empty_setting_sources(monkeypatch):
    captured: dict = {}

    class _Options:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    async def _query(prompt, options):
        return
        yield  # pragma: no cover - makes this an async generator

    sdk = types.ModuleType("claude_agent_sdk")
    sdk.ClaudeAgentOptions = _Options
    sdk.query = _query
    sdk_types = types.ModuleType("claude_agent_sdk.types")
    for name in ("AssistantMessage", "ResultMessage", "TextBlock", "ToolResultBlock"):
        setattr(sdk_types, name, type(name, (), {}))
    sdk_types.ToolUseBlock = type("ToolUseBlock", (), {})
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", sdk_types)

    handle = _handle()
    await execute_claude_code("a", "do", {}, system_prompt="sp", environment_handle=handle)

    assert captured["cwd"] == str(handle.host_working_dir)
    assert captured["tools"] == ["Read", "Grep", "Glob"] == CLAUDE_CODE_READ_TOOLS
    assert captured["allowed_tools"] == ["Read", "Grep", "Glob"]
    assert captured["setting_sources"] == []


def test_installed_claude_agent_sdk_accepts_boundary_options():
    """The installed SDK must accept the options execute_claude_code relies on.

    Releases before 0.1.19 have no ClaudeAgentOptions.tools; on those every
    claude_code call would fail with a TypeError instead of running read-only.
    """
    sdk = pytest.importorskip("claude_agent_sdk")
    names = {f.name for f in dataclasses.fields(sdk.ClaudeAgentOptions)}
    used = {"system_prompt", "cwd", "max_turns", "tools", "allowed_tools", "setting_sources"}
    assert used <= names


def test_execution_environment_error_maps_to_503():
    assert EXCEPTION_STATUS_MAP[ExecutionEnvironmentError] == 503


# =============================================================================
# Write guard
# =============================================================================


class _PastGuard(Exception):
    """Raised by the first emit after the guard: proves execution got past it."""


def _write_capable_config() -> MagicMock:
    config = MagicMock()
    config.engine = "pydantic_ai"
    config.invocation.tier = "user"
    config.scope.read = ["@workspace/"]
    config.scope.write = ["@workspace/evidence/"]
    return config


async def _execute_with(handle, deps):
    with (
        patch(f"{_EXECUTOR}.get_registry") as registry,
        patch(f"{_EXECUTOR}._import_agent_module"),
        patch(f"{_EXECUTOR}._build_model"),
        patch(f"{_EXECUTOR}.build_model_settings"),
        patch(f"{_EXECUTOR}._build_agent_deps", return_value=deps),
        patch(f"{_EXECUTOR}._emit", AsyncMock(side_effect=_PastGuard)),
    ):
        registry.return_value.get.return_value = _write_capable_config()
        execute_agent = _make_agent_executor(
            AsyncMock(), session_id="s", mission_id="m", environment_handle=handle
        )
        await execute_agent("security.webapp.scanner", "scan", {}, UsageLimits(request_limit=1))


@pytest.mark.parametrize("handle", [None, _handle(host_working_dir=None)])
async def test_write_guard_blocks_without_handle(handle):
    with pytest.raises(ExecutionEnvironmentError, match="needs an isolated workspace"):
        await _execute_with(handle, MagicMock(spec=[]))


async def test_write_guard_allows_worktree_under_platform_repo():
    worktree = find_project_root() / "var" / "worktrees" / "x" / "workspace"
    deps = MagicMock(spec=[])
    with pytest.raises(_PastGuard):
        await _execute_with(_handle(host_working_dir=worktree), deps)
    assert deps.project_root == worktree
