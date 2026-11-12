"""
Pydantic schemas for config/settings/missions.yaml.

Split from config_schema.py to keep both modules under the 1000-line limit.
MissionsSchema and every schema nested under it live here.
"""

from typing import Literal

from pydantic import Field, model_validator

from modules.backend.core.config_schema import _StrictBase


class KnowledgeEmbeddingSchema(_StrictBase):
    """Embedding provider configuration."""

    provider: str = "openai"  # openai | voyage | local
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    version: int = 1  # bumps trigger backfill
    backfill_batch_size: int = 50
    default_search_mode: str = "hybrid"
    fail_open: bool = True


class KnowledgeLearningsSchema(_StrictBase):
    """Learnings extraction and promotion configuration."""

    min_occurrence_for_extraction: int = 2
    promotion_confidence_threshold: float = 0.7
    promotion_min_missions: int = 2
    context_assembler_reserve_tokens: int = 1500
    context_assembler_max_entries: int = 5
    dedup_similarity_threshold: float = 0.92
    evidence_render_limit: int = 20
    extraction_window_days: int = Field(..., ge=1)


class KnowledgeIntentSchema(_StrictBase):
    """Intent capture configuration."""

    auto_capture: bool = True
    summary_max_chars: int = 160
    dedup_similarity_threshold: float = 0.95


class KnowledgeSessionMemorySchema(_StrictBase):
    """Session rolling summary configuration."""

    compression_threshold_messages: int = 50
    summary_max_tokens: int = 8000


class KnowledgeOfficerSchema(_StrictBase):
    """Knowledge Officer agent configuration."""

    budget_usd_per_run: float = 0.10
    model: str = "haiku"


class KnowledgeSchema(_StrictBase):
    """Knowledge platform configuration (Plan 57)."""

    enabled: bool = True
    embedding: KnowledgeEmbeddingSchema = Field(default_factory=KnowledgeEmbeddingSchema)
    learnings: KnowledgeLearningsSchema = Field(...)
    intent: KnowledgeIntentSchema = Field(default_factory=KnowledgeIntentSchema)
    session_memory: KnowledgeSessionMemorySchema = Field(
        default_factory=KnowledgeSessionMemorySchema
    )
    officer: KnowledgeOfficerSchema = Field(default_factory=KnowledgeOfficerSchema)


class RecurrenceSchema(_StrictBase):
    """Recurring mission schedule limits (Plan 88)."""

    enabled: bool = Field(...)
    default_catch_up_window_seconds: int = Field(..., ge=60)
    max_catch_up_window_seconds: int = Field(..., ge=60)
    min_interval_seconds: int = Field(..., ge=60)
    max_schedules_per_mission: int = Field(..., ge=1)
    objective_template_max_chars: int = Field(..., ge=100)

    @model_validator(mode="after")
    def _default_window_within_max(self) -> "RecurrenceSchema":
        if self.default_catch_up_window_seconds > self.max_catch_up_window_seconds:
            raise ValueError(
                "missions.recurrence.default_catch_up_window_seconds must not exceed "
                "max_catch_up_window_seconds"
            )
        return self


_PACKET_LAYERS = ("previous_run_digest", "context_delta", "code_map", "learnings", "history")
_MCD_RESTRICTED_ROOTS = frozenset({"version", "last_updated", "last_updated_by"})


class DigestSchema(_StrictBase):
    """End-of-run digest generation (Plan 88 Phase 3)."""

    agent_name: str = Field(..., min_length=1)
    summary_max_chars: int = Field(..., ge=200)
    max_outcomes: int = Field(..., ge=1)
    headline_max_chars: int = Field(..., ge=50)
    task_excerpt_max_chars: int = Field(..., ge=1)
    agent_output_retries: int = Field(..., ge=0)


class ContextPacketSchema(_StrictBase):
    """Run-start context packet assembly (Plan 88 Phase 3)."""

    previous_digest_max_chars: int = Field(..., ge=200)
    context_delta_max_changes: int = Field(..., ge=1)
    context_delta_max_tokens: int = Field(..., ge=1)
    context_delta_value_max_chars: int = Field(..., ge=50)
    assembly_order: list[
        Literal["previous_run_digest", "context_delta", "code_map", "learnings", "history"]
    ] = Field(...)

    @model_validator(mode="after")
    def _order_is_permutation(self) -> "ContextPacketSchema":
        if sorted(self.assembly_order) != sorted(_PACKET_LAYERS):
            raise ValueError(
                "context_packet.assembly_order must list each of the 5 layers exactly once"
            )
        return self


class CompactionSchema(_StrictBase):
    """Deterministic MCD compaction (Plan 88 Phase 3)."""

    decisions_max_age_days: int = Field(..., ge=1)
    keep_recent_milestones: int = Field(..., ge=1)
    protected_roots: list[str] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _no_restricted_roots(self) -> "CompactionSchema":
        listed = _MCD_RESTRICTED_ROOTS.intersection(self.protected_roots)
        if listed:
            raise ValueError(
                f"compaction.protected_roots must not list {sorted(listed)}; "
                "they are always protected"
            )
        return self


class MissionsSchema(_StrictBase):
    """Mission system configuration."""

    default_budget_ceiling_usd: float | None = None
    max_missions_per_owner: int = 50
    pcd_max_size_bytes: int = 20_480  # 20KB
    pcd_target_size_bytes: int = 15_360  # 15KB
    pcd_prune_threshold_pct: int = Field(..., ge=1, le=100)
    pcd_alert_threshold_pct: int = 90
    history_summarize_after_days: int = 30
    enable_context_assembly: bool = True
    knowledge: KnowledgeSchema = Field(...)
    recurrence: RecurrenceSchema = Field(...)
    digest: DigestSchema = Field(...)
    context_packet: ContextPacketSchema = Field(...)
    compaction: CompactionSchema = Field(...)

    @model_validator(mode="after")
    def _target_below_max(self) -> "MissionsSchema":
        if self.pcd_target_size_bytes >= self.pcd_max_size_bytes:
            raise ValueError("missions.pcd_target_size_bytes must be below pcd_max_size_bytes")
        return self
