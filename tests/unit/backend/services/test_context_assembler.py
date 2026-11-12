"""Tests for ContextAssembler (Plan 88, 88.3.5).

Tests use mocked dependencies (MissionContextManager, HistoryQueryService,
MissionLearningRepository, RunMemoryService) since the assembler is pure
orchestration over them. Config is patched where a test needs a budget.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.backend.core.utils import estimate_tokens
from modules.backend.schemas.run_memory import (
    ContextDelta,
    ContextDeltaEntry,
    PreviousRunDigest,
    RunContextPacket,
)
from modules.backend.services.context_assembler import _CODING_TAGS, ContextAssembler

_MOD = "modules.backend.services.context_assembler"
_DEFAULT_ORDER = ["previous_run_digest", "context_delta", "code_map", "learnings", "history"]


def _patch_config(
    *,
    budget: int = 50_000,
    history_reserve: int = 1500,
    learnings_reserve: int = 1500,
    max_entries: int = 5,
    order: list[str] | None = None,
    digest_chars: int = 4000,
    delta_tokens: int = 2000,
):
    """Patch both config getters the assembler reads."""
    mc = SimpleNamespace(
        dispatch=SimpleNamespace(
            context_token_budget=budget, history_reserve_tokens=history_reserve
        )
    )
    app = SimpleNamespace(
        missions=SimpleNamespace(
            context_packet=SimpleNamespace(
                previous_digest_max_chars=digest_chars,
                context_delta_max_tokens=delta_tokens,
                assembly_order=order or _DEFAULT_ORDER,
            ),
            knowledge=SimpleNamespace(
                learnings=SimpleNamespace(
                    context_assembler_reserve_tokens=learnings_reserve,
                    context_assembler_max_entries=max_entries,
                )
            ),
        )
    )
    return (
        patch(f"{_MOD}.get_mission_control_config", return_value=mc),
        patch(f"{_MOD}.get_app_config", return_value=app),
    )


def _learning(idx: int, *, chars: int = 100, confidence: float = 0.5) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"l{idx}",
        kind="failure_pattern",
        title=f"learning {idx}",
        recommendation="r" * chars,
        confidence=confidence,
        domain_tags=["api"],
    )


def _run_packet() -> RunContextPacket:
    return RunContextPacket(
        mission_run_id="run-2",
        is_first_run=False,
        previous_run_digest=PreviousRunDigest(
            mission_run_id="run-1",
            sequence=1,
            status="succeeded",
            generator="deterministic",
            summary="Previous run summary",
            open_items=[{"text": "open", "source_task_id": None}],
            metrics={},
        ),
        context_delta=ContextDelta(
            from_version=1,
            to_version=2,
            entries=[
                ContextDeltaEntry(
                    version=2, change_type="add", path="a.b", value_excerpt='"x"', reason="r"
                )
            ],
            omitted_count=0,
        ),
    )


@pytest.fixture
def mock_context_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.get_context = AsyncMock(
        return_value={
            "identity": {"name": "test-project", "tech_stack": ["python"]},
            "version": 1,
        }
    )
    return mgr


@pytest.fixture
def mock_history_service() -> MagicMock:
    svc = MagicMock()
    svc.get_recent_failures = AsyncMock(return_value=[])
    svc.get_recent_task_executions = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def mock_learning_repo() -> MagicMock:
    repo = MagicMock()
    repo.list_by_mission = AsyncMock(return_value=[])
    repo.list_platform_promoted = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_run_memory() -> MagicMock:
    svc = MagicMock()
    svc.build_context_packet = AsyncMock(return_value=_run_packet())
    return svc


@pytest.fixture
def make_assembler(mock_context_manager, mock_history_service, mock_learning_repo, mock_run_memory):
    def _make(code_map_loader=None) -> ContextAssembler:
        return ContextAssembler(
            mock_context_manager,
            mock_history_service,
            learning_repo=mock_learning_repo,
            run_memory=mock_run_memory,
            code_map_loader=code_map_loader,
        )

    return _make


@pytest.fixture
def assembler(make_assembler) -> ContextAssembler:
    return make_assembler()


async def _build(
    assembler: ContextAssembler,
    *,
    task: dict | None = None,
    inputs: dict | None = None,
    domain_tags: list[str] | None = None,
    mission_run_id: str | None = None,
) -> dict:
    return await assembler.build(
        mission_id="proj-1",
        task_definition=task or {"task_id": "t1"},
        resolved_inputs=inputs or {},
        domain_tags=domain_tags,
        mission_run_id=mission_run_id,
    )


class TestEstimateTokens:
    def test_string_input(self):
        assert estimate_tokens("hello world") == len("hello world") // 4

    def test_dict_input(self):
        data = {"key": "value"}
        tokens = estimate_tokens(data)
        assert tokens > 0

    def test_empty_dict(self):
        assert estimate_tokens({}) == len("{}") // 4


class TestBuild:
    @pytest.mark.asyncio
    async def test_includes_pcd_and_task(self, assembler, mock_context_manager):
        """The fixed head (MCD, task, inputs) is always present."""
        packet = await _build(
            assembler, task={"task_id": "t1", "agent": "analyzer"}, inputs={"query": "test"}
        )
        assert packet["project_context"]["identity"]["name"] == "test-project"
        assert packet["task"]["task_id"] == "t1"
        assert packet["inputs"]["query"] == "test"
        mock_context_manager.get_context.assert_called_once_with("proj-1")

    @pytest.mark.asyncio
    async def test_no_history_without_domain_tags(self, assembler, mock_history_service):
        packet = await _build(assembler)
        assert "history" not in packet
        mock_history_service.get_recent_failures.assert_not_called()

    @pytest.mark.asyncio
    async def test_history_included_with_domain_tags(self, assembler, mock_history_service):
        mock_history_service.get_recent_failures = AsyncMock(
            return_value=[{"task_id": "old-t1", "failure_reason": "timeout"}]
        )
        packet = await _build(assembler, domain_tags=["auth"])
        assert "recent_failures" in packet["history"]
        mock_history_service.get_recent_failures.assert_called_once()

    @pytest.mark.asyncio
    async def test_history_executions_included(self, assembler, mock_history_service):
        mock_history_service.get_recent_task_executions = AsyncMock(
            return_value=[{"task_id": "prev-1", "agent_name": "analyzer", "status": "completed"}]
        )
        packet = await _build(assembler, domain_tags=["api"])
        assert "recent_executions" in packet["history"]

    @pytest.mark.asyncio
    async def test_inputs_summarized_when_over_budget(self, assembler):
        """Large non-scalar inputs are summarized when they exceed the budget."""
        p1, p2 = _patch_config(budget=500)
        with p1, p2:
            packet = await _build(assembler, inputs={"data": list(range(10_000))})
        assert "<list" in str(packet["inputs"]["data"])

    @pytest.mark.asyncio
    async def test_optional_layers_skipped_when_budget_exhausted(
        self, assembler, mock_history_service, mock_learning_repo
    ):
        """The fixed head is kept even when it alone exceeds the budget; no layer is added."""
        p1, p2 = _patch_config(budget=50)
        with p1, p2:
            packet = await _build(
                assembler,
                task={"task_id": "t1", "extra": "x" * 2000},
                domain_tags=["api"],
                mission_run_id="run-2",
            )
        assert set(packet) == {"project_context", "task", "inputs"}
        mock_history_service.get_recent_failures.assert_not_called()
        mock_learning_repo.list_by_mission.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_fallback_when_config_missing(self, assembler):
        with patch(f"{_MOD}.get_mission_control_config", side_effect=KeyError("dispatch")):
            with pytest.raises(KeyError):
                await _build(assembler)


class TestLearningsLayer:
    @pytest.mark.asyncio
    async def test_learnings_respect_reserve_tokens(self, assembler, mock_learning_repo):
        """10 learnings of about 400 tokens each with a reserve of 1500 give 3 entries."""
        mock_learning_repo.list_by_mission = AsyncMock(
            return_value=[_learning(i, chars=1550) for i in range(10)]
        )
        assert 380 <= estimate_tokens([_learning_dict(_learning(0, chars=1550))]) <= 420
        p1, p2 = _patch_config(learnings_reserve=1500, max_entries=10)
        with p1, p2:
            packet = await _build(assembler, domain_tags=["analysis"])
        assert len(packet["learnings"]) == 3

    @pytest.mark.asyncio
    async def test_learnings_capped_at_max_entries(self, assembler, mock_learning_repo):
        mock_learning_repo.list_by_mission = AsyncMock(
            return_value=[_learning(i) for i in range(10)]
        )
        p1, p2 = _patch_config(max_entries=2)
        with p1, p2:
            packet = await _build(assembler, domain_tags=["analysis"])
        assert len(packet["learnings"]) == 2

    @pytest.mark.asyncio
    async def test_learnings_merge_dedup_sorted_by_confidence(self, assembler, mock_learning_repo):
        shared = _learning(1, confidence=0.6)
        mock_learning_repo.list_by_mission = AsyncMock(
            return_value=[shared, _learning(2, confidence=0.4)]
        )
        mock_learning_repo.list_platform_promoted = AsyncMock(
            return_value=[shared, _learning(3, confidence=0.9)]
        )
        packet = await _build(assembler, domain_tags=["api"])
        assert [e["title"] for e in packet["learnings"]] == [
            "learning 3",
            "learning 1",
            "learning 2",
        ]

    @pytest.mark.asyncio
    async def test_learnings_without_domain_tags_uses_mission_learnings(
        self, assembler, mock_learning_repo
    ):
        """Platform-promoted learnings are not queried without domain tags."""
        mock_learning_repo.list_by_mission = AsyncMock(return_value=[_learning(1)])
        packet = await _build(assembler)
        assert [e["title"] for e in packet["learnings"]] == ["learning 1"]
        mock_learning_repo.list_by_mission.assert_awaited_once_with(
            "proj-1", domain_tags=None, limit=5
        )
        mock_learning_repo.list_platform_promoted.assert_not_called()

    @pytest.mark.asyncio
    async def test_repository_errors_propagate(self, assembler, mock_learning_repo):
        mock_learning_repo.list_by_mission = AsyncMock(side_effect=RuntimeError("db down"))
        with pytest.raises(RuntimeError):
            await _build(assembler, domain_tags=["api"])


class TestRunLayers:
    @pytest.mark.asyncio
    async def test_run_layers_included_with_run_id(self, assembler):
        packet = await _build(assembler, mission_run_id="run-2")
        assert packet["previous_run_digest"]["summary"] == "Previous run summary"
        assert packet["context_delta"]["entries"][0]["path"] == "a.b"

    @pytest.mark.asyncio
    async def test_run_layers_skipped_without_run_id(self, assembler, mock_run_memory):
        packet = await _build(assembler)
        assert "previous_run_digest" not in packet
        assert "context_delta" not in packet
        mock_run_memory.build_context_packet.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_layers_skipped_on_first_run(self, assembler, mock_run_memory):
        mock_run_memory.build_context_packet = AsyncMock(
            return_value=RunContextPacket(
                mission_run_id="run-1",
                is_first_run=True,
                previous_run_digest=None,
                context_delta=None,
            )
        )
        packet = await _build(assembler, mission_run_id="run-1")
        assert "previous_run_digest" not in packet
        assert "context_delta" not in packet

    @pytest.mark.asyncio
    async def test_run_layers_built_once_per_run(self, assembler, mock_run_memory):
        await _build(assembler, mission_run_id="run-2")
        await _build(assembler, mission_run_id="run-2")
        mock_run_memory.build_context_packet.assert_awaited_once_with("run-2")

    @pytest.mark.asyncio
    async def test_digest_over_cap_omitted_whole(self, assembler):
        p1, p2 = _patch_config(digest_chars=200)
        packet_obj = _run_packet()
        packet_obj.previous_run_digest.summary = "s" * 1000
        assembler._run_memory.build_context_packet = AsyncMock(return_value=packet_obj)
        with p1, p2:
            packet = await _build(assembler, mission_run_id="run-2")
        assert "previous_run_digest" not in packet
        assert "context_delta" in packet


class TestAssemblyOrder:
    @pytest.mark.asyncio
    async def test_assembly_order_followed(self, make_assembler, mock_history_service):
        """With history before code_map, history is included before the code map is sized."""
        history = [{"task_id": f"f{i}", "failure_reason": "x" * 200} for i in range(3)]
        mock_history_service.get_recent_failures = AsyncMock(return_value=history)
        loader = MagicMock()
        loader.get_markdown.return_value = "m" * 40_000  # 10,000 tokens
        loader.get_json.return_value = {"modules": []}
        sized: list[int] = []

        def _render(code_map, max_tokens):
            sized.append(max_tokens)
            return "rendered"

        order = ["history", "code_map", "previous_run_digest", "context_delta", "learnings"]
        p1, p2 = _patch_config(budget=8_000, order=order)
        with (
            p1,
            p2,
            patch(
                "modules.backend.services.code_map.assembler.render_for_agent", side_effect=_render
            ),
        ):
            assembler = make_assembler(code_map_loader=loader)
            packet = await _build(assembler, domain_tags=["code"], mission_run_id="run-2")

        assert list(packet)[3:5] == ["history", "code_map"]
        head = estimate_tokens(packet["project_context"]) + estimate_tokens(packet["task"])
        head += estimate_tokens(packet["inputs"])
        later_caps = 4000 // 4 + 2000 + 1500
        expected = 8_000 - head - estimate_tokens(packet["history"]) - later_caps
        assert sized == [expected]

    @pytest.mark.asyncio
    async def test_code_map_reserves_later_layer_caps(self, make_assembler):
        """The code map is sized to the remaining budget minus every later layer's cap."""
        loader = MagicMock()
        loader.get_markdown.return_value = "m" * 40_000
        loader.get_json.return_value = {"modules": []}
        sized: list[int] = []

        def _render(code_map, max_tokens):
            sized.append(max_tokens)
            return "rendered"

        p1, p2 = _patch_config(budget=10_000, history_reserve=700, learnings_reserve=900)
        with (
            p1,
            p2,
            patch(
                "modules.backend.services.code_map.assembler.render_for_agent", side_effect=_render
            ),
        ):
            assembler = make_assembler(code_map_loader=loader)
            packet = await _build(assembler, domain_tags=["code"])

        head = sum(estimate_tokens(packet[k]) for k in ("project_context", "task", "inputs"))
        assert sized == [10_000 - head - 900 - 700]
        assert packet["code_map"] == "rendered"


