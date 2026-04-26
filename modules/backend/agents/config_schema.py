"""DEPRECATED: Import from modules.backend.schemas.agent_config instead.

Re-exports all types for backward compatibility.
"""

from modules.backend.schemas.agent_config import (  # noqa: F401
    AgentConfigSchema,
    AgentInterfaceSchema,
    AgentModelSchema,
    ApprovalSchema,
    ComplianceRuleSchema,
    DispatchSchema,
    EscalationThresholdsSchema,
    ExecutionSchema,
    ExclusionsSchema,
    FileScopeConfigSchema,
    GuardrailsSchema,
    InvocationSchema,
    MissionControlConfigSchema,
    MissionControlLimitsSchema,
    ModelPricingRateSchema,
    RedisTtlSchema,
    RoutingSchema,
)
