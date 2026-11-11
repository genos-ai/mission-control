"""
Configuration Schemas.

Pydantic models defining the expected structure of each YAML config file.
Used by AppConfig to validate configuration at load time. If a YAML file
has missing keys, wrong types, or unknown fields, a clear ValidationError
is raised at startup instead of a cryptic KeyError deep in application code.

Each top-level class corresponds to one file in config/settings/:
    ApplicationSchema  → application.yaml
    DatabaseSchema     → database.yaml
    LoggingSchema      → logging.yaml
    FeaturesSchema     → features.yaml
    SecuritySchema     → security.yaml
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictBase(BaseModel):
    """Base with extra='forbid' so unknown YAML keys are caught immediately."""

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# application.yaml
# =============================================================================


class ServerSchema(_StrictBase):
    host: str
    port: int


class CorsSchema(_StrictBase):
    origins: list[str]


class PaginationSchema(_StrictBase):
    default_limit: int
    max_limit: int


class TimeoutsSchema(_StrictBase):
    database: int
    external_api: int
    background: int
    agent_task: int  # wall-clock seconds for one agent task when the agent sets none
    tool_bridge: int = 300
    sse_keepalive: int = 15
    health_probe: int = 10  # seconds one dependency probe on the admin health page may take


class TelegramAppSchema(_StrictBase):
    webhook_path: str
    authorized_users: list[int]
    max_message_length: int = 4096


class CliSchema(_StrictBase):
    console_width: int = 160
    plan_poll_interval_seconds: float = 3.0
    plan_poll_max_iterations: int = 300


class ApplicationSchema(_StrictBase):
    name: str
    version: str
    description: str
    environment: str
    debug: bool
    api_prefix: str
    docs_enabled: bool
    server: ServerSchema
    cors: CorsSchema
    pagination: PaginationSchema
    timeouts: TimeoutsSchema
    telegram: TelegramAppSchema
    cli: CliSchema = Field(default_factory=CliSchema)


# =============================================================================
# database.yaml
# =============================================================================


class BrokerSchema(_StrictBase):
    queue_name: str
    result_expiry_seconds: int


class RedisSchema(_StrictBase):
    host: str
    port: int
    db: int
    broker: BrokerSchema


class DatabaseSchema(_StrictBase):
    host: str
    port: int
    name: str
    user: str
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    echo: bool
    echo_pool: bool
    redis: RedisSchema


# =============================================================================
# logging.yaml
# =============================================================================


class ConsoleHandlerSchema(_StrictBase):
    enabled: bool


class FileHandlerSchema(_StrictBase):
    """File handler uses TimedRotatingFileHandler (calendar / interval rotation)."""

    enabled: bool
    path: str
    rotation_when: Literal["S", "M", "H", "D", "midnight", "W0", "W1", "W2", "W3", "W4", "W5", "W6"]
    rotation_interval: int = Field(default=1, ge=1)
    backup_count: int = Field(ge=0)


class HandlersSchema(_StrictBase):
    console: ConsoleHandlerSchema
    file: FileHandlerSchema


class LoggingSchema(_StrictBase):
    level: str
    format: str
    handlers: HandlersSchema


# =============================================================================
# features.yaml
# =============================================================================


class FeaturesSchema(_StrictBase):
    auth_require_email_verification: bool
    auth_allow_api_key_creation: bool
    auth_rate_limit_enabled: bool
    auth_require_api_authentication: bool
    auth_allow_self_registration: bool = False
    legacy_admin_key_enabled: bool = False
    api_detailed_errors: bool
    api_request_logging: bool
    channel_telegram_enabled: bool
    channel_slack_enabled: bool
    channel_discord_enabled: bool
    channel_whatsapp_enabled: bool
    gateway_enabled: bool
    gateway_websocket_enabled: bool
    gateway_pairing_enabled: bool
    agent_coordinator_enabled: bool
    agent_streaming_enabled: bool
    mcp_enabled: bool
    a2a_enabled: bool
    security_startup_checks_enabled: bool
    security_headers_enabled: bool
    security_cors_enforce_production: bool
    experimental_background_tasks_enabled: bool
    experimental_mission_plan_daemon_enabled: bool = False


# =============================================================================
# security.yaml
# =============================================================================


class JwtSchema(_StrictBase):
    algorithm: str
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    audience: str


class SseSchema(_StrictBase):
    session_recheck_seconds: int = Field(gt=0)


class ApiRateLimitSchema(_StrictBase):
    requests_per_minute: int
    requests_per_hour: int


class ChannelRateLimitSchema(_StrictBase):
    messages_per_minute: int
    messages_per_hour: int


class RateLimitingSchema(_StrictBase):
    api: ApiRateLimitSchema
    telegram: ChannelRateLimitSchema
    websocket: ChannelRateLimitSchema


class RequestLimitsSchema(_StrictBase):
    max_body_size_bytes: int
    max_header_size_bytes: int


class SecurityHeadersSchema(_StrictBase):
    x_content_type_options: str
    x_frame_options: str
    referrer_policy: str
    hsts_enabled: bool
    hsts_max_age: int


class SecretsValidationSchema(_StrictBase):
    jwt_secret_min_length: int
    api_key_salt_min_length: int
    webhook_secret_min_length: int


class CorsEnforcementSchema(_StrictBase):
    enforce_in_production: bool
    allow_methods: list[str]
    allow_headers: list[str]


class RoleSchema(_StrictBase):
    level: int
    description: str


class TlsSchema(_StrictBase):
    use_os_trust_store: bool


class SecuritySchema(_StrictBase):
    jwt: JwtSchema
    sse: SseSchema
    rate_limiting: RateLimitingSchema
    request_limits: RequestLimitsSchema
    headers: SecurityHeadersSchema
    secrets_validation: SecretsValidationSchema
    roles: dict[str, RoleSchema] = Field(default_factory=dict)
    user_roles: dict[str, str] = Field(default_factory=dict)
    cors: CorsEnforcementSchema
    tls: TlsSchema


# =============================================================================
# gateway.yaml
# =============================================================================


class GatewayChannelSchema(_StrictBase):
    allowlist: list[int]


class GatewaySchema(_StrictBase):
    default_policy: str
    channels: dict[str, GatewayChannelSchema]


# =============================================================================
# events.yaml
# =============================================================================


class EventsStreamSchema(_StrictBase):
    maxlen: int = 10000
    consumer_group: str = "mc-workers"


class EventsSchema(_StrictBase):
    transport: str = "redis"
    streams: dict[str, EventsStreamSchema] = Field(default_factory=dict)
    consumer_timeout_ms: int = 5000
    dlq_enabled: bool = True
    dlq_prefix: str = "dlq"
    exclude_event_types: list[str] = Field(default_factory=list)


# =============================================================================
# sessions.yaml
# =============================================================================


class SessionsSchema(_StrictBase):
    default_ttl_hours: int = 24
    max_ttl_hours: int = 168
    default_cost_budget_usd: float = 50.00
    max_cost_budget_usd: float = 500.00
    cleanup_interval_minutes: int = 60
    budget_warning_threshold: float = 0.80


# =============================================================================
# missions.yaml
# =============================================================================


class ExecutionsSchema(_StrictBase):
    """Execution persistence and audit trail configuration."""

    max_thinking_trace_length: int = 50000
    max_task_output_size_bytes: int = 1_048_576  # 1MB
    retention_days: int = 0  # 0 = keep forever
    default_page_size: int = 20
    max_page_size: int = 100
    persist_thinking_trace: bool = True
    persist_verification_details: bool = True
    tier3_min_evaluation_score: float = Field(default=0.8, ge=0.0, le=1.0)
    run_tests_timeout_seconds: int = Field(..., ge=1)


# =============================================================================
# temporal.yaml
# =============================================================================


class RetrySchema(_StrictBase):
    initial_interval_seconds: int = Field(..., ge=1)
    backoff_coefficient: float = Field(..., ge=1.0)
    maximum_interval_seconds: int = Field(..., ge=1)
    maximum_attempts: int = Field(..., ge=1)


class ActivityPolicySchema(_StrictBase):
    start_to_close_seconds: int = Field(..., ge=1)
    heartbeat_timeout_seconds: int | None = Field(...)
    retry: RetrySchema


class MissionRunActivitiesSchema(_StrictBase):
    claim: ActivityPolicySchema
    persistence: ActivityPolicySchema
    plan_run: ActivityPolicySchema
    execute_task: ActivityPolicySchema
    evaluate_gate: ActivityPolicySchema
    evaluate_post_run: ActivityPolicySchema
    director_turn: ActivityPolicySchema
    write_digest: ActivityPolicySchema
    notify: ActivityPolicySchema


class MissionRunSchema(_StrictBase):
    continue_as_new_after_iterations: int = Field(..., ge=1)
    max_parallel_tasks: int = Field(..., ge=1)
    refine_wait_seconds: int = Field(..., ge=1)
    tick_execution_timeout_seconds: int = Field(..., ge=10)
    task_heartbeat_interval_seconds: int = Field(..., ge=1)
    max_run_duration_seconds: int = Field(..., ge=600)
    activities: MissionRunActivitiesSchema

    @model_validator(mode="after")
    def _heartbeat_fits_timeout(self) -> "MissionRunSchema":
        timeout = self.activities.execute_task.heartbeat_timeout_seconds
        if timeout is None:
            raise ValueError(
                "temporal.mission_run.activities.execute_task.heartbeat_timeout_seconds is required"
            )
        if self.task_heartbeat_interval_seconds * 2 > timeout:
            raise ValueError(
                "temporal.mission_run.task_heartbeat_interval_seconds must be at most half of "
                "activities.execute_task.heartbeat_timeout_seconds"
            )
        return self


class ReconcilerSchema(_StrictBase):
    orphan_grace_seconds: int = Field(..., ge=60)
    activity: ActivityPolicySchema


class SystemScheduleSchema(_StrictBase):
    cron: str = Field(..., min_length=9)


ALLOWED_SYSTEM_SCHEDULE_KEYS: frozenset[str] = frozenset(
    {
        "reconciler",
        "retention",
        "hourly_health_check",
        "weekly_report",
        "metrics_aggregation",
        "cleanup_environments",
        "knowledge_extraction",
        "knowledge_officer",
        "embedding_backfill",
    }
)


class TemporalSchema(_StrictBase):
    """Temporal integration configuration (Tier 4 durable execution)."""

    enabled: bool = False
    server_url: str | None = None
    namespace: str = "default"
    task_queue: str = "agent-missions"
    approval_timeout_seconds: int = 14400
    escalation_timeout_seconds: int = 86400
    notification_timeout_seconds: int = 30
    # Workflow-level retry and timeout tuning
    budget_timeout_multiplier_seconds: int = 120
    min_activity_timeout_seconds: int = 600
    persistence_timeout_seconds: int = 30
    persistence_retry_max_attempts: int = 3
    execution_retry_max_attempts: int = 2
    execution_retry_initial_interval_seconds: int = 5
    execution_retry_max_interval_seconds: int = 60
    mission_run: MissionRunSchema = Field(...)
    reconciler: ReconcilerSchema = Field(...)
    system_schedules: dict[str, SystemScheduleSchema] = Field(...)

    @model_validator(mode="after")
    def _require_server_url_when_enabled(self) -> "TemporalSchema":
        if self.enabled and self.server_url is None:
            raise ValueError(
                "temporal.server_url must be explicitly configured when " "temporal.enabled is true"
            )
        return self

    @model_validator(mode="after")
    def _system_schedule_keys(self) -> "TemporalSchema":
        keys = set(self.system_schedules)
        if keys != ALLOWED_SYSTEM_SCHEDULE_KEYS:
            raise ValueError(
                "temporal.system_schedules keys must match the registry exactly: "
                f"missing {sorted(ALLOWED_SYSTEM_SCHEDULE_KEYS - keys)}, "
                f"unknown {sorted(keys - ALLOWED_SYSTEM_SCHEDULE_KEYS)}"
            )
        return self


# =============================================================================
# workflows.yaml
# =============================================================================


class WorkshopSchema(_StrictBase):
    """Workshop (single-agent sandbox) configuration."""

    max_cached_input_sets: int = 10
    default_budget_usd: float = 2.00
    max_budget_usd: float = 20.00
    cache_stale_days: int = 7


class WorkflowsSchema(_StrictBase):
    """Workflow system configuration."""

    workflows_dir: str = "config/workflow_templates"
    max_steps_per_workflow: int = 20
    max_context_size_bytes: int = 1_048_576  # 1MB
    default_step_timeout_seconds: int = 600
    default_budget_usd: float = 10.00
    max_budget_usd: float = 100.00
    max_concurrent_missions: int = 10
    enable_workflow_matching: bool = True
    # No default: the model new LLM-call and decision steps start with is a deployment choice.
    default_step_model: str = Field(
        ...,
        min_length=1,
        description="A models.yaml alias that new LLM-call and decision steps start with.",
    )
    workshop: WorkshopSchema = Field(default_factory=WorkshopSchema)


class NotificationsSchema(_StrictBase):
    """Run notification configuration."""

    enabled: bool = True
    budget_warning_threshold_pct: float = 80.0
    notify_on_completion: bool = True
    notify_on_failure: bool = True
    notify_channels: list[str] = Field(default_factory=lambda: ["telegram"])


# =============================================================================
# projects.yaml
# =============================================================================


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
    learnings: KnowledgeLearningsSchema = Field(default_factory=KnowledgeLearningsSchema)
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


class MissionsSchema(_StrictBase):
    """Mission system configuration."""

    default_budget_ceiling_usd: float | None = None
    max_missions_per_owner: int = 50
    pcd_max_size_bytes: int = 20_480  # 20KB
    pcd_target_size_bytes: int = 15_360  # 15KB
    pcd_prune_threshold_pct: int = 80
    pcd_alert_threshold_pct: int = 90
    history_summarize_after_days: int = 30
    enable_context_assembly: bool = True
    knowledge: KnowledgeSchema = Field(default_factory=KnowledgeSchema)
    recurrence: RecurrenceSchema = Field(...)


# =============================================================================
# gate.yaml
# =============================================================================


class GateAiSchema(_StrictBase):
    """AI reviewer model and budget settings."""

    model: str  # a registry model, e.g. the provider:model string of the reviewer
    max_tokens: int = Field(..., ge=1)
    budget_per_review_usd: float = Field(
        default=0.01,
        description=(
            "Hard cost cap per gate review call. Not yet enforced — "
            "reserved for future use (e.g. model selection by budget, "
            "post-hoc cost tracking, or aborting expensive reviews)."
        ),
    )


_GateMode = Literal["interactive", "manual", "ai_assisted", "autonomous"]


class GatePointSchema(_StrictBase):
    """Per-gate-point configuration."""

    enabled: bool = True
    mode: _GateMode | None = None  # None = inherit from top-level GateSchema.mode


class GatePointsSchema(_StrictBase):
    """All six gate points with per-point overrides."""

    pre_dispatch: GatePointSchema = Field(default_factory=GatePointSchema)
    pre_layer: GatePointSchema = Field(default_factory=GatePointSchema)
    post_task: GatePointSchema = Field(default_factory=GatePointSchema)
    verification_failed: GatePointSchema = Field(default_factory=GatePointSchema)
    post_layer: GatePointSchema = Field(default_factory=GatePointSchema)
    # Plan 51 Phase C: post-run autonomy loop checkpoint. Called
    # directly from MissionPlanService.dispatch_approved, not routed
    # through ConfigurableGate. Config entry for discovery/enable flag.
    post_run: GatePointSchema = Field(default_factory=GatePointSchema)


class GateAutoRulesSchema(_StrictBase):
    """Auto-continue rules for autonomous mode to skip routine LLM calls."""

    cost_threshold_pct: int = 80
    max_tasks_per_layer: int = 10
    skip_post_task_on_pass: bool = True


class ProviderAuthSchema(_StrictBase):
    """Authentication configuration for a model provider.

    Provider-specific fields (e.g. ``scope`` for Foundry Entra auth) live here
    rather than in a subclass. If a third provider needs its own quirk field,
    promote this to ``ProviderAuthBase`` + per-provider subclasses instead of
    growing the union — the pattern-of-three threshold for splitting is real.
    """

    auth_mode: str = (
        "api_key"  # "api_key" | "auth_token" | "codex_oauth" | "entra" | "bearer_token"
    )
    env_var: str | None = None
    base_url: str | None = None
    scope: str | None = None  # foundry-only: Entra ID token scope
    # foundry-only, used by model discovery to list deployments through Azure Resource Manager
    subscription_id: str | None = None
    resource_group: str | None = None
    account_name: str | None = None
    # Path appended to base_url for each wire protocol the provider serves, e.g.
    # foundry: {openai_chat: /openai/v1/, anthropic_messages: /anthropic}.
    endpoint_paths: dict[str, str] = Field(default_factory=dict)
    # Model format the provider reports for a deployment -> the protocol it answers,
    # used by `catalog discover` to catch a model registered under the wrong protocol.
    deployment_protocols: dict[str, str] = Field(default_factory=dict)


class CopilotClientSchema(_StrictBase):
    """Copilot SDK client health check settings (providers.yaml copilot_client)."""

    health_check_interval_seconds: int = Field(..., ge=30)
    ping_timeout_seconds: int = Field(..., ge=1, le=60)


class ProvidersSchema(_StrictBase):
    """Provider authentication configuration (providers.yaml).

    Every ``ProviderAuthSchema`` field is a provider. Other fields (``copilot_client``)
    are client settings: use ``provider_names()`` and ``auth_for()``, never
    ``model_fields``, to enumerate or look up providers.
    """

    copilot_client: CopilotClientSchema
    anthropic: ProviderAuthSchema = Field(
        default_factory=lambda: ProviderAuthSchema(
            auth_mode="api_key",
            env_var="ANTHROPIC_API_KEY",
        ),
    )
    openai: ProviderAuthSchema = Field(
        default_factory=lambda: ProviderAuthSchema(
            auth_mode="api_key",
            env_var="OPENAI_API_KEY",
        ),
    )
    foundry: ProviderAuthSchema = Field(
        default_factory=lambda: ProviderAuthSchema(
            auth_mode="entra",
            env_var=None,
            base_url=None,
            scope="https://ai.azure.com/.default",
        ),
    )
    foundry_project: ProviderAuthSchema = Field(
        default_factory=lambda: ProviderAuthSchema(
            auth_mode="entra",
            env_var=None,
            base_url=None,
            scope="https://ai.azure.com/.default",
        ),
    )

    @classmethod
    def provider_names(cls) -> frozenset[str]:
        """Names of the provider auth entries, excluding client settings."""
        return frozenset(
            name
            for name, field in cls.model_fields.items()
            if field.annotation is ProviderAuthSchema
        )

    def auth_for(self, provider: str) -> ProviderAuthSchema | None:
        """Auth settings for ``provider``, or None when it has no auth entry."""
        if provider not in self.provider_names():
            return None
        return getattr(self, provider)

    @model_validator(mode="after")
    def _protocols_match_backends(self) -> "ProvidersSchema":
        """Protocols named in endpoint_paths and deployment_protocols must exist."""
        from modules.backend.core.model_backends import BACKENDS

        for name in self.provider_names():
            if name not in BACKENDS:
                continue
            block = getattr(self, name)
            named = [*block.endpoint_paths, *block.deployment_protocols.values()]
            for protocol in named:
                if protocol not in BACKENDS[name]:
                    raise ValueError(
                        f"providers.{name}: unknown protocol '{protocol}'. "
                        f"Supported: {sorted(BACKENDS[name])}."
                    )
        return self


class ModelSpec(_StrictBase):
    """One registered model: how it is called and the behaviour that varies by model."""

    protocol: str
    thinking: Literal["budget", "adaptive"] = Field(
        default="budget",
        description=(
            "Extended-thinking style for models called over the Anthropic Messages "
            "protocol: 'budget' takes an explicit token budget, 'adaptive' is required "
            "by models that reject one."
        ),
    )
    output_mode: Literal["tool", "native", "prompted"] = Field(
        default="tool",
        description=(
            "How structured output is enforced for agents on this model unless the "
            "agent sets its own. 'tool' (default) forces a final_result tool call; "
            "'prompted' puts the schema in the instructions, for models that reject a "
            "forced tool choice (openai_chat, anthropic_messages); 'native' uses "
            "response_format json_schema (openai_chat only)."
        ),
    )


class ModelsSchema(_StrictBase):
    """Model alias configuration (models.yaml).

    Aliases map short names (quick, moderate, comprehensive) to
    fully-qualified provider:model strings. Workflow steps reference
    aliases so changing provider in one place propagates everywhere.

    Registry lists every valid model of each provider with its ModelSpec. It is
    the source of truth for how a model is built (see model_backends.py) and is
    used by admin catalog writes to reject `provider:model` strings that don't
    correspond to a deployed model.
    """

    aliases: dict[str, str]
    registry: dict[str, dict[str, ModelSpec]] = Field(
        default_factory=dict,
        description="Valid models as {provider: {model: ModelSpec}}.",
    )

    @model_validator(mode="after")
    def _registry_matches_backends(self) -> "ModelsSchema":
        """Every provider and protocol must exist, and each spec must suit its protocol."""
        from modules.backend.core.model_backends import (
            ANTHROPIC_SETTINGS_PROTOCOLS,
            BACKENDS,
            output_mode_error,
        )

        for provider, models in self.registry.items():
            if provider not in BACKENDS:
                raise ValueError(
                    f"models.registry: unknown provider '{provider}'. Known: {sorted(BACKENDS)}."
                )
            for model, spec in models.items():
                if spec.protocol not in BACKENDS[provider]:
                    raise ValueError(
                        f"models.registry.{provider}.{model}: unknown protocol "
                        f"'{spec.protocol}'. Supported: {sorted(BACKENDS[provider])}."
                    )
                if (
                    "thinking" in spec.model_fields_set
                    and spec.protocol not in ANTHROPIC_SETTINGS_PROTOCOLS
                ):
                    raise ValueError(
                        f"models.registry.{provider}.{model}: 'thinking' applies only to "
                        f"{sorted(ANTHROPIC_SETTINGS_PROTOCOLS)}, not '{spec.protocol}'."
                    )
                error = output_mode_error(spec.output_mode, {spec.protocol})
                if error:
                    raise ValueError(
                        f"models.registry.{provider}.{model}: {error}, not '{spec.protocol}'."
                    )
        return self

    def models_of(self, provider: str) -> list[str]:
        """Every registered model of ``provider``."""
        return list(self.registry.get(provider, {}))

    def spec_of(self, provider: str, model: str) -> ModelSpec | None:
        """The registered spec of ``model``, or None when it is not registered."""
        return self.registry.get(provider, {}).get(model)

    def models_by_provider(self) -> dict[str, list[str]]:
        """``{provider: [model, ...]}`` without the specs."""
        return {provider: self.models_of(provider) for provider in self.registry}


class GateManualSchema(_StrictBase):
    """Manual gate configuration (Plan 80g)."""

    timeout_seconds: int = Field(
        ...,
        ge=1,
        description=(
            "How long a manual gate or a PROPOSED task approval waits for "
            "an HTTP decision before auto-aborting. Reduce for ephemeral "
            "runs, increase for long unattended sessions."
        ),
    )
    poll_interval_seconds: int = Field(..., ge=1)


class GateSchema(_StrictBase):
    """Gate reviewer configuration (gate.yaml)."""

    mode: _GateMode = Field(...)
    ai: GateAiSchema
    manual: GateManualSchema
    points: GatePointsSchema = Field(default_factory=GatePointsSchema)
    auto_rules: GateAutoRulesSchema = Field(default_factory=GateAutoRulesSchema)


# =============================================================================
# cli.yaml (Plan 88 step 88.1.13)
# =============================================================================


class CliMcSchema(_StrictBase):
    """User CLI (mc.py) presentation settings."""

    runs_list_limit: int = Field(..., ge=1, le=200)


class CliSchema(_StrictBase):
    """CLI configuration (cli.yaml)."""

    mc: CliMcSchema


# =============================================================================
# failures.yaml (Plan 88 step 88.2.3b, contracts 3.4.9)
# =============================================================================


class FailureEvidenceBoundsSchema(_StrictBase):
    max_message_chars: int = Field(..., ge=1)
    max_summary_chars: int = Field(..., ge=1)
    max_traceback_frames: int = Field(..., ge=1)


class FailureSupervisorSchema(_StrictBase):
    max_failure_digests: int = Field(..., ge=1)


class FailuresSchema(_StrictBase):
    """Task failure evidence bounds and retry policy (failures.yaml). Rules are code."""

    evidence: FailureEvidenceBoundsSchema
    supervisor: FailureSupervisorSchema
    unknown_retryable: bool


# =============================================================================
# cost.yaml (Plan 60)
# =============================================================================


class CostAlertsSchema(_StrictBase):
    """Alert thresholds for cost monitoring (Phase 3)."""

    hourly_spend_limit_usd: float = 5.0
    per_agent_hourly_limit_usd: float = 2.0
    min_cache_hit_rate: float = 0.40


class OutputEfficiencySchema(_StrictBase):
    """Output/input ratio thresholds for flagging expensive agents."""

    high_threshold: float = 3.0
    critical_threshold: float = 5.0


class CostSchema(_StrictBase):
    """Cost management configuration (cost.yaml)."""

    default_cache_ttl: str = "1h"
    alerts: CostAlertsSchema = Field(default_factory=CostAlertsSchema)
    emergency_downgrade_model: str
    output_efficiency: OutputEfficiencySchema = Field(
        default_factory=OutputEfficiencySchema,
    )


# =============================================================================
# security_assessment.yaml (WASA — Plan 66/67)
# =============================================================================


class SecurityAssessmentRiskWeightsSchema(_StrictBase):
    """Composite risk score weights for the report."""

    cvss: float = 0.40
    exploitability: float = 0.30
    business_impact: float = 0.30


class SecurityAssessmentSchema(_StrictBase):
    """WASA security assessment configuration (security_assessment.yaml).

    Phase 1 fields only. Phase 2/3 additions (recon_rate_limit_rps,
    dast_proxy_port, appsec_*, exploit_*, auth_*) will be added when
    those phases are implemented.
    """

    # Scope enforcement
    roe_opa_endpoint: str = Field(
        description="OPA endpoint for ROE scope validation. Required.",
    )
    scope_validation_mode: str = Field(
        default="strict",
        pattern=r"^(strict|permissive)$",
    )

    # Scanner phase
    scanner_max_file_size_bytes: int = Field(default=1_048_576, ge=1024)
    tool_registry_path: str = Field(default="config/security/tools.yaml")

    # Triage phase
    triage_fp_confidence_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    triage_code_context_lines: int = Field(default=10, ge=3, le=25)
    triage_max_findings_per_run: int = Field(default=500, ge=10, le=2000)

    # Evidence
    evidence_sha256_on_write: bool = Field(default=True)
    evidence_base_path: str = Field(default="@workspace/evidence/")

    # Cost controls
    cost_hard_limit_usd: float = Field(default=50.0, ge=1.0, le=500.0)
    cost_alert_threshold_pct: float = Field(default=0.80, ge=0.5, le=0.95)

    # Report
    report_min_executive_summary_chars: int = Field(default=300, ge=100)
    report_risk_score_weights: SecurityAssessmentRiskWeightsSchema = Field(
        default_factory=SecurityAssessmentRiskWeightsSchema,
    )
