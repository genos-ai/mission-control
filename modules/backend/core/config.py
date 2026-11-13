"""
Configuration Management.

Loads secrets from config/.env and settings from config/settings/*.yaml.
No hardcoded values in code — all configuration comes from these sources.

Secrets (.env):
    DB_PASSWORD, REDIS_PASSWORD, JWT_SECRET, API_KEY_SALT,
    TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET

Settings (YAML):
    application.yaml - App identity, server, cors, telegram, pagination
    database.yaml    - Database and Redis connection settings
    logging.yaml     - Logging configuration
    features.yaml    - Feature flags
    security.yaml    - JWT settings
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from modules.backend.core.config_schema import (
    ApplicationSchema,
    CliSchema,
    CostSchema,
    DatabaseSchema,
    EventsSchema,
    ExecutionsSchema,
    FailuresSchema,
    FeaturesSchema,
    GateSchema,
    GatewaySchema,
    LoggingSchema,
    ModelsSchema,
    NotificationsSchema,
    ProvidersSchema,
    SecurityAssessmentSchema,
    SecuritySchema,
    SessionsSchema,
    TemporalSchema,
    WorkflowsSchema,
)
from modules.backend.core.config_schema_missions import MissionsSchema


def find_project_root() -> Path:
    """Find project root by looking for .project_root marker file."""
    current = Path.cwd()
    while current != current.parent:
        if (current / ".project_root").exists():
            return current
        current = current.parent
    raise RuntimeError("Project root not found. Ensure .project_root file exists.")


def validate_project_root() -> Path:
    """
    Validate that the project root can be found.

    Raises SystemExit with a clear message if .project_root is not found.
    Use this in entry scripts before any configuration loading.
    """
    try:
        return find_project_root()
    except RuntimeError as e:
        raise SystemExit(f"Error: {e}") from e


def load_yaml_config(filename: str) -> dict[str, Any]:
    """Load a YAML configuration file from config/settings/."""
    project_root = find_project_root()
    config_path = project_root / "config" / "settings" / filename

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path) as f:
        return yaml.safe_load(f) or {}


class Settings(BaseSettings):
    """Secrets and env-only runtime toggles loaded from config/.env / environment."""

    db_password: str
    redis_password: str
    jwt_secret: str
    api_key_salt: str
    telegram_bot_token: str
    telegram_webhook_secret: str
    anthropic_api_key: str
    admin_api_key: str = ""
    perplexity_api_key: str = ""
    tavily_api_key: str = ""
    brave_api_key: str = ""

    # Passwords of the dev users seeded in development and test (DEV_*_PASSWORD in config/.env).
    # Empty means not configured: seeding refuses to run rather than create a known password.
    dev_sysadmin_password: str = ""
    dev_admin_password: str = ""
    dev_user_password: str = ""

    # Runtime toggles (set via environment, e.g. by services.py --trace).
    # MC_AGENT_TRACE=1 emits agent trace events to the mission event bus.
    mc_agent_trace: bool = False

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def _load_validated(schema_cls: type, filename: str) -> Any:
    """Load YAML and validate against schema. Returns typed model instance."""
    raw = load_yaml_config(filename)
    try:
        return schema_cls(**raw)
    except ValidationError as e:
        raise ValueError(f"Invalid configuration in {filename}:\n{e}") from e


def _load_validated_optional(schema_cls: type, filename: str) -> Any:
    """Load YAML if it exists, otherwise return schema defaults."""
    try:
        return _load_validated(schema_cls, filename)
    except FileNotFoundError:
        return schema_cls()


class AppConfig:
    """
    Application configuration loaded from YAML files.

    Each YAML file is validated against its Pydantic schema at load time.
    Missing keys, wrong types, or unknown fields raise a clear error
    immediately instead of causing cryptic KeyErrors later.

    Properties return typed Pydantic model instances with attribute access.
    """

    def __init__(self) -> None:
        self._application = _load_validated(ApplicationSchema, "application.yaml")
        self._database = _load_validated(DatabaseSchema, "database.yaml")
        self._logging = _load_validated(LoggingSchema, "logging.yaml")
        self._features = _load_validated(FeaturesSchema, "features.yaml")
        self._security = _load_validated(SecuritySchema, "security.yaml")
        self._gateway = _load_validated(GatewaySchema, "gateway.yaml")
        self._events = _load_validated_optional(EventsSchema, "events.yaml")
        self._sessions = _load_validated_optional(SessionsSchema, "sessions.yaml")
        self._executions = _load_validated(ExecutionsSchema, "executions.yaml")
        self._temporal = _load_validated_optional(TemporalSchema, "temporal.yaml")
        self._workflows = _load_validated_optional(WorkflowsSchema, "workflows.yaml")
        self._missions = _load_validated_optional(MissionsSchema, "missions.yaml")
        self._gate = _load_validated(GateSchema, "gate.yaml")
        self._notifications = _load_validated_optional(NotificationsSchema, "notifications.yaml")
        self._providers = _load_validated(ProvidersSchema, "providers.yaml")
        self._models = _load_validated(ModelsSchema, "models.yaml")
        self._cost = _load_validated(CostSchema, "cost.yaml")
        self._cli = _load_validated(CliSchema, "cli.yaml")
        self._failures = _load_validated(FailuresSchema, "failures.yaml")
        self._security_assessment = _load_validated_optional(
            SecurityAssessmentSchema,
            "security_assessment.yaml",
        )
        if self._workflows.default_step_model not in self._models.aliases:
            raise ValueError(
                f"Invalid configuration in workflows.yaml: default_step_model "
                f"'{self._workflows.default_step_model}' is not a models.yaml alias "
                f"(known: {sorted(self._models.aliases)})"
            )

    @property
    def application(self) -> ApplicationSchema:
        """Application settings."""
        return self._application

    @property
    def database(self) -> DatabaseSchema:
        """Database settings."""
        return self._database

    @property
    def logging(self) -> LoggingSchema:
        """Logging settings."""
        return self._logging

    @property
    def features(self) -> FeaturesSchema:
        """Feature flags."""
        return self._features

    @property
    def security(self) -> SecuritySchema:
        """Security settings."""
        return self._security

    @property
    def gateway(self) -> GatewaySchema:
        """Gateway settings."""
        return self._gateway

    @property
    def events(self) -> EventsSchema:
        """Event bus settings."""
        return self._events

    @property
    def sessions(self) -> SessionsSchema:
        """Session settings."""
        return self._sessions

    @property
    def executions(self) -> ExecutionsSchema:
        """Execution persistence settings."""
        return self._executions

    @property
    def temporal(self) -> TemporalSchema:
        """Temporal integration settings."""
        return self._temporal

    @property
    def workflows(self) -> WorkflowsSchema:
        """Workflow system settings."""
        return self._workflows

    @property
    def missions(self) -> MissionsSchema:
        """Mission system settings."""
        return self._missions

    @property
    def gate(self) -> GateSchema:
        """Gate reviewer settings."""
        return self._gate

    @property
    def notifications(self) -> NotificationsSchema:
        """Run notification settings."""
        return self._notifications

    @property
    def providers(self) -> ProvidersSchema:
        """Model provider auth settings."""
        return self._providers

    @property
    def models(self) -> ModelsSchema:
        """Model alias configuration (quick/moderate/comprehensive)."""
        return self._models

    @property
    def cost(self) -> CostSchema:
        """Cost management settings (Plan 60)."""
        return self._cost

    @property
    def cli(self) -> CliSchema:
        """User CLI presentation settings (Plan 88 step 88.1.13)."""
        return self._cli

    @property
    def failures(self) -> FailuresSchema:
        """Task failure evidence bounds and retry policy (Plan 88 step 88.2.3b)."""
        return self._failures

    @property
    def security_assessment(self) -> SecurityAssessmentSchema:
        """WASA security assessment settings (Plan 66/67)."""
        return self._security_assessment


@lru_cache
def get_settings() -> Settings:
    """Get cached secrets instance. Resolves .env path from project root."""
    env_path = find_project_root() / "config" / ".env"
    return Settings(_env_file=str(env_path))


@lru_cache
def get_app_config() -> AppConfig:
    """Get cached application configuration."""
    return AppConfig()


@lru_cache
def get_mission_control_config():
    """Load and cache mission_control.yaml configuration.

    Returns a MissionControlConfigSchema with routing, guardrails,
    dispatch, and other mission control settings.
    """
    from modules.backend.schemas.agent_config import MissionControlConfigSchema

    config_path = find_project_root() / "config" / "agents" / "mission_control.yaml"
    import yaml

    with open(config_path) as f:
        raw = yaml.safe_load(f)
    return MissionControlConfigSchema(**raw)


def get_default_budget_usd() -> float:
    """Return the configured default workflow budget from workflows.yaml.

    The plan-validation budget for workflow and in-process dispatch paths
    that are not given one. Mission spend caps live on the mission plan
    (missions.budgets). Never hardcode 10.0; always call this function.
    """
    return get_app_config().workflows.default_budget_usd


def get_database_url(async_driver: bool = True) -> str:
    """
    Construct database URL from YAML config and secrets.

    Args:
        async_driver: Use asyncpg driver if True, psycopg2 if False.

    Returns:
        Database connection URL string.
    """
    db = get_app_config().database
    password = get_settings().db_password
    driver = "postgresql+asyncpg" if async_driver else "postgresql"
    return f"{driver}://{db.user}:{password}@{db.host}:{db.port}/{db.name}"


def get_redis_url() -> str:
    """
    Construct Redis URL from YAML config and secrets.

    Returns:
        Redis connection URL string.
    """
    redis = get_app_config().database.redis
    password = get_settings().redis_password
    return f"redis://:{password}@{redis.host}:{redis.port}/{redis.db}"


def get_sanitized_config_view() -> dict:
    """Return non-secret platform configuration as a plain dict.

    Used by the admin config endpoint and any other view that needs
    to expose configuration without leaking secrets.
    """
    config = get_app_config()
    return {
        "application": {
            "name": config.application.name,
            "version": config.application.version,
            "environment": config.application.environment,
            "debug": config.application.debug,
        },
        "workflows": {
            "max_steps_per_workflow": config.workflows.max_steps_per_workflow,
            "default_budget_usd": config.workflows.default_budget_usd,
            "max_budget_usd": config.workflows.max_budget_usd,
            "max_concurrent_missions": config.workflows.max_concurrent_missions,
        },
        "sessions": {
            "default_ttl_hours": config.sessions.default_ttl_hours,
            "default_cost_budget_usd": config.sessions.default_cost_budget_usd,
            "max_cost_budget_usd": config.sessions.max_cost_budget_usd,
        },
        "notifications": {
            "enabled": config.notifications.enabled,
            "notify_on_completion": config.notifications.notify_on_completion,
            "notify_on_failure": config.notifications.notify_on_failure,
            "budget_warning_threshold_pct": config.notifications.budget_warning_threshold_pct,
        },
        "features": {
            "gateway_enabled": config.features.gateway_enabled,
            "agent_coordinator_enabled": config.features.agent_coordinator_enabled,
            "mcp_enabled": config.features.mcp_enabled,
        },
    }


def get_server_base_url() -> tuple[str, float]:
    """
    Get the backend server base URL and timeout from application.yaml.

    Returns:
        Tuple of (base_url, timeout_seconds).
    """
    app = get_app_config().application
    server = app.server
    base_url = f"http://{server.host}:{server.port}"
    timeout = float(app.timeouts.external_api)
    return base_url, timeout
