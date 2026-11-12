"""Digest agent (Plan 88, 88.3.6): output validation, cost, failure mapping, catalog YAML."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, RetryPromptPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from modules.backend.core.config import find_project_root, get_app_config
from modules.backend.core.exceptions import ExternalServiceError
from modules.backend.schemas.agent_config import AgentConfigSchema
from modules.backend.schemas.run_memory import DigestNarrative

AGENT_MODULE = "modules.backend.agents.system.digest.agent"
YAML_PATH = find_project_root() / "config" / "agents" / "system" / "digest" / "agent.yaml"

TASK_EXCERPTS = [
    {"task_id": "t-1", "agent": "research.agent", "status": "completed", "excerpt": "found X"},
    {"task_id": "t-2", "agent": "research.agent", "status": "failed", "excerpt": "timeout"},
]
VALID = {
    "summary": "Found X. Task t-2 timed out and is still open.",
    "open_items": [
        {"text": "Rerun the t-2 search with a narrower query.", "source_task_id": "t-2"}
    ],
    "headlines": [
        {"task_id": "t-1", "headline": "Found X"},
        {"task_id": "t-2", "headline": "Timed out"},
    ],
}


def _catalog_config() -> AgentConfigSchema:
    return AgentConfigSchema(**yaml.safe_load(Path(YAML_PATH).read_text(encoding="utf-8")))


@pytest.fixture
def recorder(monkeypatch) -> AsyncMock:
    """Registry backed by the repository YAML (no DB); record_llm_call captured."""
    registry = SimpleNamespace(get=lambda name: _catalog_config())
    monkeypatch.setattr(f"{AGENT_MODULE}.get_registry", lambda: registry)
    monkeypatch.setattr(
        "modules.backend.agents.mission_control.registry.get_registry", lambda: registry
    )
    record = AsyncMock()
    monkeypatch.setattr(f"{AGENT_MODULE}.record_llm_call", record)
    return record


def _use_model(monkeypatch, model) -> None:
    monkeypatch.setattr(f"{AGENT_MODULE}._build_model", lambda _cfg: model)


def _scripted(*outputs: dict) -> tuple[FunctionModel, list[list[ModelMessage]]]:
    """A FunctionModel returning ``outputs`` in turn (the last repeats); records each call."""
    calls: list[list[ModelMessage]] = []

    async def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(messages)
        args = outputs[min(len(calls), len(outputs)) - 1]
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)])

    return FunctionModel(_fn), calls


def _retry_text(messages: list[ModelMessage]) -> str:
    return " ".join(
        str(part.content)
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, RetryPromptPart)
    )


async def _generate():
    from modules.backend.agents.system.digest.agent import generate_digest_narrative

    return await generate_digest_narrative(
        draft={"status": "succeeded", "outcomes": []},
        objective="Track X",
        task_excerpts=TASK_EXCERPTS,
        mission_id="m-1",
        mission_run_id="run-1",
        session_id="s-1",
    )


async def test_output_validator_rejects_unknown_task_id(monkeypatch, recorder):
    bad = {**VALID, "headlines": [{"task_id": "t-999", "headline": "Invented"}]}
    model, calls = _scripted(bad, VALID)
    _use_model(monkeypatch, model)

    output, _ = await _generate()

    assert len(calls) == 2
    assert "unknown task id 't-999'" in _retry_text(calls[1])
    assert {h.task_id for h in output.headlines} == {"t-1", "t-2"}


async def test_output_validator_rejects_unknown_open_item_source(monkeypatch, recorder):
    bad = {**VALID, "open_items": [{"text": "Do Y.", "source_task_id": "t-404"}]}
    model, calls = _scripted(bad, VALID)
    _use_model(monkeypatch, model)

    await _generate()

    assert "unknown task id 't-404'" in _retry_text(calls[1])


async def test_output_validator_rejects_long_summary(monkeypatch, recorder):
    limit = get_app_config().missions.digest.summary_max_chars
    model, calls = _scripted({**VALID, "summary": "x" * (limit + 1)}, VALID)
    _use_model(monkeypatch, model)

    output, _ = await _generate()

    assert f"the limit is {limit}" in _retry_text(calls[1])
    assert len(output.summary) <= limit


async def test_output_validator_rejects_long_headline(monkeypatch, recorder):
    limit = get_app_config().missions.digest.headline_max_chars
    long_headline = {**VALID, "headlines": [{"task_id": "t-1", "headline": "h" * (limit + 1)}]}
    model, calls = _scripted(long_headline, VALID)
    _use_model(monkeypatch, model)

    await _generate()

    assert f"the limit is {limit}" in _retry_text(calls[1])


async def test_persistent_invalid_output_raises_external_service_error(monkeypatch, recorder):
    bad = {**VALID, "headlines": [{"task_id": "t-999", "headline": "Invented"}]}
    model, calls = _scripted(bad)
    _use_model(monkeypatch, model)

    with pytest.raises(ExternalServiceError, match="UnexpectedModelBehavior"):
        await _generate()

    assert len(calls) == get_app_config().missions.digest.agent_output_retries + 1
    # The billed attempts are still attributed to the run.
    recorder.assert_awaited_once()
    kwargs = recorder.await_args.kwargs
    assert kwargs["mission_run_id"] == "run-1"
    assert kwargs["usage"].requests == len(calls)
    assert kwargs["cost_usd"] > 0


async def test_records_llm_call_with_run_id(monkeypatch, recorder):
    _use_model(monkeypatch, TestModel(custom_output_args=VALID))

    output, cost = await _generate()

    assert isinstance(output, DigestNarrative)
    recorder.assert_awaited_once()
    kwargs = recorder.await_args.kwargs
    assert kwargs["mission_run_id"] == "run-1"
    assert kwargs["task_id"] is None
    assert kwargs["agent_name"] == "system.digest.agent"
    assert kwargs["mission_id"] == "m-1"
    assert kwargs["session_id"] == "s-1"
    assert kwargs["model"] == get_app_config().models.aliases["quick"]
    assert kwargs["cost_usd"] == cost
    assert cost > 0


async def test_model_failure_raises_external_service_error(monkeypatch, recorder):
    async def _fail(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(status_code=503, model_name="fixture", body="unavailable")

    _use_model(monkeypatch, FunctionModel(_fail))

    with pytest.raises(ExternalServiceError, match="ModelHTTPError"):
        await _generate()

    recorder.assert_not_awaited()


def test_catalog_yaml_valid():
    config = _catalog_config()

    assert config.agent_name == "system.digest.agent"
    assert config.agent_name == get_app_config().missions.digest.agent_name
    assert config.produces_artifact is False
    assert config.invocation.tier == "system"
    assert config.keywords == []
    assert config.chat_enabled is False


def test_prompt_file_exists():
    prompt = find_project_root() / "config" / "prompts" / "agents" / "system" / "digest"
    assert (prompt / "system.md").read_text(encoding="utf-8").strip()