def _learning_dict(learning: SimpleNamespace) -> dict:
    return {
        "kind": learning.kind,
        "title": learning.title,
        "recommendation": learning.recommendation,
        "confidence": learning.confidence,
        "domain_tags": learning.domain_tags,
    }


class TestIsCodingTask:
    """Test the domain_tags → coding task classification."""

    def test_none_tags_returns_true(self):
        assert ContextAssembler._is_coding_task(None) is True

    def test_empty_tags_returns_true(self):
        assert ContextAssembler._is_coding_task([]) is True

    def test_coding_tag_returns_true(self):
        for tag in _CODING_TAGS:
            assert ContextAssembler._is_coding_task([tag]) is True

    def test_non_coding_tag_returns_false(self):
        assert ContextAssembler._is_coding_task(["analysis"]) is False
        assert ContextAssembler._is_coding_task(["health"]) is False

    def test_mixed_tags_with_coding(self):
        assert ContextAssembler._is_coding_task(["auth", "bugfix"]) is True

    def test_mixed_tags_without_coding(self):
        assert ContextAssembler._is_coding_task(["auth", "monitoring"]) is False


class TestCodeMapLayer:
    """Test Layer 3 (Code Map) integration in ContextAssembler."""

    @pytest.mark.asyncio
    async def test_no_code_map_without_loader(
        self,
        make_assembler,
    ):
        """No code_map in packet when no loader is injected."""
        packet = await _build(make_assembler(), domain_tags=["code"])
        assert "code_map" not in packet

    @pytest.mark.asyncio
    async def test_code_map_included_for_coding_task(
        self,
        make_assembler,
    ):
        """Code Map markdown is included for coding tasks."""
        mock_loader = MagicMock()
        mock_loader.get_markdown.return_value = "# Code Map\n\n- module_a\n- module_b"

        assembler = make_assembler(code_map_loader=mock_loader)
        packet = await _build(assembler, domain_tags=["code"])
        assert "code_map" in packet
        assert "# Code Map" in packet["code_map"]
        mock_loader.get_markdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_code_map_skipped_for_non_coding_task(
        self,
        make_assembler,
    ):
        """Code Map is not loaded for non-coding domain tags."""
        mock_loader = MagicMock()
        mock_loader.get_markdown.return_value = "# Code Map"

        assembler = make_assembler(code_map_loader=mock_loader)
        packet = await _build(assembler, domain_tags=["analysis"])
        assert "code_map" not in packet
        mock_loader.get_markdown.assert_not_called()

    @pytest.mark.asyncio
    async def test_code_map_included_when_no_domain_tags(
        self,
        make_assembler,
    ):
        """Conservative: Code Map is included when domain_tags is None."""
        mock_loader = MagicMock()
        mock_loader.get_markdown.return_value = "# Code Map\n\nfull content"

        assembler = make_assembler(code_map_loader=mock_loader)
        packet = await _build(assembler)
        assert "code_map" in packet

    @pytest.mark.asyncio
    async def test_code_map_none_when_loader_returns_none(
        self,
        make_assembler,
    ):
        """No code_map key when loader returns None (file missing)."""
        mock_loader = MagicMock()
        mock_loader.get_markdown.return_value = None

        assembler = make_assembler(code_map_loader=mock_loader)
        packet = await _build(assembler, domain_tags=["code"])
        assert "code_map" not in packet
