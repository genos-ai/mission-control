# Code Map — mission-control

**360 files** | **57,348 lines** | **516 classes** | **752 functions** | commit `b38172f4f83d`

Symbols ranked by PageRank (most-connected first).

## Dependencies

  clients.tui.app -> backend.core.logging, clients.tui.messages, clients.tui.screens.admin, clients.tui.screens.catalog, clients.tui.screens.dashboard, clients.tui.screens.profile, clients.tui.screens.workspace, clients.tui.screens.mission_picker, clients.tui.screens.mission_history, clients.tui.services.event_listener, clients.tui.services.service_bridge, clients.tui.services.state, backend.agents.mission_control.dispatch, backend.agents.mission_control.outcome, backend.schemas.task_plan, clients.tui.widgets.agent_detail, clients.tui.widgets.agent_sidebar, clients.tui.widgets.cost_bar, clients.tui.widgets.event_stream, clients.tui.services.gate_reviewer, clients.tui.widgets.gate_modal, clients.tui.widgets.mission_panel, clients.tui.widgets.notification, clients.tui.widgets.workflow_progress
  backend.agents.mission_control.mission_control -> backend.agents.mission_control.cost, backend.core.exceptions, backend.agents.mission_control.dispatch, backend.agents.mission_control.gate, backend.agents.mission_control.persistence_bridge, backend.agents.mission_control.helpers, backend.agents.mission_control.history, backend.agents.mission_control.middleware, backend.agents.mission_control.models, backend.core.protocols, backend.agents.mission_control.outcome, backend.agents.mission_control.plan_validator, backend.agents.mission_control.registry, backend.agents.mission_control.roster, backend.core.logging, backend.events.types, backend.schemas.session, backend.schemas.task_plan, backend.services.context_assembler, backend.services.context_curator, backend.services.history_query, backend.services.mission_context
  backend.models -> backend.models.base, backend.models.agent_catalog, backend.models.execution, backend.models.execution_record, backend.models.mission_team, backend.models.note, backend.models.mission, backend.models.mission_context, backend.models.mission_history, backend.models.mission_plan, backend.models.prompt_version, backend.models.session, backend.models.workflow_definition, backend.models.user, backend.models.api_key, backend.models.workflow_schedule
  backend.migrations.env -> backend.models.base, backend.models.execution, backend.models.execution_record, backend.models.note, backend.models.mission, backend.models.mission_context, backend.models.mission_history, backend.models.session, backend.models.agent_catalog, backend.models.mission_team, backend.models.prompt_version, backend.models.workflow_definition, backend.models.workflow_schedule, backend.models.user, backend.models.api_key
  backend.agents.mission_control.dispatch.loop -> backend.agents.mission_control.dispatch.dag, backend.agents.mission_control.dispatch.result_builders, backend.agents.mission_control.dispatch.step_executor, backend.agents.mission_control.gate, backend.agents.mission_control.helpers, backend.agents.mission_control.models, backend.agents.mission_control.outcome, backend.agents.mission_control.roster, backend.core.logging, backend.events.types, backend.schemas.task_plan
  backend.agents.mission_control.helpers.agent_executor -> backend.agents.mission_control.models, backend.agents.mission_control.registry, backend.agents.mission_control.cost, backend.core.config, backend.core.exceptions, backend.core.logging, backend.events.types, backend.agents.mission_control.helpers.agent_setup, backend.agents.mission_control.helpers.event_emitter, backend.agents.mission_control.helpers.model_builder, backend.agents.mission_control.helpers.prompt_builder
  backend.api.v1.endpoints.streams -> backend.core.config, backend.core.dependencies, backend.core.exceptions, backend.core.logging, backend.events.bus, backend.models.user, backend.services.console, backend.services.mission, backend.services.session
  backend.services.auth -> backend.core, backend.core.exceptions, backend.core.logging, backend.core.utils, backend.models.api_key, backend.models.user, backend.repositories.api_key, backend.repositories.user, backend.services.base
  backend.services.execution -> backend.core.config, backend.core.exceptions, backend.agents.mission_control.models, backend.core.logging, backend.core.protocols, backend.core.utils, backend.models.execution, backend.repositories.execution, backend.services.base
  backend.services.workflow_architect -> backend.agents.deps.base, backend.agents.mission.workflow.agent, backend.agents.mission.workflow.deps, backend.agents.mission_control.helpers, backend.agents.mission_control.registry, backend.core.config, backend.core.logging, backend.events.types, backend.services.base
  backend.services.workflow_run -> backend.core.config, backend.core.logging, backend.core.utils, backend.models.execution, backend.repositories.workflow_run, backend.schemas.workflow, backend.services.base, backend.services.execution, backend.services.workflow
  backend.agents.mission_control.dispatch.step_executor -> backend.agents.mission_control.helpers, backend.agents.mission_control.middleware, backend.agents.mission_control.models, backend.agents.mission_control.outcome, backend.agents.mission_control.roster, backend.agents.mission_control.verification, backend.events.types, backend.schemas.task_plan
  backend.services.mission_team -> backend.core.exceptions, backend.core.logging, backend.models.mission_team, backend.repositories.agent_catalog, backend.repositories.mission, backend.repositories.mission_team, backend.repositories.prompt_version, backend.services.base
  backend.services.platform_metrics -> backend.core.logging, backend.core.utils, backend.models.agent_catalog, backend.models.execution, backend.models.execution_record, backend.models.mission, backend.models.session, backend.services.base
  backend.services.session -> backend.core.config, backend.core.exceptions, backend.core.logging, backend.core.utils, backend.models.session, backend.repositories.session, backend.schemas.session, backend.services.base
  backend.services.workflow_schedule -> backend.core.config, backend.core.exceptions, backend.core.logging, backend.core.utils, backend.models.workflow_schedule, backend.repositories.workflow_definition, backend.repositories.workflow_schedule, backend.services.base
  backend.services.workshop -> backend.agents.mission_control.helpers, backend.agents.mission_control.cost, backend.agents.mission_control.registry, backend.core.config, backend.core.logging, backend.core.utils, backend.models.execution_record, backend.services.base
  clients.tui.screens.workspace -> clients.tui.tabs.chat, clients.tui.tabs.context, clients.tui.tabs.overview, clients.tui.tabs.runs, clients.tui.tabs.team, clients.tui.tabs.workflows, clients.tui.tabs.workshop, clients.tui.widgets.cost_bar
  backend.agents.mission_control.dispatch.retry_handler -> backend.agents.mission_control.dispatch.result_builders, backend.agents.mission_control.dispatch.step_executor, backend.agents.mission_control.gate, backend.agents.mission_control.outcome, backend.agents.mission_control.roster, backend.core.logging, backend.schemas.task_plan
  backend.api.v1.endpoints.missions_plan -> backend.core.dependencies, backend.core.exceptions, backend.models.mission_plan, backend.schemas.base, backend.schemas.mission_plan, backend.services.mission, backend.services.mission_plan
  backend.services.execution_persistence -> backend.core.config, backend.core.logging, backend.core.utils, backend.models.execution_record, backend.repositories.execution_record, backend.schemas.execution_record, backend.services.base
  backend.services.mission_plan -> backend.core.exceptions, backend.core.utils, backend.models.mission_plan, backend.repositories.mission, backend.repositories.mission_plan, backend.schemas.task_plan, backend.services.base
  backend.services.summarization -> backend.core.logging, backend.core.utils, backend.models.execution_record, backend.models.mission_history, backend.repositories.mission_history, backend.services.base, backend.services.mission_context
  backend.services.workflow_definition -> backend.core.exceptions, backend.core.logging, backend.models.workflow_definition, backend.repositories.mission, backend.repositories.workflow_definition, backend.schemas.workflow, backend.services.base
  backend.agents.mission_control.helpers -> backend.agents.mission_control.helpers.model_builder, backend.agents.mission_control.helpers.prompt_builder, backend.agents.mission_control.helpers.agent_setup, backend.agents.mission_control.helpers.routing, backend.agents.mission_control.helpers.event_emitter, backend.agents.mission_control.helpers.agent_executor
  backend.agents.mission_control.helpers.agent_setup -> backend.agents.config_schema, backend.agents.deps.base, backend.agents.mission_control.middleware, backend.agents.mission_control.registry, backend.core.config, backend.core.logging
  backend.agents.mission_control.helpers.routing -> backend.agents.mission_control.middleware, backend.agents.mission_control.models, backend.agents.mission_control.registry, backend.agents.mission_control.router, backend.core.exceptions, backend.core.logging
  backend.api.v1.endpoints.executions -> backend.core.dependencies, backend.core.exceptions, backend.core.logging, backend.schemas.base, backend.schemas.execution_record, backend.services.execution_persistence
  backend.api.v1.endpoints.missions -> backend.api.v1.endpoints, backend.core.dependencies, backend.core.exceptions, backend.schemas.base, backend.schemas.mission, backend.services.mission
  backend.api.v1.endpoints.missions_team -> backend.core.dependencies, backend.schemas.base, backend.schemas.mission, backend.schemas.mission_team, backend.services.mission, backend.services.mission_team
  backend.api.v1.endpoints.workflows -> backend.core.dependencies, backend.core.exceptions, backend.schemas.base, backend.schemas.execution, backend.services.execution, backend.services.workflow
  backend.main -> backend.api, backend.api.v1, backend.core.config, backend.core.exception_handlers, backend.core.logging, backend.core.middleware
  backend.services.bootstrap -> backend.core, backend.core.exceptions, backend.core.logging, backend.models.user, backend.repositories.api_key, backend.repositories.user
  backend.services.pqi.scorer -> backend.core.logging, backend.services.pqi.ast_analysis, backend.services.pqi.composite, backend.services.pqi.dimensions, backend.services.pqi.tools, backend.services.pqi.types
  backend.services.user -> backend.core, backend.core.exceptions, backend.models.user, backend.repositories.api_key, backend.repositories.user, backend.services.base
  clients.tui.services.service_bridge -> backend.agents.mission_control.gate, backend.agents.mission_control.mission_control, backend.agents.mission_control.models, backend.agents.mission_control.outcome, backend.agents.mission_control.roster, backend.core.logging
  backend.agents.mission.workflow.agent -> backend.agents.mission.workflow.deps, backend.agents.mission_control.helpers, backend.agents.tools, backend.core.logging, backend.events.types
  backend.agents.mission_control.dispatch.convergence -> backend.agents.mission_control.gate, backend.agents.mission_control.helpers, backend.agents.mission_control.models, backend.agents.mission_control.outcome, backend.core.logging
  backend.agents.mission_control.dispatch_adapter -> backend.agents.mission_control.mission_control, backend.agents.mission_control.models, backend.core.config, backend.core.protocols, backend.core.logging
  backend.agents.mission_control.helpers.event_emitter -> backend.agents.mission_control.models, backend.core.exceptions, backend.core.logging, backend.events.types, backend.schemas.session
  backend.agents.mission_control.plan_validator -> backend.agents.mission_control.check_registry, backend.agents.mission_control.roster, backend.core.logging, backend.schemas.task_plan, backend.agents.mission_control.checks.builtin
  backend.agents.platform.health.agent -> backend.agents.deps.base, backend.agents.mission_control.helpers, backend.agents.schemas, backend.agents.tools, backend.core.logging
  backend.agents.software.architecture.agent -> backend.agents.mission_control.helpers, backend.agents.deps.base, backend.agents.schemas, backend.agents.tools, backend.core.logging
  backend.agents.software.quality.agent -> backend.agents.mission_control.helpers, backend.agents.deps.base, backend.agents.schemas, backend.agents.tools, backend.core.logging
  backend.api.v1.endpoints.catalog -> backend.core.dependencies, backend.core.exceptions, backend.schemas.agent_catalog, backend.schemas.base, backend.services.agent_catalog
  backend.api.v1.endpoints.notes -> backend.core.dependencies, backend.core.pagination, backend.schemas.base, backend.schemas.note, backend.services.note
  backend.api.v1.endpoints.sessions -> backend.core.dependencies, backend.core.pagination, backend.schemas.base, backend.schemas.session, backend.services.session
  backend.services.agent_catalog -> backend.core.exceptions, backend.core.logging, backend.models.agent_catalog, backend.repositories.agent_catalog, backend.services.base
  backend.services.console -> backend.core.config, backend.core.database, backend.core.logging, backend.events.types, backend.models.session
  backend.services.mission -> backend.core.logging, backend.core.exceptions, backend.models.mission, backend.repositories.mission, backend.services.base
  backend.services.mission_context -> backend.core.logging, backend.core.utils, backend.models.mission_context, backend.repositories.mission_context, backend.services.base
  clients.telegram.handlers.example -> backend.core.config, backend.core.logging, clients.telegram.callbacks.common, clients.telegram.keyboards.common, clients.telegram.states.example
  backend.agents.mission_control.helpers.model_builder -> backend.agents.config_schema, backend.core.config, backend.core.exceptions, backend.core.logging
  backend.agents.mission_control.verification -> backend.agents.mission_control.models, backend.core.logging, backend.agents.mission_control.verification_models, backend.agents.mission_control.verification_tiers
  backend.api.v1.endpoints.admin_users -> backend.core.dependencies, backend.schemas.auth, backend.schemas.base, backend.schemas.user
  backend.api.v1.endpoints.auth -> backend.core.dependencies, backend.schemas.auth, backend.schemas.base, backend.schemas.user
  backend.api.v1.endpoints.client_errors -> backend.core.dependencies, backend.core.logging, backend.schemas.base, backend.schemas.client_error
  backend.core.dependencies -> backend.core.database, backend.core.exceptions, backend.models.user, backend.core.idempotency
  backend.core.security -> backend.core.config, backend.core.exceptions, backend.core.logging, backend.core.utils
  backend.events -> backend.events.bus, backend.events.publishers, backend.events.schemas, backend.events.types
  backend.services.catalog_seeder -> backend.agents.config_schema, backend.core.config, backend.core.logging, backend.services.agent_catalog
  backend.services.code_map.generator -> backend.services.code_map.assembler, backend.services.code_map.graph, backend.services.code_map.parser, backend.services.code_map.ranker
  backend.services.context_assembler -> backend.core.logging, backend.core.utils, backend.services.history_query, backend.services.mission_context
  backend.services.note -> backend.models.note, backend.repositories.note, backend.schemas.note, backend.services.base
  backend.services.pqi.dimensions.analysis -> backend.services.pqi.ast_analysis, backend.services.pqi.normalizers, backend.services.pqi.tools, backend.services.pqi.types
  backend.services.pqi.dimensions.style -> backend.services.pqi.ast_analysis, backend.services.pqi.normalizers, backend.services.pqi.tools, backend.services.pqi.types
  backend.temporal.worker -> backend.core.logging, backend.temporal.activities, backend.temporal.client, backend.temporal.workflow
  clients.cli.live_display -> backend.agents.mission_control.models, backend.events.types, clients.common.display, clients.common.event_rendering
  clients.telegram.middlewares -> clients.telegram.middlewares.auth, clients.telegram.middlewares.logging, clients.telegram.middlewares.rate_limit, clients.telegram.middlewares.setup
  clients.tui.services.state -> backend.agents.mission_control.gate, backend.agents.mission_control.outcome, backend.agents.mission_control.roster, backend.schemas.task_plan
  clients.tui.tabs.overview -> clients.tui.widgets.agent_sidebar, clients.tui.widgets.chat_input, clients.tui.widgets.event_stream, clients.tui.widgets.notification
  backend.agents.mission.director.agent -> backend.agents.mission.director.deps, backend.agents.mission_control.helpers, backend.core.logging
  backend.agents.mission_control.dispatch -> backend.agents.mission_control.dispatch.dag, backend.agents.mission_control.dispatch.loop, backend.agents.mission_control.dispatch.step_executor
  backend.agents.mission_control.gate -> backend.core.logging, backend.agents.mission_control.gate_models, backend.agents.mission_control.gate_prompt
  backend.agents.mission_control.middleware -> backend.agents.config_schema, backend.core.config, backend.core.logging
  backend.agents.mission_control.persistence_bridge -> backend.agents.mission_control.outcome, backend.core.logging, backend.services.execution_persistence
  backend.agents.mission_control.registry -> backend.agents.config_schema, backend.core.config, backend.core.logging
  backend.agents.mission_control.router -> backend.agents.mission_control.models, backend.agents.mission_control.registry, backend.core.logging
  backend.agents.mission_control.verification_tiers -> backend.agents.mission_control.models, backend.core.logging, backend.agents.mission_control.verification_models
  backend.agents.platform.director.agent -> backend.agents.platform.director.deps, backend.agents.mission_control.helpers, backend.core.logging
  backend.agents.preflight -> backend.agents.mission_control.helpers, backend.agents.mission_control.registry, backend.core.logging
  backend.agents.system.planning.agent -> backend.agents.deps.base, backend.agents.mission_control.helpers, backend.core.logging
  backend.agents.system.summarization.agent -> backend.agents.mission_control.helpers, backend.agents.mission_control.registry, backend.core.logging
  backend.agents.system.verification.agent -> backend.agents.deps.base, backend.agents.mission_control.helpers, backend.core.logging
  backend.agents.tools.compliance -> backend.agents.config_schema, backend.agents.deps.base, backend.services.compliance
  backend.api.v1.endpoints.agents -> backend.core.dependencies, backend.core.logging, backend.schemas.base
  backend.api.v1.endpoints.missions_workflows -> backend.core.dependencies, backend.schemas.base, backend.schemas.workflow_schedule
  backend.core.exception_handlers -> backend.core.exceptions, backend.core.logging, backend.schemas.base
  backend.events.bus -> backend.core.config, backend.core.logging, backend.events.types
  backend.gateway.adapters.telegram -> backend.core.config, backend.core.logging, backend.gateway.adapters
  backend.gateway.registry -> backend.core.config, backend.core.logging, backend.gateway.adapters
  backend.gateway.security.startup_checks -> backend.core.config, backend.core.config_schema, backend.core.logging
  backend.repositories.api_key -> backend.core.utils, backend.models.api_key, backend.repositories.base
  backend.repositories.base -> backend.core.exceptions, backend.core.logging, backend.models.base
  backend.repositories.execution -> backend.core.logging, backend.models.execution, backend.repositories.base
  backend.repositories.execution_record -> backend.core.logging, backend.models.execution_record, backend.repositories.base
  backend.repositories.session -> backend.core.utils, backend.models.session, backend.repositories.base
  backend.repositories.user -> backend.core.utils, backend.models.user, backend.repositories.base
  backend.repositories.workflow_run -> backend.core.logging, backend.models.execution, backend.repositories.base
  backend.services.code_map -> backend.services.code_map.generator, backend.services.code_map.assembler, backend.services.code_map.loader
  backend.services.history_query -> backend.core.logging, backend.models.execution_record, backend.services.base
  backend.services.workflow -> backend.core.config, backend.core.logging, backend.schemas.workflow
  clients.cli.console_cmds -> backend.core.logging, clients.common.display, clients.common.gate_helpers
  clients.cli.context -> clients.cli.report, backend.core.config, backend.core.utils
  clients.cli.gate -> backend.agents.mission_control.gate, clients.common.display, clients.common.gate_helpers
  clients.cli.mission_cmds -> clients.cli.mission_context, clients.cli.report, clients.common.display
  clients.cli.report -> backend.core.logging, clients.common.display, clients.common.display
  clients.telegram.handlers -> clients.telegram.handlers.common, clients.telegram.handlers.example, clients.telegram.handlers.setup
  clients.telegram.middlewares.auth -> backend.core.config, backend.core.logging, backend.core.security
  clients.telegram.middlewares.setup -> clients.telegram.middlewares.auth, clients.telegram.middlewares.logging, clients.telegram.middlewares.rate_limit
  clients.telegram.services.notifications -> backend.core.config, backend.core.logging, backend.core.utils
  clients.tui.services.event_listener -> backend.agents.mission_control.models, backend.core.logging, backend.events.types
  clients.tui.widgets.agent_sidebar -> backend.agents.mission_control.roster, clients.common.gate_helpers, clients.tui.messages
  clients.tui.widgets.gate_modal -> backend.agents.mission_control.gate, clients.common.gate_helpers, clients.tui.messages
  clients.tui.widgets.mission_panel -> backend.agents.mission_control.outcome, backend.schemas.task_plan, clients.common.gate_helpers
  backend.agents.mission_control.approval -> backend.core.config, backend.core.logging
  backend.agents.mission_control.checks.builtin -> backend.agents.mission_control.check_registry, backend.core.logging
  backend.agents.mission_control.cost -> backend.agents.mission_control.middleware, backend.core.logging
  backend.agents.mission_control.dispatch.result_builders -> backend.agents.mission_control.outcome, backend.schemas.task_plan
  backend.agents.mission_control.escalation -> backend.core.config, backend.core.logging
  backend.agents.mission_control.gate_prompt -> backend.agents.mission_control.gate_models, backend.core.logging
  backend.agents.mission_control.helpers.prompt_builder -> backend.core.config, backend.core.logging
  backend.agents.mission_control.history -> backend.core.logging, backend.schemas.session
  backend.agents.mission_control.models -> backend.core.protocols, backend.events.types
  backend.agents.system.synthesis.agent -> backend.agents.mission_control.helpers, backend.core.logging
  backend.api.health -> backend.core.logging, backend.core.utils
  backend.api.v1.endpoints.admin -> backend.core.dependencies, backend.schemas.base
  backend.api.v1.endpoints.missions_context -> backend.core.dependencies, backend.schemas.base
  backend.api.v1.endpoints.workshop -> backend.schemas.base, backend.core.dependencies
  backend.core.middleware -> backend.core.logging, backend.core.utils
  backend.events.publishers -> backend.core.logging, backend.events.schemas
  backend.events.types -> backend.core.logging, backend.core.utils
  backend.gateway.security.rate_limiter -> backend.core.config, backend.core.logging
  backend.models.api_key -> backend.models.base, backend.core.utils
  backend.models.session -> backend.core.utils, backend.models.base
  backend.repositories.agent_catalog -> backend.models.agent_catalog, backend.repositories.base
  backend.repositories.mission -> backend.models.mission, backend.repositories.base
  backend.repositories.mission_context -> backend.models.mission_context, backend.repositories.base
  backend.repositories.mission_history -> backend.models.mission_history, backend.repositories.base
  backend.repositories.mission_plan -> backend.models.mission_plan, backend.repositories.base
  backend.repositories.mission_team -> backend.models.mission_team, backend.repositories.base
  backend.repositories.note -> backend.models.note, backend.repositories.base
  backend.repositories.prompt_version -> backend.models.prompt_version, backend.repositories.base
  backend.repositories.workflow_definition -> backend.models.workflow_definition, backend.repositories.base
  backend.repositories.workflow_schedule -> backend.models.workflow_schedule, backend.repositories.base
  backend.services.base -> backend.core.exceptions, backend.core.logging
  backend.services.code_map.assembler -> backend.core.utils, backend.services.code_map.types
  backend.services.container_backend -> backend.core.logging, backend.services.execution_environment
  backend.services.context_curator -> backend.core.logging, backend.services.mission_context
  backend.services.pqi.dimensions -> backend.services.pqi.dimensions.analysis, backend.services.pqi.dimensions.style
  backend.services.pqi.tools.bandit -> backend.core.logging, backend.services.pqi.tools
  backend.services.run_notifier -> backend.core.config, backend.core.logging
  backend.services.synthesis -> backend.agents.mission_control.helpers, backend.core.logging
  backend.tasks.example -> backend.core.logging, backend.core.utils
  backend.tasks.scheduled -> backend.core.logging, backend.core.utils
  backend.tasks.workflow_scheduler -> backend.core.logging, backend.core.utils
  backend.temporal.activities -> backend.core.logging, backend.temporal.models
  backend.temporal.client -> backend.core.config, backend.core.logging
  clients.cli.cli_context -> backend.core.config, backend.core.logging
  clients.cli.mc_chat -> clients.common.display, clients.common.event_rendering
  clients.cli.mc_status -> clients.cli.report, clients.common.display
  clients.cli.mc_team -> clients.cli.report, clients.common.display
  clients.telegram.handlers.common -> backend.core.logging, clients.telegram.keyboards.common
  clients.telegram.handlers.setup -> clients.telegram.handlers.common, clients.telegram.handlers.example
  clients.telegram.middlewares.rate_limit -> backend.core.config, backend.core.logging
  clients.telegram.webhook -> backend.core.config, backend.core.logging
  clients.tui.messages -> backend.agents.mission_control.gate, backend.events.types
  clients.tui.screens.catalog -> backend.core.logging, clients.common.gate_helpers
  clients.tui.screens.dashboard -> backend.core.logging, clients.common.gate_helpers
  clients.tui.screens.mission_history -> clients.common.gate_helpers, clients.tui.widgets.context_viewer
  clients.tui.services.gate_reviewer -> backend.agents.mission_control.gate, clients.tui.messages
  clients.tui.tabs.runs -> backend.core.logging, clients.common.gate_helpers
  clients.tui.tabs.team -> backend.core.logging, clients.tui.widgets.prompt_editor
  clients.tui.tabs.workflows -> backend.core.logging, clients.tui.widgets.dag_renderer
  clients.tui.widgets.catalog_browse_modal -> backend.core.logging, clients.common.gate_helpers
  clients.tui.widgets.event_stream -> backend.events.types, clients.common.event_rendering
  backend.agents.deps -> backend.agents.deps.base
  backend.agents.deps.base -> backend.agents.config_schema
  backend.agents.mission.director.deps -> backend.agents.deps.base
  backend.agents.mission.workflow.deps -> backend.agents.deps.base
  backend.agents.mission_control -> backend.agents.mission_control.mission_control
  backend.agents.mission_control.check_registry -> backend.core.logging
  backend.agents.mission_control.checks -> backend.agents.mission_control.checks.builtin
  backend.agents.mission_control.dispatch.dag -> backend.schemas.task_plan
  backend.agents.mission_control.dispatch.environment -> backend.core.logging
  backend.agents.mission_control.roster -> backend.core.logging
  backend.agents.platform.director.deps -> backend.agents.deps.base
  backend.agents.tools.code -> backend.agents.deps.base
  backend.agents.tools.codemap -> backend.agents.deps.base
  backend.agents.tools.environment -> backend.core.logging
  backend.agents.tools.filesystem -> backend.agents.deps.base
  backend.agents.tools.system -> backend.agents.deps.base
  backend.agents.tools.workflow_design -> backend.core.logging
  backend.api.v1 -> backend.api.v1.endpoints
  backend.core.config -> backend.core.config_schema
  backend.core.database -> backend.core.logging
  backend.core.idempotency -> backend.core.logging
  backend.core.logging -> backend.core.config
  backend.core.pagination -> backend.schemas.base
  backend.events.broker -> backend.core.logging
  backend.events.middleware -> backend.core.logging
  backend.events.schemas -> backend.core.utils
  backend.gateway.adapters -> backend.gateway.adapters.base
  backend.gateway.adapters.base -> backend.core.utils
  backend.migrations.versions.20260321_phase3_users_and_api_keys -> backend.core.utils
  backend.models.agent_catalog -> backend.models.base
  backend.models.base -> backend.core.utils
  backend.models.execution -> backend.models.base
  backend.models.execution_environment -> backend.models.base
  backend.models.execution_record -> backend.models.base
  backend.models.mission -> backend.models.base
  backend.models.mission_context -> backend.models.base
  backend.models.mission_history -> backend.models.base
  backend.models.mission_plan -> backend.models.base
  backend.models.mission_team -> backend.models.base
  backend.models.note -> backend.models.base
  backend.models.prompt_version -> backend.models.base
  backend.models.user -> backend.models.base
  backend.models.workflow_definition -> backend.models.base
  backend.models.workflow_schedule -> backend.models.base
  backend.repositories -> backend.repositories.base
  backend.schemas -> backend.schemas.base
  backend.schemas.auth -> backend.schemas.user
  backend.schemas.base -> backend.core.utils
  backend.schemas.mission_plan -> backend.models.mission_plan
  backend.services.branch_manager -> backend.core.logging
  backend.services.code_map.graph -> backend.services.code_map.types
  backend.services.code_map.loader -> backend.core.logging
  backend.services.code_map.parser -> backend.services.code_map.types
  backend.services.code_map.ranker -> backend.services.code_map.types
  backend.services.compliance -> backend.core.logging
  backend.services.database_admin -> backend.core.logging
  backend.services.execution_environment -> backend.core.logging
  backend.services.health -> backend.core.logging
  backend.services.pqi -> backend.services.pqi.scorer
  backend.services.pqi.composite -> backend.services.pqi.types
  backend.services.pqi.tools -> backend.services.pqi.tools.runner
  backend.services.pqi.tools.radon -> backend.services.pqi.tools
  backend.tasks.broker -> backend.core.logging
  backend.tasks.scheduler -> backend.core.logging
  backend.temporal.workflow -> backend.temporal.models
  clients.cli.admin_cmds -> clients.cli.report
  clients.cli.agent -> backend.core.logging
  clients.cli.architect_cmds -> clients.cli.report
  clients.cli.catalog_cmds -> clients.cli.report
  clients.cli.db -> backend.core.logging
  clients.cli.execution_cmds -> backend.core.logging
  clients.cli.mc_run -> clients.common.display
  clients.cli.migrate -> backend.core.config
  clients.cli.mission_context -> backend.core.logging
  clients.cli.schedule_cmds -> clients.cli.report
  clients.cli.server -> backend.core.config
  clients.cli.telegram -> backend.core.config
  clients.cli.workflow_cmds -> backend.core.logging
  clients.cli.workshop_cmds -> clients.cli.report
  clients.common.event_rendering -> backend.events.types
  clients.common.gate_helpers -> backend.agents.mission_control.gate
  clients.telegram -> clients.telegram.bot
  clients.telegram.bot -> backend.core.logging
  clients.telegram.callbacks -> clients.telegram.callbacks.common
  clients.telegram.keyboards -> clients.telegram.keyboards.common
  clients.telegram.keyboards.common -> clients.telegram.callbacks.common
  clients.telegram.middlewares.logging -> backend.core.logging
  clients.telegram.services -> clients.telegram.services.notifications
  clients.telegram.states -> clients.telegram.states.example
  clients.tui -> clients.tui.app
  clients.tui.screens.admin -> backend.core.logging
  clients.tui.screens.mission_picker -> clients.tui.messages
  clients.tui.screens.profile -> backend.core.logging
  clients.tui.tabs.chat -> backend.core.logging
  clients.tui.tabs.context -> backend.core.logging
  clients.tui.tabs.workshop -> backend.core.logging
  clients.tui.widgets.chat_input -> clients.tui.messages
  clients.tui.widgets.context_viewer -> clients.common.gate_helpers
  clients.tui.widgets.cost_bar -> clients.common.gate_helpers
  clients.tui.widgets.dag_renderer -> clients.common.gate_helpers
  clients.tui.widgets.workflow_progress -> clients.common.gate_helpers

## backend.core

modules/backend/core/config.py (310 lines):
│class AppConfig:
│    def __init__() -> None
│    def application() -> ApplicationSchema
│    def database() -> DatabaseSchema
│    def logging() -> LoggingSchema
│    def features() -> FeaturesSchema
│    def security() -> SecuritySchema
│    def gateway() -> GatewaySchema
│    def events() -> EventsSchema
│    def sessions() -> SessionsSchema
│    def executions() -> ExecutionsSchema
│    def temporal() -> TemporalSchema
│    def workflows() -> WorkflowsSchema
│    def missions() -> MissionsSchema
│    def gate() -> GateSchema
│    def notifications() -> NotificationsSchema
│class Settings(BaseSettings):
│    db_password: str
│    redis_password: str
│    jwt_secret: str
│    api_key_salt: str
│    telegram_bot_token: str
│    telegram_webhook_secret: str
│    anthropic_api_key: str
│    admin_api_key: str
│def find_project_root() -> Path
│def validate_project_root() -> Path
│def load_yaml_config(filename: str) -> dict[str, Any]
│def _load_validated(schema_cls: type, filename: str) -> Any
│def _load_validated_optional(schema_cls: type, filename: str) -> Any
│@lru_cache
│def get_settings() -> Settings
│@lru_cache
│def get_app_config() -> AppConfig
│def get_database_url(async_driver: bool) -> str
│def get_redis_url() -> str
│def get_sanitized_config_view() -> dict
│def get_server_base_url() -> tuple[str, float]

modules/backend/core/logging.py (266 lines):
│def _load_logging_config() -> dict[str, Any]
│def _get_logging_config() -> dict[str, Any]
│def _resolve_log_path(configured_path: str) -> Path
│def setup_logging(level: str | None, format_type: str | None, enable_console: bool | None, ...) -> None
│def get_logger(name: str) -> Any
│def log_with_source(logger: Any, source: str, level: str, ...) -> None
│def bind_context() -> None
│def clear_context() -> None

modules/backend/core/config_schema.py (454 lines):
│class FeaturesSchema(_StrictBase):
│    auth_require_email_verification: bool
│    auth_allow_api_key_creation: bool
│    auth_rate_limit_enabled: bool
│    auth_require_api_authentication: bool
│    auth_allow_self_registration: bool
│    api_detailed_errors: bool
│    api_request_logging: bool
│    channel_telegram_enabled: bool
│    channel_slack_enabled: bool
│    channel_discord_enabled: bool
│    channel_whatsapp_enabled: bool
│    gateway_enabled: bool
│    gateway_websocket_enabled: bool
│    gateway_pairing_enabled: bool
│    agent_coordinator_enabled: bool
│    agent_streaming_enabled: bool
│    mcp_enabled: bool
│    a2a_enabled: bool
│    security_startup_checks_enabled: bool
│    security_headers_enabled: bool
│    security_cors_enforce_production: bool
│    experimental_background_tasks_enabled: bool
│    events_publish_enabled: bool
│class SecuritySchema(_StrictBase):
│    jwt: JwtSchema
│    rate_limiting: RateLimitingSchema
│    request_limits: RequestLimitsSchema
│    headers: SecurityHeadersSchema
│    secrets_validation: SecretsValidationSchema
│    roles: dict[str, RoleSchema]
│    user_roles: dict[str, str]
│    cors: CorsEnforcementSchema
│class ApplicationSchema(_StrictBase):
│    name: str
│    version: str
│    description: str
│    environment: str
│    debug: bool
│    api_prefix: str
│    docs_enabled: bool
│    server: ServerSchema
│    cors: CorsSchema
│    pagination: PaginationSchema
│    timeouts: TimeoutsSchema
│    telegram: TelegramAppSchema
│    cli: CliSchema
│class DatabaseSchema(_StrictBase):
│    host: str
│    port: int
│    name: str
│    user: str
│    pool_size: int
│    max_overflow: int
│    pool_timeout: int
│    pool_recycle: int
│    echo: bool
│    echo_pool: bool
│    redis: RedisSchema
│class LoggingSchema(_StrictBase):
│    level: str
│    format: str
│    handlers: HandlersSchema
│class GatewaySchema(_StrictBase):
│    default_policy: str
│    channels: dict[str, GatewayChannelSchema]
│class EventsSchema(_StrictBase):
│    transport: str
│    channel_prefix: str
│    streams: dict[str, EventsStreamSchema]
│    consumer_timeout_ms: int
│    dlq_enabled: bool
│    dlq_prefix: str
│class SessionsSchema(_StrictBase):
│    default_ttl_hours: int
│    max_ttl_hours: int
│    default_cost_budget_usd: float
│    max_cost_budget_usd: float
│    cleanup_interval_minutes: int
│    budget_warning_threshold: float
│class ExecutionsSchema(_StrictBase):
│    max_thinking_trace_length: int
│    max_task_output_size_bytes: int
│    retention_days: int
│    default_page_size: int
│    max_page_size: int
│    persist_thinking_trace: bool
│    persist_verification_details: bool
│class TemporalSchema(_StrictBase):
│    enabled: bool
│    server_url: str
│    namespace: str
│    task_queue: str
│    workflow_execution_timeout_days: int
│    activity_start_to_close_seconds: int
│    activity_retry_max_attempts: int
│    approval_timeout_seconds: int
│    escalation_timeout_seconds: int
│    notification_timeout_seconds: int
│    budget_timeout_multiplier_seconds: int
│    min_activity_timeout_seconds: int
│    persistence_timeout_seconds: int
│    persistence_retry_max_attempts: int
│    execution_retry_max_attempts: int
│    execution_retry_initial_interval_seconds: int
│    execution_retry_max_interval_seconds: int
│    def _require_server_url_when_enabled() -> 'TemporalSchema'
│class WorkflowsSchema(_StrictBase):
│    workflows_dir: str
│    max_steps_per_workflow: int
│    max_context_size_bytes: int
│    default_step_timeout_seconds: int
│    default_budget_usd: float
│    max_budget_usd: float
│    max_concurrent_missions: int
│    enable_workflow_matching: bool
│    max_scheduled_runs_per_day: int
│    schedule_evaluation_interval_seconds: int
│    workshop: WorkshopSchema
│class NotificationsSchema(_StrictBase):
│    enabled: bool
│    budget_warning_threshold_pct: float
│    notify_on_completion: bool
│    notify_on_failure: bool
│    notify_channels: list[str]
│class MissionsSchema(_StrictBase):
│    default_budget_ceiling_usd: float | None
│    max_missions_per_owner: int
│    pcd_max_size_bytes: int
│    pcd_target_size_bytes: int
│    pcd_prune_threshold_pct: int
│    pcd_alert_threshold_pct: int
│    history_summarize_after_days: int
│    enable_context_assembly: bool
│class GateSchema(_StrictBase):
│    mode: _GateMode
│    ai: GateAiSchema
│    points: GatePointsSchema
│    auto_rules: GateAutoRulesSchema
│class RedisSchema(_StrictBase):
│    host: str
│    port: int
│    db: int
│    broker: BrokerSchema
│class HandlersSchema(_StrictBase):
│    console: ConsoleHandlerSchema
│    file: FileHandlerSchema
│class GatewayChannelSchema(_StrictBase):
│    allowlist: list[int]
│class EventsStreamSchema(_StrictBase):
│    maxlen: int
│    consumer_group: str
│class WorkshopSchema(_StrictBase):
│    max_cached_input_sets: int
│    default_budget_usd: float
│    max_budget_usd: float
│    cache_stale_days: int
│class BrokerSchema(_StrictBase):
│    queue_name: str
│    result_expiry_seconds: int
│class GatePointSchema(_StrictBase):
│    enabled: bool
│    mode: _GateMode | None
│class ConsoleHandlerSchema(_StrictBase):
│    enabled: bool
│class FileHandlerSchema(_StrictBase):
│    enabled: bool
│    path: str
│    rotation_when: Literal['S', 'M', 'H', 'D', 'midnight', 'W0', 'W1', 'W2', 'W3', 'W4', 'W5', 'W6']
│    rotation_interval: int
│    backup_count: int
│class GateAiSchema(_StrictBase):
│    model: str
│    temperature: float
│    max_tokens: int
│    budget_per_review_usd: float
│class GatePointsSchema(_StrictBase):
│    pre_dispatch: GatePointSchema
│    pre_layer: GatePointSchema
│    post_task: GatePointSchema
│    verification_failed: GatePointSchema
│    post_layer: GatePointSchema
│class GateAutoRulesSchema(_StrictBase):
│    cost_threshold_pct: int
│    max_tasks_per_layer: int
│    skip_post_task_on_pass: bool
│class ApiRateLimitSchema(_StrictBase):
│    requests_per_minute: int
│    requests_per_hour: int
│class ChannelRateLimitSchema(_StrictBase):
│    messages_per_minute: int
│    messages_per_hour: int
│class ServerSchema(_StrictBase):
│    host: str
│    port: int
│class CorsSchema(_StrictBase):
│    origins: list[str]
│class PaginationSchema(_StrictBase):
│    default_limit: int
│    max_limit: int
│class TimeoutsSchema(_StrictBase):
│    database: int
│    external_api: int
│    background: int
│class TelegramAppSchema(_StrictBase):
│    webhook_path: str
│    authorized_users: list[int]
│    max_message_length: int
│class CliSchema(_StrictBase):
│    console_width: int
│class JwtSchema(_StrictBase):
│    algorithm: str
│    access_token_expire_minutes: int
│    refresh_token_expire_days: int
│    audience: str
│class RateLimitingSchema(_StrictBase):
│    api: ApiRateLimitSchema
│    telegram: ChannelRateLimitSchema
│    websocket: ChannelRateLimitSchema
│class RequestLimitsSchema(_StrictBase):
│    max_body_size_bytes: int
│    max_header_size_bytes: int
│class SecurityHeadersSchema(_StrictBase):
│    x_content_type_options: str
│    x_frame_options: str
│    referrer_policy: str
│    hsts_enabled: bool
│    hsts_max_age: int
│class SecretsValidationSchema(_StrictBase):
│    jwt_secret_min_length: int
│    api_key_salt_min_length: int
│    webhook_secret_min_length: int
│class CorsEnforcementSchema(_StrictBase):
│    enforce_in_production: bool
│    allow_methods: list[str]
│    allow_headers: list[str]
│class RoleSchema(_StrictBase):
│    level: int
│    description: str
│class _StrictBase(BaseModel):

modules/backend/core/utils.py (37 lines):
│def estimate_tokens(data: Any) -> int
│def utc_now() -> datetime

modules/backend/core/exceptions.py (85 lines):
│class ApplicationError(Exception):
│    def __init__(message: str, code: str) -> None
│class NotFoundError(ApplicationError):
│    def __init__(message: str) -> None
│class ValidationError(ApplicationError):
│    def __init__(message: str, details: dict | None) -> None
│class AuthenticationError(ApplicationError):
│    def __init__(message: str) -> None
│class AuthorizationError(ApplicationError):
│    def __init__(message: str) -> None
│class ConflictError(ApplicationError):
│    def __init__(message: str) -> None
│class ExternalServiceError(ApplicationError):
│    def __init__(message: str) -> None
│class RateLimitError(ApplicationError):
│    def __init__(message: str) -> None
│class BudgetExceededError(ApplicationError):
│    def __init__(message: str, current_cost: float, budget: float) -> None
│class DatabaseError(ApplicationError):
│    def __init__(message: str) -> None

modules/backend/core/dependencies.py (182 lines):
│def get_request_id(x_request_id: str | None) -> str
│def get_event_bus()
│def get_current_user(db: DbSession, authorization: str | None, api_key: str | None) -> User
│def get_optional_user(db: DbSession, authorization: str | None, api_key: str | None) -> User | None
│def get_current_user_sse(db: DbSession, token: str | None, authorization: str | None) -> User
│def require_admin(user: CurrentUser) -> User
│def get_idempotency(idempotency_key: str | None) -> AsyncIterator[IdempotencyGuard | None]

modules/backend/core/protocols.py (64 lines):
│class SessionServiceProtocol(Protocol):
│    def get_session(session_id: str) -> Any
│    def enforce_budget(session_id: str, estimated_cost: float) -> None
│    def get_messages(session_id: str, limit: int, offset: int) -> tuple[list, int]
│    def update_cost(session_id: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None
│    def touch_activity(session_id: str) -> None
│    def add_message(session_id: str, data: Any) -> None
│class ExecutionDispatchProtocol(Protocol):
│    def execute(mission_brief: str, roster_ref: str, complexity_tier: str, upstream_context: dict | None, cost_ceiling_usd: float | None, session_id: str | None, mission_id: str | None, gate: object | None) -> dict

modules/backend/core/database.py (113 lines):
│def _create_engine() -> Any
│def get_engine() -> Any
│def get_session_factory() -> async_sessionmaker[AsyncSession]
│@asynccontextmanager
│def get_async_session() -> AsyncGenerator[AsyncSession, None]
│def get_db_session() -> AsyncGenerator[AsyncSession, None]

modules/backend/core/idempotency.py (108 lines):
│class IdempotencyGuard:
│    def __init__(redis: AsyncRedis, key: str) -> None
│    def get_cached_response() -> dict | None
│    def cache_response(response_data: dict, ttl: int) -> None

modules/backend/core/security.py (176 lines):
│def hash_password(password: str) -> str
│def verify_password(plain_password: str, hashed_password: str) -> bool
│def create_access_token(data: dict[str, Any], expires_delta: timedelta | None) -> str
│def create_refresh_token(data: dict[str, Any]) -> str
│def decode_token(token: str) -> dict[str, Any]
│def generate_api_key() -> tuple[str, str]
│def verify_api_key(plain_key: str, hashed_key: str) -> bool
│def check_role_level(user_role: str, minimum_role: str) -> bool
│def resolve_user_role_from_config(user_id: int) -> str

modules/backend/core/__init__.py (1 lines):

modules/backend/core/pagination.py (266 lines):
│class PaginationParams:
│    limit: int
│    offset: int
│    cursor: str | None
│    def is_cursor_based() -> bool
│class PagedResult:
│    items: list[T]
│    total: int | None
│    limit: int
│    offset: int
│    has_more: bool
│    next_cursor: str | None
│def get_pagination_params(limit: int | None, offset: int, cursor: str | None) -> PaginationParams
│def encode_cursor(value: str | int) -> str
│def decode_cursor(cursor: str) -> str
│def create_paginated_response(items: list[Any], item_schema: type[BaseModel], total: int | None, ...) -> dict[str, Any]
│def paginate_query(query_func, params: PaginationParams, count_func) -> PagedResult

modules/backend/core/exception_handlers.py (300 lines):
│def _get_request_id(request: Request) -> str | None
│def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse
│def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse
│def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse
│def _get_model_http_error() -> type
│def model_http_error_handler(request: Request, exc: Exception) -> JSONResponse
│def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse
│def register_exception_handlers(app: FastAPI) -> None

modules/backend/core/middleware.py (121 lines):
│class RequestContextMiddleware(BaseHTTPMiddleware):
│    def dispatch(request: Request, call_next: RequestResponseEndpoint) -> Response

modules/backend/__init__.py (1 lines):

modules/backend/main.py (128 lines):
│@asynccontextmanager
│def lifespan(app: FastAPI) -> AsyncGenerator[None, None]
│def create_app() -> FastAPI
│def _mount_channel_adapters(app: FastAPI, app_config) -> None
│def get_app() -> FastAPI
│def __getattr__(name: str) -> FastAPI


## backend.agents

modules/backend/agents/mission_control/gate.py (282 lines):
│class LlmGateReviewer:
│    def __init__(model: str, temperature: float, max_tokens: int)
│    def _get_agent()
│    def review(context: GateContext) -> GateDecision
│class ConfigurableGate:
│    def __init__(config: Any, console: Any, verbose: bool)
│    def _get_llm() -> LlmGateReviewer
│    def _get_cli()
│    def _effective_mode(gate_type: str) -> str
│    def _is_enabled(gate_type: str) -> bool
│    def _should_auto_continue(context: GateContext) -> bool
│    def review(context: GateContext) -> GateDecision
│def create_gate(mode_override: str | None, console: Any, verbose: bool) -> GateReviewer | None

modules/backend/agents/config_schema.py (310 lines):
│class _StrictBase(BaseModel):
│class AgentConfigSchema(_StrictBase):
│    agent_name: str
│    agent_type: str
│    description: str
│    enabled: bool
│    model: str | AgentModelSchema
│    keywords: list[str]
│    tools: list[str]
│    max_input_length: int
│    max_budget_usd: float
│    execution: ExecutionSchema
│    invocation: InvocationSchema
│    scope: FileScopeConfigSchema
│    interface: AgentInterfaceSchema | None
│    version: str
│    max_tokens: int | None
│    max_requests: int | None
│    file_size_limit: int | None
│    rules: list[ComplianceRuleSchema] | None
│    exclusions: ExclusionsSchema | None
│    chat_enabled: bool
│    thinking_budget: dict[str, int] | None
│    def _normalize_model(v: str | dict) -> str | dict
│    def _validate_model_config() -> Self
│    def _validate_invocation_tier() -> Self
│class FileScopeConfigSchema(_StrictBase):
│    read: list[str]
│    write: list[str]
│class InvocationSchema(_StrictBase):
│    tier: Literal['user', 'platform', 'system']
│    required_role: Literal['admin', 'user'] | None
│class ExecutionSchema(_StrictBase):
│    mode: str
│    prefer: Literal['local', 'worktree', 'container'] | None
│    template: str | None
│class ComplianceRuleSchema(_StrictBase):
│    id: str
│    description: str
│    severity: str
│    enabled: bool
│class ExclusionsSchema(_StrictBase):
│    paths: list[str]
│    patterns: list[str]
│class AgentInterfaceSchema(_StrictBase):
│    input: dict[str, str]
│    output: dict[str, str]
│class MissionControlConfigSchema(_StrictBase):
│    model_pricing: dict[str, ModelPricingRateSchema]
│    routing: RoutingSchema
│    limits: MissionControlLimitsSchema
│    guardrails: GuardrailsSchema
│    redis_ttl: RedisTtlSchema
│    approval: ApprovalSchema
│    dispatch: DispatchSchema
│    escalation: EscalationThresholdsSchema
│class ModelPricingRateSchema(_StrictBase):
│    input: float
│    output: float
│class RoutingSchema(_StrictBase):
│    strategy: str
│    llm_model: str
│    complex_request_agent: str
│    fallback_agent: str
│    chat_agent: str
│    max_routing_depth: int
│class MissionControlLimitsSchema(_StrictBase):
│    max_requests_per_task: int
│    max_tool_calls_per_task: int
│    max_tokens_per_task: int
│    max_cost_per_plan: float
│    max_cost_per_user_daily: float
│    task_timeout_seconds: int
│    plan_timeout_seconds: int
│class GuardrailsSchema(_StrictBase):
│    max_input_length: int
│    injection_patterns: list[str]
│class RedisTtlSchema(_StrictBase):
│    session: int
│    approval: int
│    lock: int
│    result: int
│class ApprovalSchema(_StrictBase):
│    poll_interval_seconds: int
│    timeout_seconds: int
│class DispatchSchema(_StrictBase):
│    default_request_limit: int
│    token_cost_factor: int
│    context_token_budget: int
│    history_reserve_tokens: int
│class EscalationThresholdsSchema(_StrictBase):
│    max_auto_approve_cost_usd: float
│    max_medium_approve_cost_usd: float
│    max_auto_approve_retries: int
│class AgentModelSchema(_StrictBase):
│    name: str
│    temperature: float
│    max_tokens: int

modules/backend/agents/deps/base.py (90 lines):
│class FileScope:
│    read_paths: list[str]
│    write_paths: list[str]
│    def check_read(rel_path: str) -> None
│    def check_write(rel_path: str) -> None
│    def is_readable(rel_path: str) -> bool
│    def _matches(rel_path: str, allowed: list[str]) -> bool
│class BaseAgentDeps:
│    project_root: Path
│    scope: FileScope
│    config: AgentConfigSchema | None
│    session_id: str | None
│    on_event: Any
│    environment_handle: Any
│class QaAgentDeps(BaseAgentDeps):
│    on_progress: Any
│    def emit(event: dict) -> None
│class HealthAgentDeps(BaseAgentDeps):
│    app_config: Any
│class HorizontalAgentDeps(BaseAgentDeps):
│    allowed_agents: set[str]
│    max_delegation_depth: int
│    mission_control: Any

modules/backend/agents/mission_control/gate_models.py (84 lines):
│class GateContext:
│    gate_type: str
│    mission_id: str
│    layer_index: int
│    total_layers: int
│    pending_tasks: list[dict]
│    task_id: str | None
│    task_result: dict | None
│    task_output: dict | None
│    verification: dict | None
│    completed_tasks: list[dict]
│    total_cost_usd: float
│    budget_usd: float
│    current_instructions: str | None
│    current_inputs: dict | None
│    ai_recommendation: Any
│class GateAction(str, Enum):
│class GateDecision:
│    action: GateAction
│    reason: str | None
│    modified_inputs: dict | None
│    modified_instructions: str | None
│    reviewer: str
│class GateReviewer(Protocol):
│    def review(context: GateContext) -> GateDecision
│class NoOpGate:
│    def review(context: GateContext) -> GateDecision

modules/backend/agents/mission_control/helpers/__init__.py (64 lines):

modules/backend/agents/mission_control/gate_prompt.py (153 lines):
│def _build_gate_prompt(context: GateContext) -> str
│def _parse_action(action_str: str) -> GateAction

modules/backend/agents/mission_control/models.py (154 lines):
│class EventBusProtocol(Protocol):
│    def publish(event: SessionEvent) -> None
│    def publish_to_mission(mission_id: str, event: SessionEvent) -> None
│class ExecuteAgentFn(Protocol):
│    def __call__(agent_name: str, instructions: str, inputs: dict, usage_limits: UsageLimits) -> Awaitable[dict]
│class ContextCuratorProtocol(Protocol):
│    def get_mission_context(mission_id: str) -> dict
│    def apply_task_updates(mission_id: str, task_result_context_updates: list[dict]) -> tuple[int, list[str]]
│class ContextAssemblerProtocol(Protocol):
│    def build(mission_id: str, task_definition: dict, resolved_inputs: dict) -> dict
│class MissionControlRequest:
│    user_input: str
│    agent: str | None
│    conversation_id: str | None
│    channel: str
│    session_type: str
│    tool_access_level: str
│class CollectResult(TypedDict):
│    agent_name: str
│    output: str
│    cost_usd: float
│    session_id: str
│    thinking: str | None
│class MissionControlResponse:
│    agent_name: str
│    output: str
│    metadata: dict[str, Any]
│class NoOpEventBus:
│    def publish(event: SessionEvent) -> None
│    def publish_to_mission(mission_id: str, event: SessionEvent) -> None

modules/backend/agents/mission_control/outcome.py (230 lines):
│class TaskResult(BaseModel):
│    task_id: str
│    agent_name: str
│    status: TaskStatus
│    output_reference: dict
│    token_usage: TaskTokenUsage
│    cost_usd: float
│    duration_seconds: float
│    verification_outcome: VerificationOutcome
│    retry_count: int
│    retry_history: list[RetryHistoryEntry]
│    execution_id: str
│    context_updates: list[dict]
│    skip_reason: str | None
│class ExecutionOutcome(BaseModel):
│    mission_id: str
│    status: ExecutionStatus
│    summary: str
│    task_results: list[TaskResult]
│    total_cost_usd: float
│    total_duration_seconds: float
│    total_tokens: TaskTokenUsage
│    abort_reason: str | None
│    planning_trace_reference: str | None
│    task_plan_reference: str | None
│    gate_decisions: list[GateDecisionRecord]
│    execution_record_id: str | None
│class TaskTokenUsage(BaseModel):
│    input: int
│    output: int
│    thinking: int
│class RetryHistoryEntry(BaseModel):
│    attempt: int
│    failure_tier: int
│    failure_reason: str
│    feedback_provided: str
│class VerificationOutcome(BaseModel):
│    tier_1: Tier1Outcome
│    tier_2: Tier2Outcome
│    tier_3: Tier3Outcome
│class TaskStatus(StrEnum):
│class FailedCheck(BaseModel):
│    check: str
│    reason: str
│class GateDecisionRecord(BaseModel):
│    gate_type: str
│    layer_index: int
│    task_id: str | None
│    action: str
│    reason: str | None
│    reviewer: str
│class ExecutionStatus(StrEnum):
│class Tier1Outcome(BaseModel):
│    status: str
│    details: str
│class Tier2Outcome(BaseModel):
│    status: str
│    checks_run: int
│    checks_passed: int
│    failed_checks: list[FailedCheck]
│class Tier3Outcome(BaseModel):
│    status: str
│    overall_score: float
│    criteria_results_reference: str
│    evaluator_thinking_trace_reference: str
│    cost_usd: float
│def build_verification_outcome(result: VerificationResult) -> VerificationOutcome

modules/backend/agents/mission_control/registry.py (189 lines):
│class AgentRegistry:
│    def __init__() -> None
│    def _ensure_loaded() -> None
│    def get(agent_name: str) -> AgentConfigSchema
│    def has(agent_name: str) -> bool
│    def list_all(tier: str | None) -> list[dict[str, Any]]
│    def list_system() -> list[dict[str, Any]]
│    def get_by_keyword(text: str) -> str | None
│    def resolve_module_path(agent_name: str) -> str
│    def get_instance(agent_name: str, model: Any) -> Any
│    def reset() -> None
│@lru_cache
│def get_registry() -> AgentRegistry

modules/backend/agents/mission_control/roster.py (187 lines):
│class RosterAgentEntry(BaseModel):
│    agent_name: str
│    agent_version: str
│    description: str
│    model: RosterModelSchema
│    tools: list[str]
│    interface: RosterInterfaceSchema
│    constraints: RosterConstraintsSchema
│class Roster(BaseModel):
│    agents: list[RosterAgentEntry]
│    def get_agent(name: str, version: str) -> RosterAgentEntry | None
│    def get_agent_by_name(name: str) -> RosterAgentEntry | None
│    def agent_names() -> list[str]
│class RosterModelSchema(BaseModel):
│    name: str
│    temperature: float
│    max_tokens: int
│class RosterInterfaceSchema(BaseModel):
│    input: dict[str, str]
│    output: dict[str, str]
│class RosterConstraintsSchema(BaseModel):
│    timeout_seconds: int
│    cost_ceiling_usd: float
│    retry_budget: int
│    parallelism: str
│def derive_roster_from_team(mission_id: str, session: 'AsyncSession') -> Roster

modules/backend/agents/mission_control/middleware.py (74 lines):
│@lru_cache
│def _load_mission_control_config() -> MissionControlConfigSchema
│def check_guardrails(user_input: str, agent_config: AgentConfigSchema | None) -> None
│def with_guardrails(agent_config: AgentConfigSchema | None)

modules/backend/agents/mission_control/mission_control.py (827 lines):
│def list_agents() -> list[dict[str, Any]]
│def _prepend_mission_context(mission_id: str, message: str) -> str
│def handle(session_id: str, message: str) -> AsyncIterator[SessionEvent]
│def collect(session_id: str, message: str) -> CollectResult
│def handle_mission(mission_run_id: str, mission_brief: str) -> ExecutionOutcome

modules/backend/agents/mission_control/check_registry.py (85 lines):
│class CheckResult:
│    passed: bool
│    details: str
│    execution_time_ms: float
│def register_check(name: str) -> Callable[[CheckFn], CheckFn]
│def get_check(name: str) -> CheckFn | None
│def check_exists(name: str) -> bool
│def list_checks() -> list[str]
│def get_registry_snapshot() -> dict[str, CheckFn]

modules/backend/agents/mission_control/checks/builtin.py (226 lines):
│@register_check
│def validate_json_schema(output: dict[str, Any], params: dict[str, Any]) -> CheckResult
│@register_check
│def validate_field_exists(output: dict[str, Any], params: dict[str, Any]) -> CheckResult
│@register_check
│def validate_field_type(output: dict[str, Any], params: dict[str, Any]) -> CheckResult
│@register_check
│def validate_field_range(output: dict[str, Any], params: dict[str, Any]) -> CheckResult
│def _elapsed_ms(start: float) -> float

modules/backend/agents/mission_control/helpers/agent_setup.py (98 lines):
│def build_deps_from_config(agent_config: AgentConfigSchema) -> dict[str, Any]
│def _build_agent_deps(agent_name: str, agent_config: AgentConfigSchema, session_id: str | None, ...) -> BaseAgentDeps
│def _get_usage_limits(agent_name: str | None) -> UsageLimits
│def _import_agent_module(agent_name: str) -> Any

modules/backend/agents/mission_control/helpers/event_emitter.py (124 lines):
│def _publish(event_bus: EventBusProtocol, event: SessionEvent) -> None
│def _emit(event_bus: EventBusProtocol, event_cls: type[SessionEvent]) -> None
│def _emit_tool_events(event_bus: EventBusProtocol, stream: Any) -> tuple[list[str], list[SessionEvent]]
│def _persist_messages(session_service: 'SessionServiceProtocol', session_id: str, creates: list[SessionMessageCreate]) -> None

modules/backend/agents/mission_control/helpers/model_builder.py (93 lines):
│def build_model_settings(agent_config: AgentConfigSchema) -> 'ModelSettings | None'
│def _build_model(config_model: str | AgentModelSchema) -> Model
│def _get_model_name(config_model: str | AgentModelSchema) -> str

modules/backend/agents/mission_control/helpers/prompt_builder.py (184 lines):
│def assemble_instructions(category: str, name: str) -> str
│def _build_roster_prompt(roster: 'Roster') -> str
│def _build_planning_prompt(mission_brief: str, mission_id: str, roster_description: str, ...) -> str
│def _append_validation_feedback(prompt: str, errors: list[str]) -> str

modules/backend/agents/mission_control/helpers/agent_executor.py (313 lines):
│def _make_agent_executor(event_bus: EventBusProtocol) -> ExecuteAgentFn
│def _call_planning_agent(prompt: str, roster: 'Roster', upstream_context: dict | None, ...) -> dict

modules/backend/agents/mission_control/helpers/routing.py (49 lines):
│def _resolve_agent(session: 'SessionResponse', message: str) -> str
│def get_chat_agent() -> str

modules/backend/agents/tools/__init__.py (1 lines):

modules/backend/agents/mission_control/verification_models.py (48 lines):
│class TierStatus(str, Enum):
│class TierResult:
│    tier: int
│    status: TierStatus
│    details: str
│    execution_time_ms: float
│    check_results: list[dict[str, Any]]
│class VerificationResult:
│    passed: bool
│    tier_1: TierResult | None
│    tier_2: TierResult | None
│    tier_3: TierResult | Tier3Result | None
│    failed_tier: int | None
│    total_execution_time_ms: float
│class Tier3Result(TierResult):
│    overall_score: float
│    criteria_results_reference: str
│    evaluator_thinking_trace_reference: str
│    cost_usd: float

modules/backend/agents/mission_control/dispatch/step_executor.py (164 lines):
│def execute_task(task: TaskDefinition, roster_entry: RosterAgentEntry, resolved_inputs: dict[str, Any], ...) -> dict
│def verify_task(task: TaskDefinition, output: dict, roster_entry: RosterAgentEntry, ...) -> VerificationResult
│def execute_with_step_events(task: TaskDefinition, roster_entry: RosterAgentEntry, resolved_inputs: dict[str, Any], ...) -> TaskResult

modules/backend/agents/schemas.py (92 lines):
│class PqiDimensionScore(BaseModel):
│    score: float
│    confidence: float
│    sub_scores: dict[str, float]
│class PqiScore(BaseModel):
│    composite: float
│    quality_band: str
│    dimensions: dict[str, PqiDimensionScore]
│    file_count: int
│    line_count: int
│class ArchitectureFinding(BaseModel):
│    principle: str
│    file: str
│    line: int | None
│    message: str
│    recommendation: str
│    related_files: list[str]
│class HealthFinding(BaseModel):
│    category: str
│    severity: str
│    message: str
│    details: str | None
│class QaAuditResult(BaseModel):
│    summary: str
│    total_violations: int
│    error_count: int
│    warning_count: int
│    violations: list[Violation]
│    scanned_files_count: int
│    pqi: PqiScore | None
│class ArchitectureReviewResult(BaseModel):
│    summary: str
│    total_findings: int
│    findings: list[ArchitectureFinding]
│    files_reviewed: int
│    new_findings: int
│    baseline_findings: int
│class HealthCheckResult(BaseModel):
│    summary: str
│    overall_status: str
│    findings: list[HealthFinding]
│    error_count: int
│    warning_count: int
│    checks_performed: list[str]
│class Violation(BaseModel):
│    rule_id: str
│    file: str
│    line: int | None
│    message: str
│    severity: str
│    recommendation: str | None

modules/backend/agents/mission_control/dispatch/dag.py (74 lines):
│def topological_sort(plan: TaskPlan) -> list[list[str]]
│def resolve_upstream_inputs(task: TaskDefinition, completed_outputs: dict[str, dict]) -> dict[str, Any]

modules/backend/agents/mission_control/dispatch/loop.py (487 lines):
│def dispatch(plan: TaskPlan, roster: Roster, execute_agent_fn: ExecuteAgentFn, ...) -> ExecutionOutcome
│def _load_project_context(mission_id: str | None, context_curator: ContextCuratorProtocol | None) -> dict | None
│def _execute_layer(plan: TaskPlan, layer: list[str], layer_idx: int, ...) -> dict | None
│def _inject_context(resolved_inputs: dict[str, Any], task: Any, mission_id: str | None, ...) -> None
│def _build_outcome(plan: TaskPlan, task_results: list[TaskResult], total_cost: float, ...) -> ExecutionOutcome

modules/backend/agents/mission_control/cost.py (37 lines):
│def compute_cost_usd(input_tokens: int, output_tokens: int, model: str | None) -> float
│def estimate_cost(estimated_input_tokens: int, model: str | None) -> float

modules/backend/agents/mission/director/deps.py (20 lines):
│class MissionDirectorDeps(BaseAgentDeps):
│    mission_id: str
│    db_session: Any

modules/backend/agents/platform/director/deps.py (18 lines):
│class PlatformDirectorDeps(BaseAgentDeps):
│    db_session: Any

modules/backend/agents/mission/workflow/deps.py (22 lines):
│class ArchitectAgentDeps(BaseAgentDeps):
│    mission_id: str
│    mission_brief: str
│    team_summary: str
│    db_session: Any

modules/backend/agents/mission_control/verification_tiers.py (322 lines):
│def _elapsed_ms(start: float) -> float
│def _run_tier_1(output: dict[str, Any], verification_config: dict[str, Any], agent_interface: dict[str, Any] | None) -> TierResult
│def _run_tier_2(output: dict[str, Any], verification_config: dict[str, Any]) -> TierResult
│def _run_tier_3(output: dict[str, Any], task: dict[str, Any], verification_config: dict[str, Any], ...) -> TierResult | Tier3Result

modules/backend/agents/mission_control/router.py (40 lines):
│class RuleBasedRouter:
│    def __init__(registry: AgentRegistry) -> None
│    def route(request: MissionControlRequest) -> str | None

modules/backend/agents/mission_control/dispatch/result_builders.py (89 lines):
│def append_feedback(original_instructions: str, feedback: str) -> str
│def aborted_outcome(plan: TaskPlan, reason: str | None, start_time: float, ...) -> ExecutionOutcome
│def skipped_result(task: TaskDefinition, reason: str | None, execution_id: str) -> TaskResult
│def failed_result(task: TaskDefinition, reason: str, retry_count: int, ...) -> TaskResult

modules/backend/agents/mission_control/verification.py (173 lines):
│def run_verification_pipeline(output: dict[str, Any], task: dict[str, Any], agent_interface: dict[str, Any] | None, ...) -> VerificationResult
│def build_retry_feedback(verification_result: VerificationResult, attempt: int) -> dict[str, Any]

modules/backend/agents/mission_control/dispatch/__init__.py (19 lines):

modules/backend/agents/mission/workflow/agent.py (229 lines):
│def create_agent(model: str | Model) -> Agent
│def run_conversational(agent: Agent, deps: ArchitectAgentDeps, message: str) -> dict[str, Any]

modules/backend/agents/mission_control/history.py (169 lines):
│def session_messages_to_model_history(messages: list) -> list[ModelMessage]
│def model_messages_to_session_creates(messages: list[ModelMessage], session_id: str, agent_id: str | None, ...) -> list[SessionMessageCreate]

modules/backend/agents/mission_control/persistence_bridge.py (139 lines):
│def persist_mission_results(outcome: ExecutionOutcome) -> str | None

modules/backend/agents/mission_control/plan_validator.py (286 lines):
│class ValidationResult:
│    def __init__() -> None
│    def is_valid() -> bool
│    def add_error(rule: str, message: str) -> None
│    def __repr__() -> str
│def validate_plan(plan: TaskPlan, roster: Roster, mission_budget_usd: float) -> ValidationResult
│def _rule_2_agent_validation(plan: TaskPlan, roster: Roster, result: ValidationResult) -> None
│def _rule_3_dag_validation(plan: TaskPlan, result: ValidationResult) -> None
│def _rule_4_dependency_consistency(plan: TaskPlan, result: ValidationResult) -> None
│def _rule_5_input_compatibility(plan: TaskPlan, roster: Roster, result: ValidationResult) -> None
│def _rule_6_check_registry(plan: TaskPlan, result: ValidationResult) -> None
│def _rule_7_budget_validation(plan: TaskPlan, mission_budget_usd: float, result: ValidationResult) -> None
│def _rule_8_timeout_validation(plan: TaskPlan, roster: Roster, result: ValidationResult) -> None
│def _rule_9_critical_path_validation(plan: TaskPlan, result: ValidationResult) -> None
│def _rule_10_tier3_completeness(plan: TaskPlan, roster: Roster, result: ValidationResult) -> None
│def _rule_11_self_evaluation_prevention(plan: TaskPlan, result: ValidationResult) -> None

modules/backend/agents/__init__.py (1 lines):

modules/backend/agents/deps/__init__.py (17 lines):

modules/backend/agents/mission/__init__.py (0 lines):

modules/backend/agents/mission/director/__init__.py (0 lines):

modules/backend/agents/mission/director/agent.py (470 lines):
│def create_agent(model: str | Model) -> Agent

modules/backend/agents/mission/workflow/__init__.py (1 lines):

modules/backend/agents/mission_control/__init__.py (10 lines):

modules/backend/agents/mission_control/approval.py (54 lines):
│def request_approval(mission_id: str, task_id: str, action: str, ...) -> dict

modules/backend/agents/mission_control/checks/__init__.py (7 lines):

modules/backend/agents/mission_control/dispatch/convergence.py (441 lines):
│class ConvergenceConfig:
│    max_iterations: int
│    convergence_condition: str
│    convergence_threshold: float | None
│    commit_per_cycle: bool
│    final_verification: bool
│    evaluation_agent: str
│    remediation_agent: str
│    evaluation_config: dict[str, Any]
│    remediation_config: dict[str, Any]
│    def from_dict(data: dict[str, Any]) -> ConvergenceConfig
│class CycleResult:
│    cycle_number: int
│    findings_count: int
│    fixes_applied: int
│    convergence_metric: float | None
│    converged: bool
│    evaluation_result: TaskResult | None
│    remediation_result: TaskResult | None
│def execute_convergence_loop() -> TaskResult
│def _run_final_verification() -> TaskResult
│def _extract_findings_count(result: Any) -> int
│def _extract_fixes_count(result: Any) -> int
│def _extract_metric(result: Any, config: ConvergenceConfig) -> float | None
│def _check_convergence(condition: str, findings_count: int, metric: float | None, ...) -> bool
│def _to_task_result(task_id: str, agent_name: str, raw_result: Any) -> TaskResult

modules/backend/agents/mission_control/dispatch/environment.py (110 lines):
│def resolve_execution_mode() -> str
│def _validate_mode(mode: str, repo_root: str | None) -> str

modules/backend/agents/mission_control/dispatch/retry_handler.py (365 lines):
│def execute_with_retry(task: TaskDefinition, roster_entry: RosterAgentEntry, resolved_inputs: dict[str, Any], ...) -> TaskResult
│def _handle_verification_failure(task: TaskDefinition, output: dict, token_usage: TaskTokenUsage, ...) -> TaskResult | str
│def _handle_post_task_gate(task: TaskDefinition, output: dict, token_usage: TaskTokenUsage, ...) -> TaskResult | str

modules/backend/agents/mission_control/dispatch_adapter.py (122 lines):
│class MissionControlDispatchAdapter:
│    def __init__(session_service: SessionServiceProtocol, db_session: AsyncSession, event_bus: EventBusProtocol) -> None
│    def execute(mission_brief: str, roster_ref: str, complexity_tier: str, upstream_context: dict | None, cost_ceiling_usd: float | None, session_id: str | None, mission_id: str | None, gate: object | None, execution_mode: str | None) -> dict

modules/backend/agents/mission_control/escalation.py (231 lines):
│class EscalationLevel:
│    level: int
│    responder_type: str
│    timeout_seconds: int
│    description: str
│class RiskThresholds:
│    max_auto_approve_cost_usd: float
│    max_medium_approve_cost_usd: float
│    max_auto_approve_retries: int
│    allowed_retry_actions: frozenset[str]
│def _build_escalation_chain() -> list[EscalationLevel]
│def get_escalation_chain() -> list[EscalationLevel]
│def get_escalation_level(current_level: int) -> EscalationLevel | None
│def get_next_escalation(current_level: int) -> EscalationLevel | None
│def _get_thresholds() -> RiskThresholds
│def evaluate_automated_rules(action: str, context: dict) -> dict | None
│def evaluate_risk_matrix(action: str, context: dict) -> dict | None

modules/backend/agents/platform/__init__.py (0 lines):

modules/backend/agents/platform/director/__init__.py (0 lines):

modules/backend/agents/platform/director/agent.py (151 lines):
│def create_agent(model: str | Model) -> Agent

modules/backend/agents/platform/health/__init__.py (1 lines):

modules/backend/agents/platform/health/agent.py (128 lines):
│def create_agent(model: str | Model) -> Agent[HealthAgentDeps, HealthCheckResult]
│def run_agent(user_message: str, deps: HealthAgentDeps, agent: Agent[HealthAgentDeps, HealthCheckResult], ...) -> HealthCheckResult
│def run_agent_stream(user_message: str, deps: HealthAgentDeps, agent: Agent[HealthAgentDeps, HealthCheckResult], ...) -> AsyncGenerator[dict, None]

modules/backend/agents/preflight.py (106 lines):
│class ModelCheckResult:
│    model_name: str
│    ok: bool
│    elapsed_ms: float
│    error: str | None
│    error_type: str | None
│class PreflightResult:
│    ok: bool
│    checks: list[ModelCheckResult]
│    def failed() -> list[ModelCheckResult]
│def _ping_model(model_name: str) -> ModelCheckResult
│def preflight_check(roster_name: str, models: list[str] | None) -> PreflightResult

modules/backend/agents/software/__init__.py (0 lines):

modules/backend/agents/software/architecture/__init__.py (1 lines):

modules/backend/agents/software/architecture/agent.py (182 lines):
│def create_agent(model: str | Model) -> Agent[QaAgentDeps, ArchitectureReviewResult]
│def run_agent(user_message: str, deps: QaAgentDeps, agent: Agent[QaAgentDeps, ArchitectureReviewResult], ...) -> ArchitectureReviewResult
│def run_agent_stream(user_message: str, deps: QaAgentDeps, agent: Agent[QaAgentDeps, ArchitectureReviewResult], ...) -> AsyncGenerator[dict, None]

modules/backend/agents/software/quality/__init__.py (1 lines):

modules/backend/agents/software/quality/agent.py (325 lines):
│def create_agent(model: str | Model) -> Agent[QaAgentDeps, QaAuditResult]
│def pre_execute(user_message: str, deps: QaAgentDeps) -> tuple[str, PqiScore | None]
│def post_execute(output: QaAuditResult, hook_data: PqiScore | None) -> None
│def _compute_pqi(deps: QaAgentDeps) -> PqiScore | None
│def _format_pqi_for_llm(pqi: PqiScore) -> str
│def run_agent(user_message: str, deps: QaAgentDeps, agent: Agent[QaAgentDeps, QaAuditResult], ...) -> QaAuditResult
│def run_agent_stream(user_message: str, deps: QaAgentDeps, agent: Agent[QaAgentDeps, QaAuditResult], ...) -> AsyncGenerator[dict, None]

modules/backend/agents/system/__init__.py (0 lines):

modules/backend/agents/system/planning/__init__.py (1 lines):

modules/backend/agents/system/planning/agent.py (108 lines):
│class PlanningAgentDeps(BaseAgentDeps):
│    mission_brief: str
│    roster_description: str
│    upstream_context: dict[str, Any] | None
│    code_map: dict | None
│def create_agent(model: str | Model) -> Agent
│def run_agent(agent: Agent, deps: PlanningAgentDeps, user_prompt: str) -> dict
│def extract_task_plan_json(text: str) -> dict

modules/backend/agents/system/summarization/__init__.py (0 lines):

modules/backend/agents/system/summarization/agent.py (109 lines):
│class SummarizationOutput(BaseModel):
│    title: str
│    summary: str
│    key_outcomes: list[str]
│    domain_tags: list[str]
│@lru_cache
│def _get_agent() -> Agent[None, SummarizationOutput]
│def get_agent(model: Model | None) -> Agent[None, SummarizationOutput]
│def summarize_missions(mission_outcomes: list[dict]) -> dict[str, Any]

modules/backend/agents/system/synthesis/__init__.py (0 lines):

modules/backend/agents/system/synthesis/agent.py (65 lines):
│@lru_cache
│def _get_agent() -> Agent[None, str]
│def synthesize(outcome_data: dict[str, Any]) -> str

modules/backend/agents/system/verification/__init__.py (1 lines):

modules/backend/agents/system/verification/agent.py (105 lines):
│class CriterionResult(BaseModel):
│    criterion: str
│    score: float
│    passed: bool
│    evidence: str
│    issues: list[str]
│class VerificationEvaluation(BaseModel):
│    overall_score: float
│    passed: bool
│    criteria_results: list[CriterionResult]
│    blocking_issues: list[str]
│    recommendations: list[str]
│def create_agent(model: str | Model) -> Agent[BaseAgentDeps, VerificationEvaluation]
│def run_agent(user_message: str, deps: BaseAgentDeps, agent: Agent[BaseAgentDeps, VerificationEvaluation], ...) -> VerificationEvaluation

modules/backend/agents/tools/code.py (77 lines):
│def apply_fix(project_root: Path, file_path: str, old_text: str, ...) -> dict
│def run_tests(project_root: Path) -> dict

modules/backend/agents/tools/codemap.py (156 lines):
│def generate_code_map(project_root: Path, scope: FileScope) -> dict
│def load_code_map(project_root: Path, scope: FileScope) -> dict
│def get_dependency_analysis(project_root: Path, scope: FileScope) -> dict
│def run_quality_score(project_root: Path, scope: FileScope) -> dict

modules/backend/agents/tools/compliance.py (98 lines):
│def _get_scanner(project_root: Path, config: AgentConfigSchema) -> ComplianceScannerService
│def scan_imports(project_root: Path, scope: FileScope, config: AgentConfigSchema) -> list[dict]
│def scan_datetime(project_root: Path, scope: FileScope, config: AgentConfigSchema) -> list[dict]
│def scan_hardcoded(project_root: Path, scope: FileScope, config: AgentConfigSchema) -> list[dict]
│def scan_file_sizes(project_root: Path, scope: FileScope, config: AgentConfigSchema) -> list[dict]
│def scan_cli_options(project_root: Path, scope: FileScope, config: AgentConfigSchema) -> list[dict]
│def scan_config_files(project_root: Path, scope: FileScope, config: AgentConfigSchema) -> list[dict]
│def load_project_standards(project_root: Path, scope: FileScope) -> dict

modules/backend/agents/tools/environment.py (116 lines):
│def run_command(command: str) -> dict[str, Any]
│def _run_in_environment(command: str, handle: Any, timeout_seconds: int, ...) -> dict[str, Any]
│def _run_local(command: str, timeout_seconds: int) -> dict[str, Any]

modules/backend/agents/tools/filesystem.py (66 lines):
│def read_file(project_root: Path, file_path: str, scope: FileScope) -> str
│def list_files(project_root: Path, scope: FileScope, exclusion_paths: set[str] | None) -> list[str]

modules/backend/agents/tools/system.py (367 lines):
│def check_system_health() -> dict
│def get_app_info(app_config: Any) -> dict
│def scan_log_errors(project_root: Path, scope: FileScope, max_lines: int) -> dict
│def validate_config_files(project_root: Path, scope: FileScope) -> dict
│def check_dependencies(project_root: Path, scope: FileScope) -> dict
│def check_file_structure(project_root: Path, scope: FileScope) -> dict

modules/backend/agents/tools/workflow_design.py (214 lines):
│def browse_agent_catalog(session: AsyncSession) -> list[dict[str, Any]]
│def validate_workflow_proposal(steps: list[dict[str, Any]], objective: dict[str, Any] | None) -> dict[str, Any]
│def build_graph_structure(steps: list[dict[str, Any]]) -> dict[str, Any]
│def persist_workflow(session: AsyncSession) -> dict[str, Any]


## clients

modules/clients/common/gate_helpers.py (89 lines):
│def cost_color(cost: float, budget: float) -> str
│def status_icon(status: str) -> str
│def safe_css_id(raw: str) -> str
│def filter_catalog_agents(agents: list[dict], query: str) -> list[dict]
│def gate_header(ctx: GateContext, title: str) -> str

modules/clients/common/display.py (233 lines):
│def status_color(status: Any) -> str
│def styled_status(status: Any) -> str
│def severity_color(severity: str) -> str
│def annotate_current_mission(name: str, mission_id: str, current_mission_id: str | None) -> str
│def get_console() -> Console
│def build_table(title: str | None) -> Table
│def status_panel() -> Panel
│def info_panel() -> Panel
│def primary_panel() -> Panel
│def thinking_panel() -> Panel
│def output_panel(body: Any) -> Panel
│def format_json_body(raw: str) -> Any
│def cost_line() -> str
│def summary_table() -> Table

modules/clients/cli/report.py (672 lines):
│def render_task_outputs(console: Console, tasks: list[dict]) -> None
│def render_execution_outcomes(console: Console, executions: list[Any]) -> None
│def render_human(raw: str) -> list[Any]
│def _find_list_field(parsed: dict) -> tuple[str, list[dict]]
│def _build_dynamic_table(items: list[dict]) -> Table
│def _build_pqi_panel(pqi: dict) -> Panel
│def _extract_scalars(parsed: dict) -> list[tuple[str, str]]
│def _build_scalars_table(scalars: list[tuple[str, str]]) -> Table
│def render_execution(execution: Any, output_format: str) -> None
│def render_workflow_completion(console: Console, run: Any, executions: list[Any]) -> None
│def render_workflow_run(run: Any, executions: list[Any], output_format: str) -> None
│def _render_summary(title: str, status_line: str, data: dict) -> None
│def generate_narrative(data: dict) -> str
│def _fallback_narrative(data: dict) -> str
│def colorize_narrative(text: str) -> str
│def _emit_json(data: dict) -> None
│def _render_execution_detail(execution: Any) -> None
│def _render_workflow_detail(run: Any, executions: list[Any]) -> None
│def _render_errors(error_data: dict | None) -> None
│def _status_str(status: Any) -> str
│def _styled_status(status: Any, pad: int) -> str
│def _execution_to_dict(execution: Any) -> dict
│def workflow_run_to_dict(run: Any, executions: list[Any]) -> dict
│def _extract_task_summaries(outcome: dict) -> list[dict]
│def _extract_findings(data: dict) -> list[str]

modules/clients/telegram/callbacks/common.py (115 lines):
│class ActionCallback(CallbackData):
│    action: str
│    action_id: str
│class MenuCallback(CallbackData):
│    menu: str
│    item_id: str | None
│class PaginationCallback(CallbackData):
│    list_type: str
│    page: int
│    per_page: int
│class ItemCallback(CallbackData):
│    action: str
│    item_type: str
│    item_id: str

modules/clients/tui/messages.py (92 lines):
│class MissionSelected(Message):
│    def __init__(mission_id: str, mission_name: str) -> None
│class SessionEventReceived(Message):
│    def __init__(event: SessionEvent) -> None
│class GateReviewRequested(Message):
│    def __init__(context: GateContext) -> None
│class GateReviewCompleted(Message):
│    def __init__(decision: GateDecision) -> None
│class AgentSelected(Message):
│    def __init__(agent_name: str) -> None
│class MissionStartRequested(Message):
│    def __init__(brief: str) -> None
│class MissionCreated(Message):
│    def __init__(mission_name: str, description: str) -> None
│class MissionCancelRequested(Message):
│class TabSwitched(Message):
│    def __init__(tab_id: str) -> None
│class ScreenChanged(Message):
│    def __init__(screen_name: str) -> None

modules/clients/telegram/keyboards/common.py (195 lines):
│def get_main_menu_keyboard(user_role: str) -> ReplyKeyboardMarkup
│def get_cancel_keyboard() -> ReplyKeyboardMarkup
│def get_confirmation_keyboard(action_id: str) -> InlineKeyboardMarkup
│def get_pagination_keyboard(list_type: str, current_page: int, total_pages: int, ...) -> InlineKeyboardMarkup
│def get_yes_no_keyboard(action_id: str) -> InlineKeyboardMarkup
│def get_back_keyboard(menu: str) -> InlineKeyboardMarkup

modules/clients/common/event_rendering.py (131 lines):
│def summarize_event(event: SessionEvent) -> str
│def format_event_line(event: SessionEvent) -> str
│def is_noisy(event: SessionEvent) -> bool
│def is_streaming(event: SessionEvent) -> bool
│def format_thinking_line(event: SessionEvent) -> str

modules/clients/telegram/states/example.py (50 lines):
│class FeedbackForm(StatesGroup):
│class SettingsForm(StatesGroup):
│class RegistrationForm(StatesGroup):

modules/clients/telegram/bot.py (147 lines):
│def create_bot() -> 'Bot'
│def create_dispatcher() -> 'Dispatcher'
│def get_bot() -> 'Bot'
│def get_dispatcher() -> 'Dispatcher'
│def setup_webhook(bot: 'Bot', webhook_url: str, secret_token: str) -> None
│def cleanup_bot(bot: 'Bot') -> None

modules/clients/telegram/services/notifications.py (473 lines):
│class NotificationResult:
│    success: bool
│    user_id: int
│    message_id: int | None
│    error: str | None
│    rate_limited: bool
│    timestamp: datetime
│class AlertType(str, Enum):
│class NotificationService:
│    def __init__() -> None
│    def _check_rate_limit(user_id: int) -> bool
│    def send(user_id: int, text: str, parse_mode: str, disable_notification: bool, reply_markup: Any) -> NotificationResult
│    def send_alert(user_id: int, title: str, body: str, alert_type: AlertType, data: dict[str, Any] | None, disable_notification: bool) -> NotificationResult
│    def broadcast(user_ids: list[int], text: str, parse_mode: str, disable_notification: bool, delay_between: float) -> list[NotificationResult]
│    def send_success(user_id: int, title: str, message: str, data: dict[str, Any] | None) -> NotificationResult
│    def send_warning(user_id: int, title: str, message: str, data: dict[str, Any] | None) -> NotificationResult
│    def send_error(user_id: int, title: str, error_message: str, context: dict[str, Any] | None) -> NotificationResult
│    def send_system(user_id: int, title: str, message: str) -> NotificationResult
│def _get_notification_rate_limit() -> int
│def get_notification_service() -> NotificationService
│def send_alert(user_id: int, message: str, alert_type: AlertType, ...) -> NotificationResult
│def send_notification(user_id: int, title: str, body: str, ...) -> NotificationResult

modules/clients/tui/app.py (840 lines):
│class MissionControlApp(App):
│    def __init__() -> None
│    def on_mount() -> None
│    def _startup() -> None
│    def action_screenshot() -> None
│    def action_goto_dashboard() -> None
│    def action_goto_catalog() -> None
│    def action_goto_admin() -> None
│    def action_goto_profile() -> None
│    def action_show_notifications() -> None
│    def _enter_workspace() -> None
│    def _on_workspace_ready() -> None
│    def on_mission_selected(event: MissionSelected) -> None
│    def on_mission_created(event: MissionCreated) -> None
│    def _update_mission_header() -> None
│    def _load_roster() -> None
│    def action_new_mission() -> None
│    def on_mission_start_requested(event: MissionStartRequested) -> None
│    def _execute_mission(brief: str) -> None
│    def action_cancel_mission() -> None
│    def on_session_event_received(message: SessionEventReceived) -> None
│    def _route_event(event: object) -> None
│    def _push_to_event_stream(event: object) -> None
│    def _active_detail_for(agent_id: str) -> AgentDetailWidget | None
│    def _push_to_agent_detail_thinking(agent_id: str) -> None
│    def _push_to_agent_detail_chunk(agent_id: str, content: str) -> None
│    def _push_to_agent_detail_complete(agent_id: str) -> None
│    def _push_to_agent_detail_tool_call(agent_id: str) -> None
│    def _push_to_agent_detail_tool_result(agent_id: str) -> None
│    def _sidebar_set_active(agent_name: str, active: bool) -> None
│    def _sidebar_set_status(agent_name: str, status: str, cost: float) -> None
│    def _update_cost_bar() -> None
│    def _notify(severity: str, message: str, notification_type: str | None) -> None
│    def _update_notification_badge() -> None
│    def _update_workflow_panel(step_id: str) -> None
│    def _update_mission_summary() -> None
│    def _handle_plan_created(event: object) -> None
│    def _show_mission_panel(plan: TaskPlan, layers: list[list[str]]) -> None
│    def on_gate_review_requested(message: GateReviewRequested) -> None
│    def on_gate_review_completed(message: GateReviewCompleted) -> None
│    def on_agent_selected(event: AgentSelected) -> None
│    def _show_agent_detail(agent_name: str) -> None
│    def action_show_overview() -> None
│    def action_switch_mission() -> None
│    def _show_mission_picker() -> None
│    def action_show_history() -> None
│    def _show_history() -> None
│    def _set_loading(loading: bool) -> None
│    def action_focus_input() -> None

modules/clients/telegram/handlers/common.py (154 lines):
│@router.message
│def cmd_start(message: Message, telegram_user: User, user_role: str) -> None
│@router.message
│def cmd_help(message: Message, user_role: str) -> None
│@router.message
│def cmd_cancel(message: Message, state: FSMContext) -> None
│@router.message
│def cmd_status(message: Message) -> None
│@router.message
│def btn_cancel(message: Message, state: FSMContext) -> None

modules/clients/telegram/handlers/example.py (243 lines):
│@router.message
│def cmd_echo(message: Message) -> None
│@router.message
│def cmd_info(message: Message, user_role: str) -> None
│@router.message
│def cmd_feedback(message: Message, state: FSMContext) -> None
│@router.message
│def process_category(message: Message, state: FSMContext) -> None
│@router.message
│def process_invalid_category(message: Message) -> None
│@router.message
│def process_feedback_message(message: Message, state: FSMContext) -> None
│@router.message
│def cmd_confirm(message: Message) -> None
│@router.callback_query
│def callback_confirm(callback: CallbackQuery, callback_data: ActionCallback) -> None
│@router.callback_query
│def callback_cancel(callback: CallbackQuery, callback_data: ActionCallback) -> None
│@router.message
│def cmd_api_example(message: Message) -> None

modules/clients/telegram/middlewares/auth.py (140 lines):
│class AuthMiddleware(BaseMiddleware):
│    def __call__(handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any
│def require_role(min_role: str)

modules/clients/telegram/middlewares/logging.py (150 lines):
│class LoggingMiddleware(BaseMiddleware):
│    def __call__(handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any
│    def _extract_context(event: TelegramObject) -> dict[str, Any]

modules/clients/telegram/middlewares/rate_limit.py (208 lines):
│class RateLimitMiddleware(BaseMiddleware):
│    def __init__(rate_limit: int | None, rate_window: int)
│    def __call__(handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any
│    def _get_user_id(event: TelegramObject) -> int | None
│    def _check_rate_limit(user_id: int, now: float) -> tuple[bool, int]
│    def _send_rate_limit_message(event: TelegramObject, remaining: int) -> None
│class ThrottleMiddleware(BaseMiddleware):
│    def __init__(default_throttle: float)
│    def __call__(handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any
│    def _get_user_id(event: TelegramObject) -> int | None
│def _get_telegram_rate_limit() -> int

modules/clients/tui/widgets/dag_renderer.py (116 lines):
│class DagRenderer(Static):
│    def __init__(steps: list[dict] | None) -> None
│    def compose() -> ComposeResult
│    def update_steps(steps: list[dict]) -> None
│    def update_step_status(step_id: str, status: str) -> None
│    def _render_dag() -> str
│    def _build_layers() -> list[list[dict]]

modules/clients/tui/widgets/prompt_editor.py (78 lines):
│class PromptEditor(Static):
│    def __init__() -> None
│    def compose() -> ComposeResult
│    def on_button_pressed(event: Button.Pressed) -> None
│    def set_content(text: str) -> None

modules/clients/tui/widgets/context_viewer.py (127 lines):
│class ContextViewer(Widget):
│    def __init__(title: str) -> None
│    def compose() -> ComposeResult
│    def load_execution_detail(detail: dict) -> None
│    def _load_overview_tab(detail: dict) -> None
│    def _load_json_tab(plan_json: str | dict | None) -> None
│    def _load_tasks_tab(executions: list[dict]) -> None
│    def load_json(title: str, data: dict | str) -> None
│    def clear() -> None

modules/clients/tui/widgets/agent_sidebar.py (163 lines):
│class AgentCard(Static):
│    is_active: reactive[bool]
│    is_selected: reactive[bool]
│    status_text: reactive[str]
│    def __init__(entry: RosterAgentEntry) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│    def watch_is_active(active: bool) -> None
│    def watch_is_selected(selected: bool) -> None
│    def update_status(status: str | None, cost: float) -> None
│class MissionSummary(Static):
│    def compose() -> ComposeResult
│    def update_from_state() -> None
│class AgentSidebar(Widget):
│    def __init__() -> None
│    def compose() -> ComposeResult
│    def load_roster(agents: list[RosterAgentEntry]) -> None
│    def set_active(agent_name: str, active: bool) -> None
│    def set_selected(agent_name: str) -> None
│    def set_agent_status(agent_name: str, status: str, cost: float) -> None

modules/clients/tui/widgets/event_stream.py (57 lines):
│class EventEntry(Static):
│    def __init__(event: SessionEvent) -> None
│    def compose() -> ComposeResult
│class EventStreamWidget(Widget):
│    def compose() -> ComposeResult
│    def add_event(event: SessionEvent) -> None

modules/clients/tui/widgets/notification.py (361 lines):
│class NotificationRecord:
│    def __init__(notification_type: str, message: str) -> None
│    def label() -> str
│    def mark_read() -> None
│class NotificationStore:
│    def __init__(max_size: int) -> None
│    def add(notification_type: str, message: str) -> NotificationRecord
│    def records() -> list[NotificationRecord]
│    def unread_count() -> int
│    def mark_all_read() -> None
│    def clear() -> None
│class NotificationEntry(Static):
│    def __init__(message: str, severity: str) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│class NotificationStack(Widget):
│    def __init__() -> None
│    def compose() -> ComposeResult
│    def add_notification(message: str, severity: str, timeout_seconds: float) -> None
│    def _dismiss(entry_id: str) -> None
│    def clear_all() -> None
│class _NotificationRow(Static):
│    def __init__(record: NotificationRecord) -> None
│    def compose() -> ComposeResult
│    def _format_age() -> str
│    def on_click() -> None
│class NotificationListModal(ModalScreen):
│    def __init__(store: NotificationStore) -> None
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _render_list() -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│    def action_dismiss_modal() -> None

modules/clients/cli/mission_context.py (90 lines):
│def _async_resolve_current_mission_id() -> str | None
│def _resolve_current_mission_id() -> str | None
│def async_require_mission_id(mission_id: str | None) -> str
│def require_mission_id(mission_id: str | None) -> str
│def with_mission(f)

modules/clients/telegram/handlers/setup.py (28 lines):
│def get_all_routers() -> list[Router]

modules/clients/tui/widgets/chat_input.py (52 lines):
│class ChatInput(Widget):
│    def compose() -> ComposeResult
│    def on_input_submitted(event: Input.Submitted) -> None

modules/clients/telegram/middlewares/setup.py (36 lines):
│def setup_middlewares(dp: 'Dispatcher') -> None

modules/clients/tui/widgets/cost_bar.py (146 lines):
│class CostBar(Widget):
│    cost_usd: reactive[float]
│    budget_usd: reactive[float]
│    input_tokens: reactive[int]
│    output_tokens: reactive[int]
│    current_layer: reactive[int]
│    total_layers: reactive[int]
│    pending_gates: reactive[int]
│    notification_count: reactive[int]
│    connected: reactive[bool]
│    workflow_name: reactive[str]
│    workflow_step: reactive[int]
│    workflow_total_steps: reactive[int]
│    def compose() -> ComposeResult
│    def watch_cost_usd(cost: float) -> None
│    def watch_input_tokens(tokens: int) -> None
│    def watch_output_tokens(tokens: int) -> None
│    def _update_tokens() -> None
│    def watch_current_layer(layer: int) -> None
│    def watch_pending_gates(count: int) -> None
│    def watch_workflow_name(name: str) -> None
│    def watch_workflow_step(step: int) -> None
│    def watch_workflow_total_steps(total: int) -> None
│    def _update_workflow_label() -> None
│    def watch_notification_count(count: int) -> None
│    def watch_connected(connected: bool) -> None
│def _fmt_tokens(n: int) -> str

modules/clients/tui/tabs/chat.py (259 lines):
│class _ThreadItem(Static):
│    def __init__(session: dict) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│class ChatTab(Static):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_sessions() -> None
│    def _render_thread_list(sessions: list[dict]) -> None
│    def on__thread_item_selected(event: _ThreadItem.Selected) -> None
│    def _load_messages(session_id: str) -> None
│    def _render_messages(messages: list[dict]) -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│    def on_input_submitted(event: Input.Submitted) -> None
│    def _create_new_chat() -> None
│    def _send_message() -> None

modules/clients/tui/tabs/context.py (257 lines):
│class _ChangeEntry(Static):
│    def __init__(change: dict) -> None
│    def compose() -> ComposeResult
│class ContextTab(Static):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_context() -> None
│    def _dict_section_to_md(heading: str, data: dict[str, Any]) -> list[str]
│    def _render_context(context: dict[str, Any]) -> None
│    def _show_empty_state() -> None
│    def _render_history(history: list[dict[str, Any]]) -> None
│    def _render_size(size_info: dict[str, Any]) -> None
│    def on_button_pressed(event: Button.Pressed) -> None

modules/clients/tui/tabs/overview.py (46 lines):
│class OverviewTab(Static):
│    def compose() -> ComposeResult

modules/clients/tui/tabs/runs.py (248 lines):
│class _RunRow(Static):
│    def __init__(run: dict) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│class RunsTab(Static):
│    def compose() -> ComposeResult
│    def __init__() -> None
│    def on_mount() -> None
│    def _load_runs() -> None
│    def _render_list(runs: list[dict]) -> None
│    def _update_page_label() -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│    def on__run_row_selected(event: _RunRow.Selected) -> None
│    def _load_detail(execution_id: str) -> None
│    def _render_detail(detail: dict) -> None

modules/clients/tui/tabs/team.py (242 lines):
│class AgentListItem(Static):
│    def __init__(member: dict) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│class TeamTab(Static):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_team() -> None
│    def _render_team_list(members: list[dict]) -> None
│    def _show_list_error(error: str) -> None
│    def on_agent_list_item_selected(event: AgentListItem.Selected) -> None
│    def _render_detail(member: dict) -> None
│    def on_prompt_editor_prompt_saved(event: PromptEditor.PromptSaved) -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│    def _remove_selected_member() -> None
│class _AgentDetailView(Static):
│    def __init__(member: dict) -> None
│    def compose() -> ComposeResult

modules/clients/tui/tabs/workflows.py (263 lines):
│class _WorkflowListItem(Static):
│    def __init__(workflow: dict) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│class WorkflowsTab(Static):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_workflows() -> None
│    def _render_workflow_list(workflows: list[dict]) -> None
│    def _show_list_error(error: str) -> None
│    def on__workflow_list_item_selected(event: _WorkflowListItem.Selected) -> None
│    def _load_detail(workflow_name: str) -> None
│    def _render_detail(detail: dict) -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│    def _run_selected_workflow() -> None

modules/clients/tui/tabs/workshop.py (405 lines):
│class WorkshopTab(Static):
│    def __init__() -> None
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_agents() -> None
│    def _show_empty_state() -> None
│    def on_select_changed(event: Select.Changed) -> None
│    def _load_agent_data() -> None
│    def _render_cached_inputs() -> None
│    def _render_prev_runs() -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│    def _toggle_system_prompt() -> None
│    def _toggle_cached_inputs() -> None
│    def _save_prompt() -> None
│    def _run_test() -> None

modules/clients/tui/screens/admin.py (418 lines):
│class _AdminCatalogTab(Static):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_agents() -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│class _AdminMetricsTab(Static):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_metrics() -> None
│    def _render_overview(data: dict[str, Any]) -> None
│    def _render_cost(data: dict[str, Any]) -> None
│    def _render_activity(data: dict[str, Any]) -> None
│class _AdminConfigTab(Static):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_config() -> None
│    def _render_config(config: dict[str, Any]) -> None
│    def _format_dict(d: dict, indent: int) -> list[str]
│class _AdminHealthTab(Static):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_health() -> None
│    def _render_health(health: dict[str, Any]) -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│class _AdminUsersTab(Static):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_users() -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│class AdminScreen(Screen):
│    def compose() -> ComposeResult
│    def action_go_back() -> None

modules/clients/tui/screens/catalog.py (173 lines):
│class _CatalogListItem(Static):
│    def __init__(agent: dict) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│class CatalogScreen(Screen):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_catalog() -> None
│    def _render_list(agents: list[dict]) -> None
│    def on_input_changed(event: Input.Changed) -> None
│    def show_agent_detail(agent: dict) -> None

modules/clients/tui/screens/dashboard.py (119 lines):
│class MissionCard(Static):
│    def __init__(mission: dict) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│class DashboardScreen(Screen):
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_data() -> None

modules/clients/tui/screens/mission_history.py (173 lines):
│class MissionRow(Static):
│    def __init__(mission: dict) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│class MissionSelected(Message):
│    def __init__(mission: dict) -> None
│class MissionHistoryScreen:
│    def __init__(missions: list[dict]) -> None
│    def compose() -> ComposeResult
│    def on_mission_selected(event: MissionSelected) -> None

modules/clients/tui/screens/mission_picker.py (128 lines):
│class MissionItem(Static):
│    def __init__(mission_id: str, mission_name: str, description: str) -> None
│    def compose() -> ComposeResult
│    def on_click() -> None
│class MissionPickerScreen:
│    def __init__(missions: list[dict[str, str]]) -> None
│    def compose() -> ComposeResult
│    def on_button_pressed(event: Button.Pressed) -> None
│    def on_mission_selected(event: MissionSelected) -> None

modules/clients/tui/screens/profile.py (302 lines):
│class ProfileScreen(Screen):
│    def __init__() -> None
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_profile() -> None
│    def _hide_password_section() -> None
│    def _render_keys(keys: list[dict[str, Any]]) -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│    def _save_display_name() -> None
│    def _change_password() -> None
│    def _create_api_key() -> None
│    def action_go_back() -> None

modules/clients/tui/screens/workspace.py (67 lines):
│class MissionWorkspaceScreen(Screen):
│    def compose() -> ComposeResult
│    def action_switch_tab(tab_id: str) -> None

modules/clients/tui/services/event_listener.py (45 lines):
│class TuiEventBus(EventBusProtocol):
│    def __init__(app: App) -> None
│    def publish(event: SessionEvent) -> None

modules/clients/tui/services/gate_reviewer.py (51 lines):
│class TuiGateReviewer(GateReviewer):
│    def __init__(app: App) -> None
│    def review(context: GateContext) -> GateDecision
│    def resolve(decision: GateDecision) -> None
│    def is_waiting() -> bool

modules/clients/tui/services/service_bridge.py (890 lines):
│class ServiceBridge:
│    def __init__() -> None
│    def list_missions() -> list[dict[str, Any]]
│    def create_mission() -> dict[str, str]
│    def get_mission(mission_id: str) -> Any
│    def get_current_user() -> dict[str, Any]
│    def set_current_mission(mission_id: str | None) -> None
│    def load_roster(mission_id: str, db_session: 'Any') -> Roster
│    def run_execution() -> ExecutionOutcome
│    def list_executions() -> list[dict[str, Any]]
│    def list_executions_paginated() -> tuple[list[dict[str, Any]], int]
│    def _execution_to_dict(r: object) -> dict[str, Any]
│    def get_execution_decisions(execution_id: str) -> list[dict[str, Any]]
│    def get_execution_detail(execution_id: str) -> dict[str, Any] | None
│    def get_execution_cost_breakdown(execution_id: str) -> dict[str, Any] | None
│    def get_team(mission_id: str) -> list[dict[str, Any]]
│    def add_team_member(mission_id: str) -> dict[str, Any]
│    def remove_team_member(mission_id: str) -> None
│    def update_team_member_prompt(mission_id: str) -> dict[str, Any]
│    def list_catalog_agents() -> list[dict[str, Any]]
│    def search_catalog() -> list[dict[str, Any]]
│    def create_session() -> dict[str, Any]
│    def send_message() -> None
│    def list_sessions() -> list[dict[str, Any]]
│    def get_session_messages() -> list[dict[str, Any]]
│    def list_workflows(mission_id: str) -> list[dict[str, Any]]
│    def get_workflow_detail(workflow_name: str) -> dict[str, Any] | None
│    def architect_chat(mission_id: str) -> dict[str, Any]
│    def get_cached_inputs() -> list[dict[str, Any]]
│    def run_workshop_test() -> dict[str, Any]
│    def list_workshop_runs() -> list[dict[str, Any]]
│    def get_mission_context(mission_id: str) -> dict[str, Any]
│    def get_context_history(mission_id: str) -> list[dict[str, Any]]
│    def get_context_size(mission_id: str) -> dict[str, Any]
│    def get_health() -> dict[str, Any]
│    def admin_create_agent() -> dict[str, Any]
│    def admin_update_agent(agent_name: str) -> dict[str, Any]
│    def admin_delete_agent(agent_name: str) -> None
│    def admin_update_system_prompt(agent_name: str) -> dict[str, Any]
│    def admin_get_prompt_history(agent_name: str) -> list[dict[str, Any]]
│    def admin_get_metrics_overview() -> dict[str, Any]
│    def admin_get_cost_breakdown() -> dict[str, Any]
│    def admin_get_agent_utilisation() -> list[dict[str, Any]]
│    def admin_get_activity() -> dict[str, Any]
│    def admin_get_config() -> dict[str, Any]
│    def admin_list_users() -> list[dict[str, Any]]
│    def admin_create_user() -> dict[str, Any]
│    def admin_deactivate_user(user_id: str) -> None
│    def admin_reset_password(user_id: str) -> None
│    def get_profile() -> dict[str, Any]
│    def update_display_name() -> None
│    def change_password() -> None
│    def list_api_keys() -> list[dict[str, Any]]
│    def create_api_key() -> dict[str, Any]
│    def revoke_api_key() -> None
│@asynccontextmanager
│def _cli_user_session() -> AsyncGenerator[tuple[Any, Any], None]
│def _enum_str(val: Any) -> str

modules/clients/tui/services/state.py (167 lines):
│class ChatState:
│    sessions: list[dict]
│    active_session_id: str | None
│    messages: list[dict]
│class WorkflowState:
│    workflows: list[dict]
│    selected_workflow: str | None
│    schedules: list[dict]
│class TeamState:
│    members: list[dict]
│    selected_member: str | None
│class ContextState:
│    document: str
│    history: list[dict]
│class TuiState:
│    current_mission_id: str | None
│    current_mission_name: str | None
│    current_session_id: str | None
│    roster_agents: list[RosterAgentEntry]
│    mission_id: str | None
│    mission_status: str
│    task_plan: TaskPlan | None
│    task_layers: list[list[str]]
│    task_results: dict[str, TaskResult]
│    current_layer: int
│    execution_outcome: ExecutionOutcome | None
│    active_agents: set[str]
│    selected_agent: str | None
│    agent_thinking: dict[str, str]
│    agent_output: dict[str, str]
│    agent_tool_calls: dict[str, list[dict]]
│    agent_verification: dict[str, dict]
│    total_cost_usd: float
│    budget_usd: float
│    total_input_tokens: int
│    total_output_tokens: int
│    events: deque
│    pending_gate: GateContext | None
│    gate_history: list[dict]
│    notifications: deque
│    workflow_name: str | None
│    workflow_progress: dict[str, dict]
│    workflow_waves: list[list[str]]
│    active_screen: str
│    active_tab: str
│    system_role: str
│    mission_role: str
│    team: TeamState
│    chat: ChatState
│    workflow: WorkflowState
│    context: ContextState
│    def reset_mission() -> None
│    def tasks_completed() -> int
│    def tasks_total() -> int
│    def budget_fraction() -> float

modules/clients/tui/widgets/agent_detail.py (167 lines):
│class AgentDetailWidget(Widget):
│    def __init__(agent_name: str) -> None
│    def compose() -> ComposeResult
│    def append_output(content: str) -> None
│    def set_full_output(content: str) -> None
│    def set_thinking(agent_id: str) -> None
│    def add_tool_call() -> None
│    def add_tool_result() -> None
│    def update_header() -> None
│    def clear() -> None

modules/clients/tui/widgets/gate_modal.py (309 lines):
│class GateReviewModal:
│    def __init__(context: GateContext) -> None
│    def compose() -> ComposeResult
│    def _resolve(action: GateAction) -> None
│    def action_gate_continue() -> None
│    def action_gate_skip() -> None
│    def action_gate_retry() -> None
│    def action_gate_modify() -> None
│    def action_gate_abort() -> None
│    def on_button_pressed(event: Button.Pressed) -> None
│def _render_context_body(ctx: GateContext) -> str
│def _action_label(action: GateAction) -> str

modules/clients/tui/widgets/mission_panel.py (227 lines):
│class TaskNode(Static):
│    def __init__(task_def: TaskDefinition) -> None
│    def compose() -> ComposeResult
│class MissionPanel(Widget):
│    def __init__() -> None
│    def compose() -> ComposeResult
│    def load_plan(plan: TaskPlan, layers: list[list[str]]) -> None
│    def update_task_status(task_id: str) -> None
│    def set_active_task(task_id: str) -> None
│    def clear_active_task(task_id: str) -> None
│    def _update_header() -> None
│    def _render_dag() -> None
│    def _refresh_task_node(task_id: str) -> None
│def _task_status_icon(task_id: str) -> str
│def _agent_short_name(agent: str) -> str

modules/clients/tui/widgets/workflow_progress.py (211 lines):
│class StepNode(Static):
│    def __init__(step_id: str) -> None
│    def compose() -> ComposeResult
│class WorkflowProgressWidget(Widget):
│    def __init__() -> None
│    def compose() -> ComposeResult
│    def load_workflow(name: str, waves: list[list[str]], budget: float) -> None
│    def update_step(step_id: str) -> None
│    def set_completed(total_cost: float, summary: str) -> None
│    def set_failed(error: str, failed_step: str | None) -> None
│    def _update_header(status: str, summary: str) -> None
│    def _render_waves() -> None
│    def _refresh_step_node(step_id: str) -> None

modules/clients/__init__.py (1 lines):

modules/clients/cli/__init__.py (1 lines):

modules/clients/cli/admin_cmds.py (362 lines):
│def run_admin_cmd(cli_logger, action: str) -> None
│def _action_metrics(cli_logger)
│def _action_costs(cli_logger)
│def _action_config(cli_logger)
│def _action_health(cli_logger)
│def _action_roles(cli_logger)
│def _action_user_roles(cli_logger)
│def _action_update_prompt(cli_logger)
│def _action_toggle_agent(cli_logger)
│def _prompt_password(console, prompt: str) -> str
│def _action_bootstrap_user(cli_logger)
│def _action_reset_password(cli_logger)
│def _action_ensure_system_accounts(cli_logger)

modules/clients/cli/agent.py (230 lines):
│def show_agents(cli_logger) -> None
│def run_agent(cli_logger, message: str, agent: str | None, ...) -> None
│def _dispatch(message: str, agent: str | None) -> dict
│def _print_jsonl(result: dict) -> None
│def _print_human(result: dict, console) -> None
│def _print_result(result: dict, console) -> None

modules/clients/cli/architect_cmds.py (63 lines):
│def run_architect(cli_logger, action: str) -> None
│def _action_chat(cli_logger)

modules/clients/cli/catalog_cmds.py (114 lines):
│def run_catalog(cli_logger, action: str) -> None
│def run_admin(cli_logger, action: str) -> None
│def _action_list(cli_logger)
│def _action_detail(cli_logger)
│def _action_seed_catalog(cli_logger)

modules/clients/cli/cli_context.py (44 lines):
│class ShowHelpOnMissingArgs(click.Group):
│    def resolve_command(ctx, args)
│class CliContext:
│    def __init__(verbose: bool, debug: bool, quiet: bool, output_format: str, source: str)

modules/clients/cli/config_display.py (44 lines):
│def show_config(logger, output_format: str) -> None

modules/clients/cli/console_cmds.py (304 lines):
│def _fetch_missions() -> list[dict]
│def _fetch_recent_runs(limit: int) -> list[dict]
│def _fetch_catalog_summary() -> dict
│def _fetch_health() -> dict
│def _create_user_display(missions: list[dict], runs: list[dict], catalog: dict, ...) -> Layout
│def _create_developer_display(missions: list[dict], runs: list[dict], catalog: dict) -> Panel
│def _monitor_loop(view: str, refresh: float) -> None
│def run_monitor(view: str, refresh: float) -> None

modules/clients/cli/context.py (477 lines):
│def run_context(cli_logger, action: str) -> None
│def _action_show(cli_logger)
│def _action_assembled(cli_logger)
│def _assembled_async(console, mission_id, domain_tags, ...)
│def _action_codemap(cli_logger)
│def _action_pqi(cli_logger)
│def _action_deps(cli_logger)

modules/clients/cli/credits.py (60 lines):
│def check_credits(logger, roster: str, output_format: str) -> None
│def _check_credits_async(logger, roster: str) -> None

modules/clients/cli/db.py (235 lines):
│def run_db(cli_logger, action: str, table: str | None, ...) -> None
│def _action_stats(cli_logger)
│def _action_tables(cli_logger)
│def _action_query(cli_logger)
│def _action_clear(cli_logger)
│def _action_clear_executions(cli_logger)
│def _action_clear_sessions(cli_logger)
│def _format_value(val) -> str

modules/clients/cli/event_worker.py (27 lines):
│def run_event_worker(logger)

modules/clients/cli/execution_cmds.py (493 lines):
│class _AbortExecution(Exception):
│def run_execution(cli_logger, action: str, objective: str | None, ...) -> None
│def _action_create(cli_logger)
│def _action_execute(cli_logger)
│def _action_run(cli_logger)
│def _action_list(cli_logger)
│def _action_detail(cli_logger)
│def _action_plan(cli_logger)
│def _action_cost(cli_logger)
│def _generate_session_id() -> str
│def _preflight_gate(roster: str) -> None

modules/clients/cli/gate.py (332 lines):
│class CliGateReviewer:
│    def __init__(console, verbose: bool)
│    def review(context: GateContext) -> GateDecision
│    def _review_pre_dispatch(ctx: GateContext) -> GateDecision
│    def _review_pre_layer(ctx: GateContext) -> GateDecision
│    def _review_post_task(ctx: GateContext) -> GateDecision
│    def _review_verification_failed(ctx: GateContext) -> GateDecision
│    def _review_post_layer(ctx: GateContext) -> GateDecision
│    def _review_generic(ctx: GateContext) -> GateDecision
│    def _header(ctx: GateContext, title: str) -> str
│    def _render_ai_recommendation(ctx: GateContext) -> None
│    def _prompt(ctx: GateContext, actions: str, help_text: dict[str, str]) -> GateDecision

modules/clients/cli/health.py (91 lines):
│def check_health(logger, output_format: str) -> None

modules/clients/cli/helpers.py (53 lines):
│def find_process_on_port(port: int) -> list[int]
│def service_stop(logger, service: str, port: int) -> None
│def service_status(logger, service: str, port: int) -> None
│def get_service_port(port: int | None) -> int

modules/clients/cli/info.py (66 lines):
│def show_info(logger, output_format: str) -> None

modules/clients/cli/live_display.py (450 lines):
│class CliEventBus(EventBusProtocol):
│    def __init__(display: LiveExecutionDisplay) -> None
│    def publish(event: SessionEvent) -> None
│class LiveExecutionDisplay:
│    def __init__(max_events: int, show_thinking: bool) -> None
│    def create_event_bus() -> CliEventBus
│    def start() -> Live
│    def handle_progress(event: dict) -> None
│    def handle_event(event: SessionEvent) -> None
│    def add_error(message: str) -> None
│    def set_status(status: str) -> None
│    def _refresh() -> None
│    def _render() -> Layout
│class VerboseEventBus(EventBusProtocol):
│    def __init__() -> None
│    def publish(event: SessionEvent) -> None

modules/clients/cli/mc_chat.py (203 lines):
│def chat_repl(agent_name: str | None, initial_message: str | None, mission_id: str, ...) -> None
│def design_repl(description: str | None, mission_id: str, verbose: bool) -> None
│def _render_chat_event(console, event)
│def _render_chat_event_verbose(event)

modules/clients/cli/mc_run.py (262 lines):
│def run(objective_or_workflow: str) -> None
│def retry(n: int) -> None
│def _resolve_gate(mission_id: str, gate_override: str | None)
│def _run_workflow(workflow) -> None
│def _run_adhoc(objective: str) -> None
│def _show_dry_run(workflow) -> None

modules/clients/cli/mc_status.py (173 lines):
│def _execution_to_dict(e) -> dict
│def show_status(mission_id: str, verbose: bool) -> None
│def show_history(n: int | None, mission_id: str, verbose: bool) -> None
│def _show_detail(n: int, mission_id: str, verbose: bool) -> None

modules/clients/cli/mc_team.py (103 lines):
│def list_team(mission_id: str) -> None
│def list_available(search: str | None) -> None
│def add_agent(mission_id: str, agent_name: str) -> None
│def remove_agent(mission_id: str, agent_name: str) -> None

modules/clients/cli/migrate.py (70 lines):
│def run_migrations(logger, migrate_action: str, revision: str, ...) -> None

modules/clients/cli/mission_cmds.py (391 lines):
│def run_mission(cli_logger, action: str) -> None
│def _action_create(cli_logger)
│def _action_list(cli_logger)
│def _action_detail(cli_logger)
│def _action_archive(cli_logger)
│def _action_delete(cli_logger)
│def _action_use(cli_logger)
│def _action_clear_mission(cli_logger)
│def _action_context_show(cli_logger)
│def _action_context_history(cli_logger)
│def _action_summarize(cli_logger)
│def _action_set_gate(cli_logger)

modules/clients/cli/schedule_cmds.py (161 lines):
│def run_schedule(cli_logger, action: str) -> None
│def _action_list(cli_logger)
│def _action_create(cli_logger)
│def _action_toggle(cli_logger)
│def _action_delete(cli_logger)

modules/clients/cli/scheduler.py (62 lines):
│def run_scheduler(logger) -> None

modules/clients/cli/server.py (54 lines):
│def run_server(logger, host: str | None, port: int | None, ...) -> None

modules/clients/cli/telegram.py (58 lines):
│def run_telegram_poll(logger) -> None
│def _run_polling(bot, dp, logger) -> None

modules/clients/cli/testing.py (40 lines):
│def run_tests(logger, test_type: str, coverage: bool) -> None

modules/clients/cli/worker.py (45 lines):
│def run_worker(logger, workers: int) -> None

modules/clients/cli/workflow_cmds.py (330 lines):
│def run_workflow_cli(cli_logger, action: str, workflow_name: str | None, ...) -> None
│def _action_list(cli_logger)
│def _action_detail(cli_logger)
│def _action_run(cli_logger)
│def _action_runs(cli_logger)
│def _action_run_detail(cli_logger)
│def _action_report(cli_logger)
│def _preflight_gate(workflow_name: str) -> None
│def _load_run_with_executions(run_id: str)

modules/clients/cli/workshop_cmds.py (144 lines):
│def run_workshop(cli_logger, action: str) -> None
│def _action_run(cli_logger)
│def _action_cached_inputs(cli_logger)
│def _action_history(cli_logger)

modules/clients/common/__init__.py (1 lines):

modules/clients/telegram/__init__.py (59 lines):

modules/clients/telegram/callbacks/__init__.py (35 lines):

modules/clients/telegram/handlers/__init__.py (11 lines):

modules/clients/telegram/keyboards/__init__.py (37 lines):

modules/clients/telegram/middlewares/__init__.py (13 lines):

modules/clients/telegram/services/__init__.py (19 lines):

modules/clients/telegram/states/__init__.py (31 lines):

modules/clients/telegram/webhook.py (117 lines):
│def get_webhook_router(bot: 'Bot', dp: 'Dispatcher') -> APIRouter
│def get_webhook_url(base_url: str) -> str

modules/clients/tui/__init__.py (5 lines):

modules/clients/tui/screens/__init__.py (1 lines):

modules/clients/tui/services/__init__.py (1 lines):

modules/clients/tui/tabs/__init__.py (0 lines):

modules/clients/tui/widgets/__init__.py (1 lines):

modules/clients/tui/widgets/catalog_browse_modal.py (150 lines):
│class AgentAdded(Message):
│    def __init__(agent_name: str) -> None
│class _CatalogAgentRow(Static):
│    def __init__(agent: dict) -> None
│    def compose() -> ComposeResult
│    def on_button_pressed(event: Button.Pressed) -> None
│class CatalogBrowseModal:
│    def compose() -> ComposeResult
│    def on_mount() -> None
│    def _load_catalog() -> None
│    def _render_agents(agents: list[dict]) -> None
│    def on_input_changed(event: Input.Changed) -> None
│    def on_agent_added(event: AgentAdded) -> None


## backend.services

modules/backend/services/code_map/types.py (78 lines):
│class SymbolInfo:
│    name: str
│    kind: SymbolKind
│    qualified_name: str
│    line: int
│    params: list[str]
│    return_type: str
│    bases: list[str]
│    fields: list[str]
│    methods: list[SymbolInfo]
│    decorators: list[str]
│    end_line: int
│class SymbolKind(str, Enum):
│class ModuleInfo:
│    path: str
│    lines: int
│    imports: list[str]
│    classes: list[SymbolInfo]
│    functions: list[SymbolInfo]
│    constants: list[str]
│    references: list[str]
│class ReferenceKind(str, Enum):
│class ReferenceEdge:
│    source: str
│    target: str
│    kind: ReferenceKind
│class ReferenceGraph:
│    nodes: list[str]
│    edges: list[ReferenceEdge]

modules/backend/services/base.py (236 lines):
│class BaseService:
│    def __init__(session: AsyncSession) -> None
│    def session() -> AsyncSession
│    def _execute_db_operation(operation: str, coro: Any) -> T
│    def _validate_required(fields: dict[str, Any], field_names: list[str]) -> None
│    def _validate_string_length(value: str, field_name: str, min_length: int | None, max_length: int | None) -> None
│    def _require_owner_or_admin(target_user_id: str, requesting_user: Any, action: str) -> None
│    def _log_operation(operation: str) -> None
│    def _log_debug(message: str) -> None

modules/backend/services/pqi/tools/runner.py (71 lines):
│class Finding:
│    rule_id: str
│    severity: str
│    confidence: str
│    message: str
│    file: str
│    line: int
│    tool: str
│class ToolResult:
│    tool: str
│    available: bool
│    findings: list[Finding]
│    metrics: dict[str, float]
│    raw_output: str
│    error: str
│    def success() -> bool
│def check_installed(command: str) -> bool
│def run_command(args: list[str], cwd: Path, timeout: int) -> tuple[str, str, int]

modules/backend/services/pqi/tools/__init__.py (10 lines):

modules/backend/services/pqi/types.py (96 lines):
│class DimensionScore:
│    name: str
│    score: float
│    sub_scores: dict[str, float]
│    confidence: float
│    recommendations: list[str]
│class QualityBand(str, Enum):
│class PQIResult:
│    composite: float
│    dimensions: dict[str, DimensionScore]
│    quality_band: QualityBand
│    floor_penalty: float
│    file_count: int
│    line_count: int
│def classify_band(score: float) -> QualityBand

modules/backend/services/pqi/ast_analysis.py (296 lines):
│class FileAnalysis:
│    path: str
│    lines: int
│    functions: int
│    classes: int
│    methods: int
│    documented_callables: int
│    total_callables: int
│    annotated_params: int
│    total_params: int
│    annotated_returns: int
│    total_returns: int
│    exception_handlers: int
│    bare_excepts: int
│    broad_excepts: int
│    max_nesting: int
│    function_lengths: list[int]
│    naming_violations: int
│    unsafe_calls: list[str]
│    public_definitions: int
│    private_definitions: int
│class ProjectAnalysis:
│    files: list[FileAnalysis]
│    test_files: int
│    test_lines: int
│    source_files: int
│    source_lines: int
│def analyze_file(file_path: Path, rel_path: str) -> FileAnalysis | None
│def analyze_project(repo_root: Path, scope: list[str] | None, exclude: list[str] | None) -> ProjectAnalysis
│def _analyze_callable(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, analysis: FileAnalysis, is_class: bool) -> None
│def _analyze_except_handler(node: ast.ExceptHandler, analysis: FileAnalysis) -> None
│def _compute_max_nesting(tree: ast.Module) -> int
│def _detect_unsafe_patterns(tree: ast.Module) -> list[str]
│def _count_naming_violations(tree: ast.Module) -> int

modules/backend/services/mission_context.py (410 lines):
│class MissionContextManager(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['MissionContextManager', None]
│    def _build_seed_mcd(mission_name: str, description: str) -> dict
│    def create_context(mission_id: str, mission_name: str, description: str) -> MissionContext
│    def get_context(mission_id: str) -> dict
│    def get_context_with_version(mission_id: str) -> tuple[dict, int]
│    def get_context_size(mission_id: str) -> dict
│    def apply_updates(mission_id: str, updates: list[dict]) -> tuple[int, list[str]]
│    def get_history(mission_id: str, limit: int) -> list[ContextChange]
│    def create_milestone(mission_id: str, title: str) -> ContextMilestone
│    def list_milestones(mission_id: str, limit: int) -> list[ContextMilestone]
│def _load_mcd_limits() -> tuple[int, int]
│def _get_max_size() -> int
│def _get_target_size() -> int
│def _get_nested(data: dict, path: str) -> Any
│def _set_nested(data: dict, path: str, value: Any) -> None
│def _delete_nested(data: dict, path: str) -> Any

modules/backend/services/pqi/scorer.py (129 lines):
│def score_project(repo_root: Path, scope: list[str] | None, exclude: list[str] | None, ...) -> PQIResult
│def _run_tools(repo_root: Path, scope: list[str] | None, exclude: list[str] | None, ...) -> dict[str, ToolResult]

modules/backend/services/pqi/normalizers.py (69 lines):
│def sigmoid(x: float, midpoint: float, k: float) -> float
│def exp_decay(count: float, rate: float) -> float
│def linear(value: float, max_value: float) -> float
│def inverse_linear(value: float, good: float, bad: float) -> float
│def ratio_score(numerator: float, denominator: float) -> float

modules/backend/services/code_map/assembler.py (510 lines):
│def assemble_code_map(modules: list[ModuleInfo], ranks: dict[str, float], repo_root_name: str, ...) -> dict
│def trim_by_rank(code_map: dict, max_tokens: int) -> dict
│def render_markdown_tree(code_map: dict) -> str
│def _render_module(lines: list[str], path: str, mod: dict) -> None
│def _get_layer(path: str) -> str
│def find_circular_deps(import_graph: dict[str, list[str]]) -> list[list[str]]
│def _shorten_module(qname: str) -> str
│def render_for_agent(code_map: dict, max_tokens: int) -> str
│def _estimate_tokens(data: dict | str) -> int
│def _collect_ranked_symbols(code_map: dict) -> list[tuple[str, float, str, str, str | None]]
│def _remove_symbol(code_map: dict, path: str, kind: str, ...) -> None
│def _method_name(sig: str) -> str
│def _is_internal_import(imp: str, internal_modules: set[str]) -> bool
│def _path_to_qname(rel_path: str) -> str

modules/backend/services/pqi/dimensions/analysis.py (446 lines):
│def _count_cycles(graph: dict[str, list[str]]) -> int
│def _gini_coefficient(values: list[int | float]) -> float
│def score_maintainability(project: ProjectAnalysis, tool_results: dict[str, ToolResult] | None) -> DimensionScore
│def score_security(project: ProjectAnalysis, tool_results: dict[str, ToolResult] | None) -> DimensionScore
│def score_modularity(project: ProjectAnalysis, code_map: dict | None) -> DimensionScore
│def score_testability(project: ProjectAnalysis, tool_results: dict[str, ToolResult] | None) -> DimensionScore

modules/backend/services/pqi/dimensions/style.py (232 lines):
│def score_robustness(project: ProjectAnalysis) -> DimensionScore
│def score_elegance(project: ProjectAnalysis, tool_results: dict[str, ToolResult] | None) -> DimensionScore
│def score_reusability(project: ProjectAnalysis, code_map: dict | None) -> DimensionScore

modules/backend/services/mission.py (480 lines):
│class MissionService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['MissionService', None]
│    def create_mission() -> Mission
│    def _auto_assign_agents(mission_id: str, tier: str) -> None
│    def delete_mission(mission_id: str) -> str
│    def _cleanup_mission_containers(mission_id: str) -> None
│    def get_mission(mission_id: str) -> Mission
│    def get_mission_by_name(name: str) -> Mission | None
│    def resolve_mission(id_or_name: str) -> Mission
│    def list_missions(owner_id: str | None, status: str | None, limit: int) -> list[Mission]
│    def update_mission(mission_id: str) -> Mission
│    def set_gate_mode(mission_id: str, mode: str) -> Mission
│    def resolve_gate(mission_id: str, gate_override: str | None)
│    def archive_mission(mission_id: str) -> Mission
│    def unarchive_mission(mission_id: str) -> Mission
│    def get_stats(mission_id: str) -> dict
│    def list_members(mission_id: str) -> list[MissionMember]
│    def add_member(mission_id: str, user_id: str, role: str) -> MissionMember
│    def update_member_role(mission_id: str, user_id: str, role: str) -> MissionMember
│    def remove_member(mission_id: str, user_id: str) -> None

modules/backend/services/execution_persistence.py (399 lines):
│class ExecutionPersistenceService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> 'AsyncGenerator[ExecutionPersistenceService, None]'
│    def save_execution(session_id: str, status: str) -> ExecutionRecord
│    def save_task_execution(execution_record_id: str, task_id: str, agent_name: str, status: str) -> TaskExecution
│    def save_attempt(task_execution_id: str, attempt_number: int, status: str) -> TaskAttempt
│    def save_decision(execution_record_id: str, decision_type: str, reasoning: str) -> ExecutionDecision
│    def get_execution(execution_id: str) -> ExecutionRecord | None
│    def get_task_executions(execution_id: str) -> list
│    def list_executions(status: str | None, roster_name: str | None, objective_category: str | None, mission_id: str | None, limit: int | None, offset: int) -> tuple[list[ExecutionRecord], int]
│    def get_decisions(execution_id: str) -> list[ExecutionDecision]
│    def get_cost_breakdown(execution_id: str) -> ExecutionCostBreakdown
│    def get_execution_status(execution_id: str) -> dict
│    def get_executions_by_session(session_id: str) -> list[ExecutionRecord]
│    def get_replan_chain(execution_id: str) -> list[ExecutionRecord]

modules/backend/services/execution_environment.py (550 lines):
│class EnvironmentHandle:
│    environment_id: str
│    mode: str
│    working_dir: Path
│    branch_name: str | None
│    container_id: str | None
│    created_at: datetime
│    metadata: dict[str, Any]
│class CommandResult:
│    exit_code: int
│    stdout: str
│    stderr: str
│    duration_seconds: float
│class ExecutionBackend(Protocol):
│    def create(name: str, config: dict[str, Any]) -> EnvironmentHandle
│    def execute(handle: EnvironmentHandle, command: list[str], timeout_seconds: int, env_vars: dict[str, str] | None) -> CommandResult
│    def cleanup(handle: EnvironmentHandle) -> None
│class LocalBackend:
│    def create(name: str, config: dict[str, Any]) -> EnvironmentHandle
│    def execute(handle: EnvironmentHandle, command: list[str], timeout_seconds: int, env_vars: dict[str, str] | None) -> CommandResult
│    def cleanup(handle: EnvironmentHandle) -> None
│class ExecutionEnvironmentService:
│    def __init__(db_session: Any) -> None
│    def register_backend(mode: str, backend: ExecutionBackend) -> None
│    def get_or_create_for_mission(mission_id: str, mode: str, config: dict[str, Any] | None) -> EnvironmentHandle
│    def resolve_or_create(name: str, mode: str, config: dict[str, Any] | None) -> EnvironmentHandle
│    def execute(handle: EnvironmentHandle, command: list[str], timeout_seconds: int, env_vars: dict[str, str] | None) -> CommandResult
│    def cleanup(handle: EnvironmentHandle) -> None
│    def list_environments_for_mission(mission_id: str) -> dict
│    def cleanup_for_mission(mission_id: str) -> int
│    def _find_running_environment(mission_id: str, mode: str) -> EnvironmentHandle | None
│    def _persist_environment(mission_id: str, handle: EnvironmentHandle, config: dict | None) -> None
│    def _touch_environment(environment_id: str) -> None
│    def _mark_destroyed(environment_id: str) -> None

modules/backend/services/agent_catalog.py (195 lines):
│class AgentCatalogService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['AgentCatalogService', None]
│    def get_by_name(agent_name: str) -> AgentCatalog
│    def get_by_name_or_none(agent_name: str) -> AgentCatalog | None
│    def list_catalog(enabled_only: bool, visibility: str | None, agent_type: str | None) -> list[AgentCatalog]
│    def list_by_type(agent_type: str, enabled_only: bool) -> list[AgentCatalog]
│    def create_entry() -> AgentCatalog
│    def update_system_prompt(agent_name: str, content: str, changed_by: str, change_reason: str | None) -> AgentCatalog
│    def update_entry(agent_name: str) -> AgentCatalog
│    def is_catalog_empty() -> bool
│    def delete_entry(agent_name: str) -> None
│    def get_prompt_history(agent_name: str, limit: int) -> list
│    def search_by_keyword(text: str) -> list[AgentCatalog]

modules/backend/services/history_query.py (167 lines):
│class HistoryQueryService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['HistoryQueryService', None]
│    def get_recent_task_executions(mission_id: str) -> list[dict]
│    def get_recent_failures(mission_id: str) -> list[dict]
│    def get_mission_summaries(mission_id: str) -> list[dict]

modules/backend/services/code_map/generator.py (83 lines):
│def generate_code_map(repo_root: Path, scope: list[str] | None, exclude: list[str] | None, ...) -> dict
│def _get_git_commit(repo_root: Path) -> str

modules/backend/services/code_map/loader.py (167 lines):
│class CodeMapLoader:
│    def __init__(project_root: Path) -> None
│    def get_json() -> dict | None
│    def get_markdown() -> str | None
│    def is_stale() -> bool
│    def ensure_fresh() -> dict | None
│    def regenerate() -> dict | None
│    def invalidate_cache() -> None
│    def _git_head() -> str

modules/backend/services/compliance.py (333 lines):
│class ComplianceScannerService:
│    def __init__(project_root: Path, config: dict[str, Any]) -> None
│    def _get_exclusion_paths() -> set[str]
│    def _get_enabled_rule_ids() -> set[str]
│    def get_rule_severity(rule_id: str) -> str
│    def collect_python_files() -> list[str]
│    def scan_file_lines(rel_path: str) -> list[str]
│    def _is_excluded(file_path: str) -> bool
│    def scan_import_violations() -> list[dict]
│    def scan_datetime_violations() -> list[dict]
│    def scan_hardcoded_values() -> list[dict]
│    def scan_file_sizes() -> list[dict]
│    def scan_cli_options() -> list[dict]
│    def scan_config_files() -> list[dict]
│    def scan_all() -> list[dict]

modules/backend/services/code_map/graph.py (288 lines):
│def build_reference_graph(modules: list[ModuleInfo]) -> ReferenceGraph
│def _add_symbol_references(symbol: SymbolInfo, module_qname: str, import_tables: dict[str, dict[str, str]], ...) -> None
│def _build_module_index(modules: list[ModuleInfo]) -> set[str]
│def _build_symbol_index(modules: list[ModuleInfo]) -> dict[str, str]
│def _build_import_tables(modules: list[ModuleInfo], known_modules: set[str]) -> dict[str, dict[str, str]]
│def _resolve_import(imp: str, known_modules: set[str]) -> str | None
│def _resolve_name(name: str, module_qname: str, import_tables: dict[str, dict[str, str]], ...) -> str | None
│def _strip_generics(type_str: str) -> str
│def _split_type_args(args_str: str) -> list[str]
│def _path_to_qname(rel_path: str) -> str

modules/backend/services/code_map/parser.py (316 lines):
│def parse_modules(repo_root: Path, scope: list[str] | None, exclude: list[str] | None) -> list[ModuleInfo]
│def _collect_files(repo_root: Path, scope: list[str] | None, exclude: list[str] | None) -> list[Path]
│def _matches_exclude(rel_path: str, pattern: str) -> bool
│def _parse_file(repo_root: Path, file_path: Path) -> ModuleInfo | None
│def _extract_imports(tree: ast.Module) -> list[str]
│def _extract_classes(tree: ast.Module, module_path: str) -> list[SymbolInfo]
│def _parse_class(node: ast.ClassDef, module_qname: str) -> SymbolInfo
│def _extract_functions(tree: ast.Module, module_path: str) -> list[SymbolInfo]
│def _parse_function(node: ast.FunctionDef | ast.AsyncFunctionDef, parent_qname: str, is_method: bool) -> SymbolInfo
│def _extract_constants(tree: ast.Module) -> list[str]
│def _extract_references(tree: ast.Module) -> list[str]
│def _attribute_chain(node: ast.Attribute) -> str
│def _annotation_str(node: ast.expr | None) -> str
│def _name_from_node(node: ast.expr) -> str
│def _path_to_module(rel_path: str) -> str

modules/backend/services/code_map/ranker.py (85 lines):
│def rank_symbols(graph: ReferenceGraph, damping: float, max_iterations: int, ...) -> dict[str, float]

modules/backend/services/session.py (433 lines):
│class SessionService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['SessionService', None]
│    def create_session(data: SessionCreate, user_id: str | None) -> Session
│    def ensure_session(session_id: str | None) -> str
│    def get_session(session_id: str) -> Session
│    def update_session(session_id: str, data: SessionUpdate) -> Session
│    def list_sessions(user_id: str | None, mission_id: str | None, status_filter: str | None, limit: int, offset: int) -> tuple[list[Session], int]
│    def _transition(session_id: str, target_status: SessionStatus, reason: str | None) -> Session
│    def suspend_session(session_id: str, reason: str) -> Session
│    def resume_session(session_id: str) -> Session
│    def complete_session(session_id: str) -> Session
│    def fail_session(session_id: str, reason: str) -> Session
│    def expire_session(session_id: str) -> Session
│    def update_cost(session_id: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None
│    def enforce_budget(session_id: str, estimated_cost: float) -> None
│    def touch_activity(session_id: str) -> None
│    def bind_channel(session_id: str, channel_type: str, channel_id: str) -> SessionChannel
│    def unbind_channel(session_id: str, channel_type: str, channel_id: str) -> None
│    def get_session_by_channel(channel_type: str, channel_id: str) -> Session
│    def add_message(session_id: str, data: SessionMessageCreate) -> None
│    def get_messages(session_id: str, limit: int, offset: int) -> tuple[list, int]
│    def expire_inactive_sessions() -> int
│    def _publish_session_event(event_type: str, session: Session) -> None

modules/backend/services/pqi/composite.py (85 lines):
│def compute_pqi(dimensions: dict[str, DimensionScore], profile: str, file_count: int, ...) -> PQIResult
│def floor_penalty(dimension_scores: dict[str, float]) -> float

modules/backend/services/pqi/dimensions/__init__.py (23 lines):

modules/backend/services/execution.py (625 lines):
│class ExecutionService(BaseService):
│    def __init__(session: AsyncSession, mission_control_dispatch: ExecutionDispatchProtocol | None, session_service: Any | None, event_bus: EventBusProtocol) -> None
│    def factory(event_bus: 'EventBusProtocol | None') -> AsyncGenerator['ExecutionService', None]
│    def _publish_event(event: Any) -> None
│    def create_execution_from_step(workflow_run_id: str, step_id: str, objective: str, roster_ref: str, complexity_tier: str, cost_ceiling_usd: float, upstream_context: dict, session_id: str, environment: str, mission_id: str | None) -> Execution
│    def create_adhoc_execution(objective: str, triggered_by: str, session_id: str | None, roster_ref: str, complexity_tier: str, cost_ceiling_usd: float | None, upstream_context: dict | None, mission_id: str | None) -> Execution
│    def run_execution(execution_id: str, gate: object | None) -> Execution
│    def start_temporal_execution(execution_id: str) -> dict[str, str]
│    def complete_execution(execution_id: str) -> Execution
│    def fail_execution(execution_id: str, error: str, error_data: dict | None) -> Execution
│    def cancel_execution(execution_id: str, reason: str) -> Execution
│    def extract_outputs(execution: Execution, output_mapping: dict | None) -> dict[str, Any]
│    def get_execution(execution_id: str) -> Execution
│    def get_execution_or_none(execution_id: str) -> Execution | None
│    def list_live_executions(mission_id: str | None, limit: int) -> list[Execution]
│    def list_executions(status: str | None, workflow_run_id: str | None, mission_id: str | None, limit: int, offset: int) -> tuple[list[Execution], int]
│    def _get_execution(execution_id: str) -> Execution
│    def _validate_transition(execution: Execution, new_status: ExecutionState) -> None

modules/backend/services/workflow.py (349 lines):
│class WorkflowService:
│    def __init__(agent_registry: dict[str, Any] | None) -> None
│    def load_workflows() -> dict[str, WorkflowSchema]
│    def list_workflows(enabled_only: bool) -> list[WorkflowSchema]
│    def get_workflow(workflow_name: str) -> WorkflowSchema | None
│    def resolve_capability(capability: str) -> str
│    def validate_workflow_capabilities(workflow: WorkflowSchema) -> list[str]
│    def generate_mission_briefs(workflow: WorkflowSchema) -> list[dict[str, Any]]
│    def match_workflow(user_input: str) -> WorkflowSchema | None
│    def resolve_upstream_context(step: WorkflowStepSchema, completed_outcomes: dict[str, dict], workflow_context: dict[str, Any]) -> dict[str, Any]
│    def to_list_item(w: WorkflowSchema) -> dict[str, Any]
│    def to_detail(w: WorkflowSchema) -> dict[str, Any]

modules/backend/services/note.py (208 lines):
│class NoteService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def create_note(data: NoteCreate) -> Note
│    def get_note(note_id: str) -> Note
│    def list_notes(include_archived: bool, limit: int, offset: int) -> list[Note]
│    def list_notes_paginated(include_archived: bool, limit: int, offset: int) -> tuple[list[Note], int]
│    def update_note(note_id: str, data: NoteUpdate) -> Note
│    def delete_note(note_id: str) -> None
│    def archive_note(note_id: str) -> Note
│    def unarchive_note(note_id: str) -> Note
│    def search_notes(query: str, limit: int) -> list[Note]

modules/backend/services/mission_team.py (278 lines):
│class MissionTeamService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['MissionTeamService', None]
│    def add_agent(mission_id: str, agent_catalog_id: str) -> MissionTeamMember
│    def add_agent_by_name(mission_id: str, agent_name: str) -> MissionTeamMember
│    def remove_agent(member_id: str) -> None
│    def remove_agent_by_name(mission_id: str, agent_name: str) -> None
│    def update_user_prompt(member_id: str, content: str, changed_by: str, change_reason: str | None) -> MissionTeamMember
│    def seed_from_catalog(mission_id: str) -> list[MissionTeamMember]
│    def list_team(mission_id: str, enabled_only: bool) -> list[MissionTeamMember]
│    def list_team_with_names(mission_id: str, enabled_only: bool) -> list[dict]
│    def get_member(member_id: str) -> MissionTeamMember
│    def toggle_enabled(member_id: str, enabled: bool) -> MissionTeamMember
│    def list_team_with_details(mission_id: str, enabled_only: bool) -> list[dict]
│    def get_prompt_history(member_id: str, limit: int) -> list

modules/backend/services/mission_plan.py (802 lines):
│class MissionPlanService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def get_or_create_plan(mission_id: str) -> MissionPlan
│    def get_task_states(mission_plan_id: str) -> list[PlanTaskState]
│    def set_gate_mode(mission_plan_id: str, gate_mode: str) -> MissionPlan
│    def set_plan_status(mission_plan_id: str, status: MissionPlanStatus) -> MissionPlan
│    def refine(mission_plan_id: str, instructions: str, user_id: str) -> MissionPlan
│    def _reconcile_task_states(plan: MissionPlan, new_plan: TaskPlan) -> None
│    def dispatch_approved(mission_plan_id: str, user_id: str) -> dict
│    def _write_back_task_results(plan: MissionPlan, outcome) -> list[str]
│    def _derive_subset_task_plan(full_plan: TaskPlan, approved_task_ids: set[str]) -> TaskPlan
│    def approve_task(mission_plan_id: str, task_id: str, user_id: str) -> list[PlanTaskState]
│    def reject_task(mission_plan_id: str, task_id: str, user_id: str) -> list[PlanTaskState]
│    def retry_task(mission_plan_id: str, task_id: str, user_id: str) -> PlanTaskState
│    def _get_task_plan_or_raise(plan: MissionPlan) -> TaskPlan
│    def _transitive_dependencies(task_plan: TaskPlan, task_id: str) -> list[str]
│    def _transitive_dependents(task_plan: TaskPlan, task_id: str) -> list[str]

modules/backend/services/console.py (400 lines):
│class MissionEventAggregator:
│    def __init__(redis: Redis, mission_id: str, refresh_interval: float) -> None
│    def start() -> None
│    def stop() -> None
│    def __aiter__() -> AsyncIterator[dict]
│    def _get_session_ids() -> set[str]
│    def _refresh_sessions() -> None
│    def _subscribe_session(session_id: str) -> None
│    def _read_pubsub(pubsub, channel: str) -> None
│    def _refresh_loop() -> None
│def get_console_history(db_session: 'AsyncSession', mission_id: str, limit: int) -> list[dict]
│def classify_event(event_type: str) -> str

modules/backend/services/context_assembler.py (212 lines):
│class ContextAssembler:
│    def __init__(context_manager: MissionContextManager, history_service: HistoryQueryService) -> None
│    def build(mission_id: str, task_definition: dict, resolved_inputs: dict) -> dict
│    def _is_coding_task(domain_tags: list[str] | None) -> bool
│    def _load_code_map_markdown(max_tokens: int | None) -> str | None
│    def _assemble_history(mission_id: str, domain_tags: list[str], remaining_budget: int) -> dict[str, Any]
│def _get_dispatch_config() -> tuple[int, int]

modules/backend/services/context_curator.py (68 lines):
│class ContextCurator:
│    def __init__(context_manager: MissionContextManager) -> None
│    def get_mission_context(mission_id: str) -> dict
│    def apply_task_updates(mission_id: str, task_result_context_updates: list[dict]) -> tuple[int, list[str]]

modules/backend/services/__init__.py (1 lines):

modules/backend/services/auth.py (220 lines):
│class AuthService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def login(email: str, password: str) -> dict
│    def refresh_token(refresh_token_str: str) -> dict
│    def resolve_api_key(raw_key: str) -> User
│    def resolve_jwt(token: str) -> User
│    def create_api_key(user_id: str, name: str, expires_in_days: int | None, requesting_user: User) -> tuple[str, ApiKey]
│    def list_api_keys(user_id: str, requesting_user: User) -> list[ApiKey]
│    def revoke_api_key(key_id: str, requesting_user: User) -> ApiKey
│    def resolve_legacy_key(raw_key: str) -> User | None

modules/backend/services/bootstrap.py (140 lines):
│class BootstrapService:
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['BootstrapService', None]
│    def ensure_system_accounts() -> list[User]
│    def bootstrap_admin(email: str, display_name: str, password: str) -> tuple[User, str]
│    def reset_password_by_email(email: str, new_password: str) -> None

modules/backend/services/branch_manager.py (265 lines):
│def make_branch_name(mission_id: str, task_description: str) -> str
│def make_commit_message(agent_name: str, description: str) -> str
│def create_branch(repo_root: Path, branch_name: str, base_branch: str) -> bool
│def push_branch(repo_root: Path, branch_name: str, remote: str) -> bool
│def delete_branch(repo_root: Path, branch_name: str) -> bool
│def list_agent_branches(repo_root: Path) -> list[str]
│def cleanup_merged_branches(repo_root: Path, base_branch: str) -> list[str]
│def create_pull_request(repo_root: Path, branch_name: str) -> dict[str, Any]

modules/backend/services/catalog_seeder.py (186 lines):
│def _resolve_system_prompt(agent_name: str, project_root: Path) -> str
│def _extract_model_config(model_field: str | AgentModelSchema) -> dict
│def _infer_visibility(agent_type: str, agent_name: str) -> str
│def seed_catalog(service: AgentCatalogService) -> dict[str, int]

modules/backend/services/code_map/__init__.py (31 lines):

modules/backend/services/container_backend.py (231 lines):
│class ContainerBackend:
│    def __init__() -> None
│    def _get_client() -> Any
│    def create(name: str, config: dict[str, Any]) -> EnvironmentHandle
│    def execute(handle: EnvironmentHandle, command: list[str], timeout_seconds: int, env_vars: dict[str, str] | None) -> CommandResult
│    def cleanup(handle: EnvironmentHandle) -> None

modules/backend/services/database_admin.py (143 lines):
│class DatabaseAdminService:
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['DatabaseAdminService', None]
│    def get_table_row_counts() -> list[tuple[str, int]]
│    def get_table_columns(table: str) -> list[tuple[str, str, str]]
│    def get_table_row_count(table: str) -> int
│    def query_recent_rows(table: str, limit: int) -> tuple[list[str], list[Any]]
│    def truncate_tables(tables: list[str]) -> int
│    def _validate_table(table: str) -> None

modules/backend/services/health.py (84 lines):
│class ComponentStatus:
│    name: str
│    status: str
│    latency_ms: int | None
│    error: str | None
│class HealthReport:
│    overall_status: str
│    components: list[ComponentStatus]
│    def is_healthy() -> bool
│class HealthCheckService:
│    def check_readiness() -> HealthReport
│    def _parse_component(name: str, raw: dict[str, Any]) -> ComponentStatus

modules/backend/services/platform_metrics.py (196 lines):
│class PlatformMetricsService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['PlatformMetricsService', None]
│    def get_overview() -> dict[str, Any]
│    def get_cost_summary() -> dict[str, Any]
│    def get_agent_utilisation() -> list[dict[str, Any]]
│    def get_recent_activity(limit: int) -> dict[str, Any]

modules/backend/services/pqi/__init__.py (9 lines):

modules/backend/services/pqi/tools/bandit.py (188 lines):
│def is_available() -> bool
│def run(repo_root: Path, scope: list[str] | None, exclude: list[str] | None) -> ToolResult
│def _strip_progress(raw: str) -> str
│def _is_test_file(path: str) -> bool
│def _parse_output(raw_json: str) -> ToolResult

modules/backend/services/pqi/tools/radon.py (209 lines):
│def is_available() -> bool
│def run(repo_root: Path, scope: list[str] | None, exclude: list[str] | None) -> ToolResult
│def _build_targets(repo_root: Path, scope: list[str] | None) -> list[str]
│def _build_excludes(repo_root: Path, exclude: list[str] | None) -> list[str]
│def _run_cc(targets: list[str], exclude_args: list[str], cwd: Path) -> dict | str
│def _run_mi(targets: list[str], exclude_args: list[str], cwd: Path) -> dict | str
│def _merge_results(cc_data: dict | str, mi_data: dict | str) -> ToolResult
│def _rank_to_severity(rank: str) -> str

modules/backend/services/run_notifier.py (249 lines):
│class RunNotifierService:
│    def notify_run_completed(run_id: str, workflow_name: str, total_cost_usd: float, step_count: int, mission_id: str | None) -> None
│    def notify_run_failed(run_id: str, workflow_name: str, error: str, total_cost_usd: float, mission_id: str | None) -> None
│    def notify_budget_warning(run_id: str, workflow_name: str, cost_usd: float, budget_usd: float, pct_used: float) -> None
│    def notify_schedule_error(schedule_id: str, error: str) -> None
│def _dispatch_to_channels(channels: list[str], title: str, body: str, ...) -> None
│def _publish_sse_notification(title: str, body: str, alert_type: str, ...) -> None
│def _send_telegram(title: str, body: str, alert_type: str, ...) -> None

modules/backend/services/summarization.py (333 lines):
│class SummarizationService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['SummarizationService', None]
│    def prune_mcd_decisions(mission_id: str, max_age_days: int) -> int
│    def prune_completed_workstreams(mission_id: str, keep_recent: int) -> int
│    def summarize_execution_records(mission_id: str, max_age_days: int, batch_size: int) -> int
│    def run_full_pipeline(mission_id: str) -> dict

modules/backend/services/synthesis.py (115 lines):
│def _get_agent() -> Agent[None, str]
│def _build_prompt(outcome: ExecutionOutcome) -> str
│def summarize_outcome(outcome: ExecutionOutcome) -> str

modules/backend/services/user.py (256 lines):
│class UserService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['UserService', None]
│    def create_user(email: str, display_name: str, password: str | None, system_role: str, is_service_account: bool, requesting_user: User) -> User
│    def get_user(user_id: str, requesting_user: User) -> User
│    def get_user_by_id_or_none(user_id: str) -> User | None
│    def get_current_mission_id(user_id: str) -> str | None
│    def list_users(requesting_user: User, limit: int, offset: int) -> list[User]
│    def update_user(user_id: str, requesting_user: User, display_name: str | None, system_role: str | None, is_active: bool | None) -> User
│    def deactivate_user(user_id: str, requesting_user: User) -> User
│    def change_password(user_id: str, old_password: str, new_password: str, requesting_user: User) -> None
│    def admin_reset_password(user_id: str, new_password: str, requesting_user: User) -> None
│    def set_current_mission(user_id: str, mission_id: str | None, requesting_user: User) -> User

modules/backend/services/workflow_architect.py (266 lines):
│class WorkflowArchitectService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['WorkflowArchitectService', None]
│    def chat(mission_id: str, message: str) -> dict[str, Any]
│    def recommend_team(mission_id: str) -> list[dict[str, Any]]
│    def _create_agent()
│    def _build_deps(mission_id: str, mission_brief: str, team_summary: str, session_id: str | None, on_event: Any) -> ArchitectAgentDeps
│    def _load_mission_context(mission_id: str) -> tuple[str, str]
│    def _build_initial_prompt(user_message: str, mission_brief: str, team_summary: str) -> str

modules/backend/services/workflow_definition.py (176 lines):
│class WorkflowDefinitionService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['WorkflowDefinitionService', None]
│    def create_workflow(mission_id: str, name: str, description: str, objective: dict[str, Any], steps: list[dict[str, Any]]) -> WorkflowDefinition
│    def get_workflow(mission_id: str, name: str) -> WorkflowDefinition
│    def list_workflows(mission_id: str, enabled_only: bool) -> list[WorkflowDefinition]
│    def update_workflow(workflow_id: str) -> WorkflowDefinition
│    def lock_workflow(workflow_id: str) -> WorkflowDefinition
│    def import_from_template(mission_id: str, template_name: str) -> WorkflowDefinition
│    def list_templates() -> list[WorkflowDefinition]
│    def _validate_steps(steps: list[dict[str, Any]]) -> None

modules/backend/services/workflow_run.py (664 lines):
│class WorkflowRunService(BaseService):
│    def __init__(session: AsyncSession, execution_service_factory: ExecutionServiceFactory | None, workflow_service: WorkflowService | None) -> None
│    def factory(event_bus: Any | None) -> AsyncGenerator['WorkflowRunService', None]
│    def run_workflow(workflow_name: str, triggered_by: str, context_overrides: dict[str, Any] | None, on_progress: Any | None, mission_name: str | None, gate: object | None) -> WorkflowRun
│    def _resolve_mission(mission_name: str, workflow: WorkflowSchema) -> str
│    def run_workflow_from_definition(workflow_definition_id: str, mission_id: str) -> WorkflowRun
│    def _definition_to_schema(defn) -> WorkflowSchema
│    def list_runs(workflow_name: str | None, limit: int) -> tuple[list[WorkflowRun], int]
│    def get_run(run_id: str) -> WorkflowRun | None
│    def _execute_steps(run: WorkflowRun, workflow: WorkflowSchema, session_id: str, on_progress: Any | None, gate: object | None) -> None
│    def _execute_wave(run: WorkflowRun, steps: list[WorkflowStepSchema], session_id: str, completed_outcomes: dict[str, dict], gate: object | None) -> list[tuple[Any, dict]]
│    def _execute_step(run: WorkflowRun, step: WorkflowStepSchema, session_id: str, completed_outcomes: dict[str, dict], execution_service: ExecutionService, gate: object | None) -> tuple[Any, dict]
│    def _build_step_objective(step: WorkflowStepSchema, step_input: dict[str, Any]) -> str
│    def _notify_run_outcome(run: 'WorkflowRun', step_count: int) -> None
│    def _compute_waves(steps: list[WorkflowStepSchema]) -> list[list[str]]

modules/backend/services/workflow_schedule.py (309 lines):
│class WorkflowScheduleService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['WorkflowScheduleService', None]
│    def create_schedule() -> WorkflowSchedule
│    def get_schedule(schedule_id: str) -> WorkflowSchedule
│    def list_by_mission(mission_id: str, enabled_only: bool) -> list[WorkflowSchedule]
│    def list_by_workflow(workflow_definition_id: str) -> list[WorkflowSchedule]
│    def update_schedule(schedule_id: str) -> WorkflowSchedule
│    def toggle_enabled(schedule_id: str, enabled: bool) -> WorkflowSchedule
│    def delete_schedule(schedule_id: str) -> None
│    def get_next_run(mission_id: str) -> dict | None
│    def evaluate_due_schedules() -> list[dict]
│def _validate_cron(expression: str) -> None
│def _compute_next_fire(cron_expression: str, after: datetime) -> str | None

modules/backend/services/workshop.py (358 lines):
│class WorkshopService(BaseService):
│    def __init__(session: AsyncSession) -> None
│    def factory() -> AsyncGenerator['WorkshopService', None]
│    def run_agent(agent_name: str) -> dict[str, Any]
│    def get_cached_inputs(agent_name: str, mission_id: str | None, limit: int | None) -> list[dict[str, Any]]
│    def list_runs(agent_name: str | None, limit: int) -> list[ExecutionRecord]
│    def list_runs_as_dicts(agent_name: str | None, limit: int) -> list[dict]
│    def _persist_workshop_run() -> ExecutionRecord
│    def _parse_agent_path(agent_name: str) -> tuple[str, str]


## backend.models

modules/backend/models/base.py (53 lines):
│class Base(DeclarativeBase):
│class UUIDMixin:
│    id: Mapped[str]
│class TimestampMixin:
│    created_at: Mapped[datetime]
│    updated_at: Mapped[datetime]

modules/backend/models/user.py (84 lines):
│class User(UUIDMixin, TimestampMixin, Base):
│    email: Mapped[str]
│    display_name: Mapped[str]
│    hashed_password: Mapped[str | None]
│    system_role: Mapped[str]
│    is_active: Mapped[bool]
│    is_service_account: Mapped[bool]
│    last_login_at: Mapped[datetime | None]
│    current_mission_id: Mapped[str | None]
│    api_keys: Mapped[list['ApiKey']]
│    current_mission: Mapped['Mission | None']
│    def has_role(minimum: str) -> bool
│    def __repr__() -> str
│class SystemRole(str, enum.Enum):

modules/backend/models/mission_plan.py (274 lines):
│class MissionPlan(UUIDMixin, TimestampMixin, Base):
│    mission_id: Mapped[str]
│    task_plan_json: Mapped[dict | None]
│    gate_mode: Mapped[str | None]
│    status: Mapped[str]
│    version: Mapped[int]
│    budget_usd_ceiling: Mapped[float | None]
│    total_spent_usd: Mapped[float]
│    veto_window_sec: Mapped[int | None]
│    task_states: Mapped[list['PlanTaskState']]
│    def __repr__() -> str
│class PlanTaskState(UUIDMixin, TimestampMixin, Base):
│    mission_plan_id: Mapped[str]
│    task_id: Mapped[str]
│    status: Mapped[str]
│    approved_by_user_id: Mapped[str | None]
│    approved_at: Mapped[datetime | None]
│    execution_record_id: Mapped[str | None]
│    task_execution_id: Mapped[str | None]
│    last_attempt_at: Mapped[datetime | None]
│    retry_count: Mapped[int]
│    veto_expires_at: Mapped[datetime | None]
│    result_summary: Mapped[str | None]
│    failure_reason: Mapped[str | None]
│    plan: Mapped['MissionPlan']
│    def __repr__() -> str
│class MissionPlanStatus(str, enum.Enum):
│class PlanTaskStatus(str, enum.Enum):

modules/backend/models/execution_record.py (403 lines):
│class ExecutionRecord(UUIDMixin, TimestampMixin, Base):
│    session_id: Mapped[str]
│    mission_id: Mapped[str | None]
│    roster_name: Mapped[str | None]
│    objective_statement: Mapped[str | None]
│    objective_category: Mapped[str | None]
│    status: Mapped[str]
│    task_plan_json: Mapped[dict | None]
│    execution_outcome_json: Mapped[dict | None]
│    planning_thinking_trace: Mapped[str | None]
│    total_cost_usd: Mapped[float]
│    started_at: Mapped[str | None]
│    completed_at: Mapped[str | None]
│    summarized: Mapped[bool]
│    parent_execution_record_id: Mapped[str | None]
│    task_executions: Mapped[list['TaskExecution']]
│    decisions: Mapped[list['ExecutionDecision']]
│    def __repr__() -> str
│class ExecutionDecision(UUIDMixin, TimestampMixin, Base):
│    execution_record_id: Mapped[str]
│    decision_type: Mapped[str]
│    task_id: Mapped[str | None]
│    reasoning: Mapped[str]
│    execution_record: Mapped['ExecutionRecord']
│    def __repr__() -> str
│class TaskExecution(UUIDMixin, TimestampMixin, Base):
│    execution_record_id: Mapped[str]
│    task_id: Mapped[str]
│    agent_name: Mapped[str]
│    status: Mapped[str]
│    output_data: Mapped[dict | None]
│    token_usage: Mapped[dict | None]
│    cost_usd: Mapped[float]
│    duration_seconds: Mapped[float | None]
│    verification_outcome: Mapped[dict | None]
│    started_at: Mapped[str | None]
│    completed_at: Mapped[str | None]
│    execution_id: Mapped[str | None]
│    domain_tags: Mapped[list | None]
│    execution_record: Mapped['ExecutionRecord']
│    attempts: Mapped[list['TaskAttempt']]
│    def __repr__() -> str
│class ExecutionRecordStatus(str, enum.Enum):
│class TaskAttempt(UUIDMixin, TimestampMixin, Base):
│    task_execution_id: Mapped[str]
│    attempt_number: Mapped[int]
│    status: Mapped[str]
│    failure_tier: Mapped[str | None]
│    failure_reason: Mapped[str | None]
│    feedback_provided: Mapped[str | None]
│    input_tokens: Mapped[int]
│    output_tokens: Mapped[int]
│    cost_usd: Mapped[float]
│    task_execution: Mapped['TaskExecution']
│    def __repr__() -> str
│class TaskExecutionStatus(str, enum.Enum):
│class TaskAttemptStatus(str, enum.Enum):
│class DecisionType(str, enum.Enum):
│class FailureTier(str, enum.Enum):

modules/backend/models/mission.py (151 lines):
│class Mission(UUIDMixin, TimestampMixin, Base):
│    name: Mapped[str]
│    description: Mapped[str]
│    brief: Mapped[str | None]
│    status: Mapped[str]
│    owner_id: Mapped[str]
│    team_id: Mapped[str | None]
│    default_roster: Mapped[str]
│    budget_ceiling_usd: Mapped[float | None]
│    repo_url: Mapped[str | None]
│    repo_root: Mapped[str | None]
│    gate_mode: Mapped[str | None]
│    tier: Mapped[str]
│    execution_environment: Mapped[str | None]
│    members: Mapped[list['MissionMember']]
│    def __repr__() -> str
│class MissionMember(UUIDMixin, TimestampMixin, Base):
│    mission_id: Mapped[str]
│    user_id: Mapped[str]
│    role: Mapped[str]
│    mission: Mapped['Mission']
│    user: Mapped['User']
│    def __repr__() -> str
│class MissionStatus(str, enum.Enum):
│class MissionTier(str, enum.Enum):
│class MissionMemberRole(str, enum.Enum):

modules/backend/models/execution.py (215 lines):
│class Execution(UUIDMixin, TimestampMixin, Base):
│    workflow_run_id: Mapped[str | None]
│    workflow_step_id: Mapped[str | None]
│    mission_id: Mapped[str | None]
│    objective: Mapped[str]
│    roster_ref: Mapped[str]
│    complexity_tier: Mapped[str]
│    status: Mapped[str]
│    session_id: Mapped[str]
│    trigger_type: Mapped[str]
│    triggered_by: Mapped[str]
│    upstream_context: Mapped[dict]
│    context: Mapped[dict]
│    total_cost_usd: Mapped[float]
│    cost_ceiling_usd: Mapped[float | None]
│    started_at: Mapped[str | None]
│    completed_at: Mapped[str | None]
│    error_data: Mapped[dict | None]
│    execution_outcome: Mapped[dict | None]
│    result_summary: Mapped[str | None]
│    execution_environment: Mapped[str]
│    def __repr__() -> str
│class WorkflowRun(UUIDMixin, TimestampMixin, Base):
│    workflow_name: Mapped[str]
│    workflow_version: Mapped[int]
│    mission_id: Mapped[str | None]
│    status: Mapped[str]
│    session_id: Mapped[str]
│    trigger_type: Mapped[str]
│    triggered_by: Mapped[str]
│    context: Mapped[dict]
│    total_cost_usd: Mapped[float]
│    budget_usd: Mapped[float | None]
│    started_at: Mapped[str | None]
│    completed_at: Mapped[str | None]
│    error_data: Mapped[dict | None]
│    result_summary: Mapped[str | None]
│    def __repr__() -> str
│class ExecutionState(str, enum.Enum):
│class WorkflowRunState(str, enum.Enum):
│class ExecutionEnvironment(str, enum.Enum):

modules/backend/models/agent_catalog.py (81 lines):
│class AgentCatalog(UUIDMixin, TimestampMixin, Base):
│    agent_name: Mapped[str]
│    agent_type: Mapped[str]
│    version: Mapped[str]
│    description: Mapped[str]
│    system_prompt: Mapped[str]
│    model_config_json: Mapped[dict]
│    tools: Mapped[list]
│    scope: Mapped[dict]
│    interface: Mapped[dict | None]
│    constraints: Mapped[dict]
│    keywords: Mapped[list]
│    enabled: Mapped[bool]
│    chat_enabled: Mapped[bool]
│    visibility: Mapped[str]
│    def __repr__() -> str

modules/backend/models/mission_context.py (158 lines):
│class ContextMilestone(UUIDMixin, TimestampMixin, Base):
│    mission_id: Mapped[str]
│    title: Mapped[str]
│    description: Mapped[str]
│    version_snapshot: Mapped[int]
│    context_snapshot: Mapped[dict]
│    created_by: Mapped[str]
│    def __repr__() -> str
│class ContextChange(UUIDMixin, TimestampMixin, Base):
│    context_id: Mapped[str]
│    version: Mapped[int]
│    change_type: Mapped[str]
│    path: Mapped[str]
│    old_value: Mapped[dict | None]
│    new_value: Mapped[dict | None]
│    agent_id: Mapped[str | None]
│    mission_id: Mapped[str | None]
│    task_id: Mapped[str | None]
│    execution_id: Mapped[str | None]
│    reason: Mapped[str]
│    context: Mapped['MissionContext']
│    def __repr__() -> str
│class MissionContext(UUIDMixin, TimestampMixin, Base):
│    mission_id: Mapped[str]
│    context_data: Mapped[dict]
│    version: Mapped[int]
│    size_characters: Mapped[int]
│    size_tokens: Mapped[int]
│    changes: Mapped[list['ContextChange']]
│    def __repr__() -> str
│class ChangeType(str, enum.Enum):

modules/backend/models/note.py (39 lines):
│class Note(UUIDMixin, TimestampMixin, Base):
│    title: Mapped[str]
│    content: Mapped[str | None]
│    is_archived: Mapped[bool]
│    def __repr__() -> str

modules/backend/models/session.py (188 lines):
│class Session(UUIDMixin, TimestampMixin, Base):
│    status: Mapped[str]
│    user_id: Mapped[str | None]
│    mission_id: Mapped[str | None]
│    agent_id: Mapped[str | None]
│    goal: Mapped[str | None]
│    plan_id: Mapped[str | None]
│    session_metadata: Mapped[dict | None]
│    total_input_tokens: Mapped[int]
│    total_output_tokens: Mapped[int]
│    total_cost_usd: Mapped[float]
│    cost_budget_usd: Mapped[float | None]
│    last_activity_at: Mapped[datetime]
│    expires_at: Mapped[datetime | None]
│    channels: Mapped[list['SessionChannel']]
│    messages: Mapped[list['SessionMessage']]
│    def budget_remaining_usd() -> float | None
│    def __repr__() -> str
│class SessionChannel(UUIDMixin, Base):
│    session_id: Mapped[str]
│    channel_type: Mapped[str]
│    channel_id: Mapped[str]
│    bound_at: Mapped[datetime]
│    is_active: Mapped[bool]
│    session: Mapped['Session']
│    def __repr__() -> str
│class SessionMessage(UUIDMixin, Base):
│    session_id: Mapped[str]
│    role: Mapped[str]
│    content: Mapped[str]
│    sender_id: Mapped[str | None]
│    model: Mapped[str | None]
│    input_tokens: Mapped[int | None]
│    output_tokens: Mapped[int | None]
│    cost_usd: Mapped[float | None]
│    thinking: Mapped[str | None]
│    tool_name: Mapped[str | None]
│    tool_call_id: Mapped[str | None]
│    created_at: Mapped[datetime]
│    session: Mapped['Session']
│    def __repr__() -> str
│class SessionStatus(str, enum.Enum):

modules/backend/models/workflow_definition.py (91 lines):
│class WorkflowDefinition(UUIDMixin, TimestampMixin, Base):
│    mission_id: Mapped[str | None]
│    name: Mapped[str]
│    description: Mapped[str]
│    version: Mapped[int]
│    enabled: Mapped[bool]
│    objective: Mapped[dict]
│    steps: Mapped[list]
│    trigger_config: Mapped[dict]
│    budget_config: Mapped[dict]
│    context: Mapped[dict]
│    designed_by: Mapped[str | None]
│    locked_at: Mapped[str | None]
│    def trigger_type() -> str
│    def step_count() -> int
│    def __repr__() -> str

modules/backend/models/mission_history.py (119 lines):
│class MissionDecision(UUIDMixin, TimestampMixin, Base):
│    mission_id: Mapped[str]
│    decision_id: Mapped[str]
│    domain: Mapped[str]
│    decision: Mapped[str]
│    rationale: Mapped[str]
│    made_by: Mapped[str]
│    execution_id: Mapped[str | None]
│    status: Mapped[str]
│    superseded_by: Mapped[str | None]
│    def __repr__() -> str
│class MilestoneSummary(UUIDMixin, TimestampMixin, Base):
│    mission_id: Mapped[str]
│    title: Mapped[str]
│    summary: Mapped[str]
│    mission_ids: Mapped[list]
│    key_outcomes: Mapped[dict]
│    domain_tags: Mapped[list]
│    period_start: Mapped[str | None]
│    period_end: Mapped[str | None]
│    def __repr__() -> str
│class DecisionStatus(str, enum.Enum):

modules/backend/models/mission_team.py (65 lines):
│class MissionTeamMember(UUIDMixin, TimestampMixin, Base):
│    mission_id: Mapped[str]
│    agent_catalog_id: Mapped[str]
│    user_prompt: Mapped[str | None]
│    user_prompt_version: Mapped[int]
│    enabled: Mapped[bool]
│    display_order: Mapped[int]
│    custom_constraints: Mapped[dict | None]
│    def __repr__() -> str

modules/backend/models/workflow_schedule.py (82 lines):
│class WorkflowSchedule(UUIDMixin, TimestampMixin, Base):
│    workflow_definition_id: Mapped[str]
│    mission_id: Mapped[str]
│    cron_expression: Mapped[str]
│    timezone: Mapped[str]
│    enabled: Mapped[bool]
│    description: Mapped[str]
│    budget_per_run_usd: Mapped[float | None]
│    max_iterations: Mapped[int | None]
│    iteration_count: Mapped[int]
│    cooldown_seconds: Mapped[int]
│    last_fired_at: Mapped[str | None]
│    next_fire_at: Mapped[str | None]
│    created_by: Mapped[str]
│    def __repr__() -> str

modules/backend/models/api_key.py (70 lines):
│class ApiKey(UUIDMixin, TimestampMixin, Base):
│    user_id: Mapped[str]
│    name: Mapped[str]
│    key_prefix: Mapped[str]
│    hashed_key: Mapped[str]
│    expires_at: Mapped[datetime | None]
│    revoked_at: Mapped[datetime | None]
│    scopes: Mapped[list | None]
│    last_used_at: Mapped[datetime | None]
│    user: Mapped['User']
│    def is_active() -> bool
│    def __repr__() -> str

modules/backend/models/prompt_version.py (60 lines):
│class PromptVersion(UUIDMixin, TimestampMixin, Base):
│    entity_type: Mapped[str]
│    entity_id: Mapped[str]
│    prompt_type: Mapped[str]
│    content: Mapped[str]
│    version: Mapped[int]
│    changed_by: Mapped[str]
│    change_reason: Mapped[str | None]
│    def content_length() -> int
│    def __repr__() -> str

modules/backend/models/__init__.py (64 lines):

modules/backend/models/execution_environment.py (81 lines):
│class EnvironmentStatus(str, enum.Enum):
│class ExecutionEnvironmentModel(UUIDMixin, TimestampMixin, Base):
│    mission_id: Mapped[str]
│    mode: Mapped[str]
│    status: Mapped[str]
│    container_id: Mapped[str | None]
│    container_name: Mapped[str | None]
│    branch_name: Mapped[str | None]
│    working_dir: Mapped[str | None]
│    image: Mapped[str | None]
│    execution_count: Mapped[int]
│    last_execution_at: Mapped[str | None]
│    config: Mapped[dict | None]
│    def __repr__() -> str


## backend.schemas

modules/backend/schemas/base.py (86 lines):
│class ApiResponse(BaseModel):
│    success: bool
│    data: DataT | None
│    error: ErrorDetail | None
│    metadata: ResponseMetadata
│class ResponseMetadata(BaseModel):
│    timestamp: datetime
│    request_id: str | None
│class ErrorDetail(BaseModel):
│    code: str
│    message: str
│    details: dict[str, Any] | None
│class ErrorResponse(BaseModel):
│    success: bool
│    data: None
│    error: ErrorDetail
│    metadata: ResponseMetadata
│class PaginatedResponse(BaseModel):
│    success: bool
│    data: list[DataT]
│    error: None
│    metadata: ResponseMetadata
│    pagination: 'PaginationInfo'
│class PaginationInfo(BaseModel):
│    total: int | None
│    limit: int
│    cursor: str | None
│    next_cursor: str | None
│    has_more: bool

modules/backend/schemas/task_plan.py (204 lines):
│class TaskPlan(BaseModel):
│    version: str
│    mission_id: str
│    summary: str
│    estimated_cost_usd: float
│    estimated_duration_seconds: int
│    tasks: list[TaskDefinition]
│    execution_hints: ExecutionHints
│    def task_ids() -> list[str]
│    def get_task(task_id: str) -> TaskDefinition | None
│class TaskDefinition(BaseModel):
│    task_id: str
│    agent: str
│    agent_version: str
│    description: str
│    instructions: str
│    inputs: TaskInputs
│    dependencies: list[str]
│    verification: TaskVerification
│    constraints: TaskConstraints
│    domain_tags: list[str]
│class ExecutionHints(BaseModel):
│    min_success_threshold: float
│    critical_path: list[str]
│class TaskInputs(BaseModel):
│    static: dict
│    from_upstream: dict[str, FromUpstreamRef]
│    file_manifest: FileManifest | None
│class TaskVerification(BaseModel):
│    tier_1: Tier1Verification
│    tier_2: Tier2Verification
│    tier_3: Tier3Verification
│class TaskConstraints(BaseModel):
│    timeout_override_seconds: int | None
│    priority: str
│class FileManifestEntry(BaseModel):
│    path: str
│    reason: str
│class DeterministicCheck(BaseModel):
│    check: str
│    params: dict
│class FromUpstreamRef(BaseModel):
│    source_task: str
│    source_field: str
│class FileManifest(BaseModel):
│    read_for_pattern: list[FileManifestEntry]
│    read_first: list[FileManifestEntry]
│    modify: list[FileManifestEntry]
│class Tier1Verification(BaseModel):
│    schema_validation: bool
│    required_output_fields: list[str]
│class Tier2Verification(BaseModel):
│    deterministic_checks: list[DeterministicCheck]
│class Tier3Verification(BaseModel):
│    requires_ai_evaluation: bool
│    evaluation_criteria: list[str]
│    evaluator_agent: str | None
│    min_evaluation_score: float | None

modules/backend/schemas/user.py (93 lines):
│class UserResponse(BaseModel):
│    id: str
│    email: str
│    display_name: str
│    system_role: str
│    is_active: bool
│    is_service_account: bool
│    last_login_at: datetime | None
│    current_mission_id: str | None
│    current_mission_name: str | None
│    created_at: datetime
│    updated_at: datetime
│    def from_user(user: object) -> 'UserResponse'
│class UserCreate(BaseModel):
│    email: EmailStr
│    display_name: str
│    password: str | None
│    system_role: str
│    is_service_account: bool
│class UserUpdate(BaseModel):
│    display_name: str | None
│    system_role: str | None
│    is_active: bool | None
│class UpdateProfileRequest(BaseModel):
│    display_name: str | None
│class SetCurrentMissionRequest(BaseModel):
│    mission_id: str | None
│class UserBriefResponse(BaseModel):
│    id: str
│    email: str
│    display_name: str
│    system_role: str
│    is_service_account: bool

modules/backend/schemas/session.py (172 lines):
│class SessionResponse(BaseModel):
│    id: str
│    status: str
│    user_id: str | None
│    mission_id: str | None
│    agent_id: str | None
│    goal: str | None
│    plan_id: str | None
│    total_input_tokens: int
│    total_output_tokens: int
│    total_cost_usd: float
│    cost_budget_usd: float | None
│    budget_remaining_usd: float | None
│    created_at: datetime
│    updated_at: datetime
│    last_activity_at: datetime
│    expires_at: datetime | None
│class SessionMessageCreate(BaseModel):
│    content: str
│    role: str
│    sender_id: str | None
│    model: str | None
│    input_tokens: int | None
│    output_tokens: int | None
│    cost_usd: float | None
│    tool_name: str | None
│    tool_call_id: str | None
│    thinking: str | None
│class SessionCreate(BaseModel):
│    goal: str | None
│    mission_id: str | None
│    agent_id: str | None
│    cost_budget_usd: float | None
│    ttl_hours: int | None
│    session_metadata: dict | None
│class SessionUpdate(BaseModel):
│    goal: str | None
│    agent_id: str | None
│    cost_budget_usd: float | None
│    session_metadata: dict | None
│class ChannelBindRequest(BaseModel):
│    channel_type: str
│    channel_id: str
│class ChannelResponse(BaseModel):
│    id: str
│    session_id: str
│    channel_type: str
│    channel_id: str
│    bound_at: datetime
│    is_active: bool
│class SessionListResponse(BaseModel):
│    id: str
│    status: str
│    goal: str | None
│    mission_id: str | None
│    agent_id: str | None
│    total_cost_usd: float
│    created_at: datetime
│    last_activity_at: datetime
│class SessionMessageResponse(BaseModel):
│    id: str
│    session_id: str
│    role: str
│    content: str
│    sender_id: str | None
│    model: str | None
│    input_tokens: int | None
│    output_tokens: int | None
│    cost_usd: float | None
│    tool_name: str | None
│    tool_call_id: str | None
│    thinking: str | None
│    created_at: datetime

modules/backend/schemas/workflow.py (273 lines):
│class WorkflowSchema(BaseModel):
│    workflow_name: str
│    description: str
│    objective: WorkflowObjectiveSchema
│    version: int
│    enabled: bool
│    mission_name: str | None
│    trigger: WorkflowTriggerSchema
│    budget: WorkflowBudgetSchema
│    context: dict[str, Any]
│    steps: list[WorkflowStepSchema]
│    def validate_steps(steps: list[WorkflowStepSchema]) -> list[WorkflowStepSchema]
│class WorkflowStepSchema(BaseModel):
│    id: str
│    description: str | None
│    capability: str
│    roster: str
│    complexity_tier: str
│    cost_ceiling_usd: float | None
│    environment: str
│    input: dict[str, Any]
│    output_mapping: WorkflowStepOutputMapping | None
│    depends_on: list[str]
│    timeout_seconds: int | None
│    max_refinement_rounds: int
│    termination: str
│    max_iterations: int | None
│class WorkflowStepOutputMapping(BaseModel):
│    summary_key: str | None
│    field_mappings: list[WorkflowOutputFieldMapping]
│class WorkflowOutputFieldMapping(BaseModel):
│    source_task: str
│    source_field: str
│    target_key: str
│class WorkflowTriggerSchema(BaseModel):
│    type: str
│    schedule: str | None
│    event_type: str | None
│    match_patterns: list[str]
│class WorkflowBudgetSchema(BaseModel):
│    max_cost_usd: float
│    max_tokens: int | None
│class WorkflowObjectiveSchema(BaseModel):
│    statement: str
│    category: str
│    owner: str
│    priority: str
│    regulatory_reference: str | None
│class WorkflowListResponse(BaseModel):
│    workflow_name: str
│    description: str
│    version: int
│    enabled: bool
│    trigger_type: str
│    step_count: int
│    budget_usd: float
│    objective_category: str
│    objective_priority: str
│    objective_owner: str
│class WorkflowDetailResponse(BaseModel):
│    workflow_name: str
│    description: str
│    objective: WorkflowObjectiveSchema
│    version: int
│    enabled: bool
│    trigger: WorkflowTriggerSchema
│    budget: WorkflowBudgetSchema
│    context_keys: list[str]
│    steps: list[WorkflowStepSchema]

modules/backend/schemas/auth.py (115 lines):
│class ApiKeyCreateRequest(BaseModel):
│    name: str
│    expires_in_days: int | None
│class LoginRequest(BaseModel):
│    email: EmailStr
│    password: str
│class TokenRefreshRequest(BaseModel):
│    refresh_token: str
│class ChangePasswordRequest(BaseModel):
│    old_password: str
│    new_password: str
│class ResetPasswordRequest(BaseModel):
│    new_password: str
│class LoginResponse(BaseModel):
│    access_token: str
│    refresh_token: str
│    token_type: str
│    user: UserResponse
│class TokenRefreshResponse(BaseModel):
│    access_token: str
│    refresh_token: str
│    token_type: str
│class ApiKeyCreateResponse(BaseModel):
│    id: str
│    name: str
│    key: str
│    key_prefix: str
│    expires_at: datetime | None
│    created_at: datetime
│class ApiKeyResponse(BaseModel):
│    id: str
│    name: str
│    key_prefix: str
│    expires_at: datetime | None
│    revoked_at: datetime | None
│    last_used_at: datetime | None
│    created_at: datetime
│def build_api_key_create_response(full_key: str, api_key: object) -> 'ApiKeyCreateResponse'

modules/backend/schemas/note.py (71 lines):
│class NoteResponse(BaseModel):
│    id: str
│    title: str
│    content: str | None
│    is_archived: bool
│    created_at: datetime
│    updated_at: datetime
│class NoteCreate(BaseModel):
│    title: str
│    content: str | None
│class NoteUpdate(BaseModel):
│    title: str | None
│    content: str | None
│    is_archived: bool | None
│class NoteListResponse(BaseModel):
│    id: str
│    title: str
│    is_archived: bool
│    created_at: datetime

modules/backend/schemas/execution_record.py (120 lines):
│class ExecutionRecordResponse(BaseModel):
│    id: str
│    session_id: str
│    roster_name: str | None
│    status: str
│    total_cost_usd: float
│    started_at: datetime | None
│    completed_at: datetime | None
│    parent_execution_record_id: str | None
│    created_at: datetime
│    updated_at: datetime
│class ExecutionCostBreakdown(BaseModel):
│    execution_id: str
│    total_cost_usd: float
│    task_costs: list[dict]
│    model_costs: dict[str, float]
│    attempt_count: int
│    total_input_tokens: int
│    total_output_tokens: int
│class TaskExecutionResponse(BaseModel):
│    id: str
│    task_id: str
│    agent_name: str
│    status: str
│    output_data: dict | None
│    token_usage: dict | None
│    cost_usd: float
│    duration_seconds: float | None
│    verification_outcome: dict | None
│    started_at: datetime | None
│    completed_at: datetime | None
│    created_at: datetime
│class TaskAttemptResponse(BaseModel):
│    id: str
│    attempt_number: int
│    status: str
│    failure_tier: str | None
│    failure_reason: str | None
│    feedback_provided: str | None
│    input_tokens: int
│    output_tokens: int
│    cost_usd: float
│    created_at: datetime
│class ExecutionDecisionResponse(BaseModel):
│    id: str
│    decision_type: str
│    task_id: str | None
│    reasoning: str
│    created_at: datetime
│class TaskExecutionDetailResponse(TaskExecutionResponse):
│    attempts: list[TaskAttemptResponse]
│class ExecutionRecordDetailResponse(ExecutionRecordResponse):
│    objective_statement: str | None
│    objective_category: str | None
│    task_plan_json: dict | None
│    execution_outcome_json: dict | None
│    planning_thinking_trace: str | None
│    task_executions: list[TaskExecutionResponse]
│    decisions: list[ExecutionDecisionResponse]
│class ExecutionListResponse(BaseModel):
│    executions: list[ExecutionRecordResponse]
│    total: int
│    page_size: int
│    offset: int

modules/backend/schemas/mission.py (145 lines):
│class MissionCreate(BaseModel):
│    name: str
│    description: str
│    brief: str | None
│    owner_id: str
│    team_id: str | None
│    default_roster: str
│    budget_ceiling_usd: float | None
│    repo_url: str | None
│    repo_root: str | None
│    tier: str
│    execution_environment: str | None
│class MissionUpdate(BaseModel):
│    description: str | None
│    brief: str | None
│    status: str | None
│    default_roster: str | None
│    budget_ceiling_usd: float | None
│    repo_url: str | None
│    repo_root: str | None
│    execution_environment: str | None
│class MissionMemberAddRequest(BaseModel):
│    user_id: str
│    role: str
│class MissionMemberUpdateRequest(BaseModel):
│    role: str
│class MissionResponse(BaseModel):
│    id: str
│    name: str
│    description: str
│    brief: str | None
│    status: str
│    owner_id: str
│    team_id: str | None
│    default_roster: str
│    budget_ceiling_usd: float | None
│    repo_url: str | None
│    repo_root: str | None
│    tier: str
│    execution_environment: str | None
│    created_at: datetime
│    updated_at: datetime
│class MissionMemberResponse(BaseModel):
│    id: str
│    mission_id: str
│    user_id: str
│    role: str
│    created_at: datetime

modules/backend/schemas/workflow_schedule.py (80 lines):
│class WorkflowScheduleCreateRequest(BaseModel):
│    workflow_definition_id: str
│    cron_expression: str
│    timezone: str
│    description: str
│    budget_per_run_usd: float | None
│    max_iterations: int | None
│    cooldown_seconds: int
│class WorkflowScheduleUpdateRequest(BaseModel):
│    cron_expression: str | None
│    timezone: str | None
│    enabled: bool | None
│    description: str | None
│    budget_per_run_usd: float | None
│    max_iterations: int | None
│    cooldown_seconds: int | None
│class WorkflowScheduleResponse(BaseModel):
│    id: str
│    workflow_definition_id: str
│    mission_id: str
│    cron_expression: str
│    timezone: str
│    enabled: bool
│    description: str
│    budget_per_run_usd: float | None
│    max_iterations: int | None
│    iteration_count: int
│    cooldown_seconds: int
│    last_fired_at: datetime | None
│    next_fire_at: datetime | None
│    created_by: str
│    created_at: datetime
│    updated_at: datetime

modules/backend/schemas/client_error.py (20 lines):
│class ClientErrorReport(BaseModel):
│    message: str
│    stack: str | None
│    component_stack: str | None
│    url: str
│    user_agent: str | None
│    timestamp: str | None
│class ClientErrorReceived(BaseModel):
│    received: bool

modules/backend/schemas/agent_catalog.py (98 lines):
│class AgentCatalogResponse(BaseModel):
│    id: str
│    agent_name: str
│    agent_type: str
│    version: str
│    description: str
│    enabled: bool
│    visibility: str
│    keywords: list[str]
│    tools: list[str]
│    model_config_json: dict[str, Any]
│    scope: dict[str, Any]
│class AgentCatalogDetailResponse(BaseModel):
│    id: str
│    agent_name: str
│    agent_type: str
│    version: str
│    description: str
│    system_prompt: str
│    model_config_json: dict[str, Any]
│    tools: list[str]
│    scope: dict[str, Any]
│    interface: dict[str, Any] | None
│    constraints: dict[str, Any]
│    keywords: list[str]
│    enabled: bool
│    visibility: str
│    created_at: datetime
│    updated_at: datetime
│class AgentCatalogCreateRequest(BaseModel):
│    agent_name: str
│    agent_type: str
│    version: str
│    description: str
│    system_prompt: str
│    model_config_json: dict[str, Any]
│    tools: list[str]
│    scope: dict[str, Any]
│    interface: dict[str, Any] | None
│    constraints: dict[str, Any]
│    keywords: list[str]
│    enabled: bool
│    visibility: str
│class SystemPromptUpdateRequest(BaseModel):
│    content: str
│    changed_by: str
│    change_reason: str | None

modules/backend/schemas/execution.py (81 lines):
│class ExecutionCreate(BaseModel):
│    objective: str
│    mission_id: str | None
│    roster_ref: str
│    complexity_tier: str
│    triggered_by: str
│    cost_ceiling_usd: float | None
│    upstream_context: dict | None
│class ExecutionResponse(BaseModel):
│    id: str
│    workflow_run_id: str | None
│    workflow_step_id: str | None
│    objective: str
│    roster_ref: str
│    complexity_tier: str
│    status: str
│    session_id: str
│    trigger_type: str
│    triggered_by: str
│    total_cost_usd: float
│    cost_ceiling_usd: float | None
│    started_at: datetime | None
│    completed_at: datetime | None
│class ExecutionDetailResponse(BaseModel):
│    id: str
│    workflow_run_id: str | None
│    workflow_step_id: str | None
│    objective: str
│    roster_ref: str
│    complexity_tier: str
│    status: str
│    session_id: str
│    trigger_type: str
│    triggered_by: str
│    upstream_context: dict
│    context: dict
│    total_cost_usd: float
│    cost_ceiling_usd: float | None
│    started_at: datetime | None
│    completed_at: datetime | None
│    result_summary: str | None
│    error_data: dict | None
│class ExecutionStateSummary(BaseModel):
│    execution_id: str
│    objective: str
│    status: str
│    roster_ref: str
│    total_cost_usd: float
│    cost_ceiling_usd: float | None
│    started_at: datetime | None
│    elapsed_seconds: float | None

modules/backend/schemas/mission_team.py (68 lines):
│class AgentConfigSummary(BaseModel):
│    agent_name: str
│    agent_type: str
│    description: str
│    model: dict[str, Any]
│    tools: list[str]
│    scope: dict[str, Any]
│    constraints: dict[str, Any]
│    chat_enabled: bool
│class MissionTeamAddRequest(BaseModel):
│    agent_catalog_id: str
│    user_prompt: str | None
│    display_order: int
│    custom_constraints: dict[str, Any] | None
│class UserPromptUpdateRequest(BaseModel):
│    content: str
│    changed_by: str
│    change_reason: str | None
│class MissionTeamMemberResponse(BaseModel):
│    id: str
│    mission_id: str
│    agent_catalog_id: str
│    user_prompt: str | None
│    user_prompt_version: int
│    enabled: bool
│    display_order: int
│    custom_constraints: dict[str, Any] | None
│    created_at: datetime
│    updated_at: datetime
│    agent: AgentConfigSummary | None

modules/backend/schemas/mission_plan.py (192 lines):
│class PlanTaskStateResponse(BaseModel):
│    id: str
│    task_id: str
│    status: str
│    approved_by_user_id: str | None
│    approved_at: datetime | None
│    execution_record_id: str | None
│    task_execution_id: str | None
│    last_attempt_at: datetime | None
│    retry_count: int
│    veto_expires_at: datetime | None
│    result_summary: str | None
│    failure_reason: str | None
│    created_at: datetime
│    updated_at: datetime
│class MissionPlanRefineRequest(BaseModel):
│    instructions: str
│class MissionPlanUpdate(BaseModel):
│    gate_mode: str | None
│    status: str | None
│    budget_usd_ceiling: float | None
│    veto_window_sec: int | None
│class MissionPlanResponse(BaseModel):
│    id: str
│    mission_id: str
│    task_plan_json: dict | None
│    gate_mode: str | None
│    status: str
│    version: int
│    budget_usd_ceiling: float | None
│    total_spent_usd: float
│    veto_window_sec: int | None
│    task_states: list[PlanTaskStateResponse]
│    created_at: datetime
│    updated_at: datetime
│class DispatchApprovedResponse(BaseModel):
│    outcome_status: str
│    execution_record_id: str | None
│    dispatched_task_ids: list[str]
│    updated_task_ids: list[str]
│    total_cost_usd: float
│    new_total_spent_usd: float
│class TaskTransitionResponse(BaseModel):
│    target_task_id: str
│    transitioned_task_ids: list[str]
│    new_status: str

modules/backend/schemas/__init__.py (16 lines):

modules/backend/schemas/mission_context.py (74 lines):
│class ContextUpdateOp(BaseModel):
│    op: str
│    path: str
│    value: Any
│    reason: str
│class ContextUpdateRequest(BaseModel):
│    context_updates: list[ContextUpdateOp]
│class MCDResponse(BaseModel):
│    mission_id: str
│    version: int
│    size_characters: int
│    size_tokens: int
│    context_data: dict
│class ContextChangeResponse(BaseModel):
│    id: str
│    version: int
│    change_type: str
│    path: str
│    old_value: Any | None
│    new_value: Any | None
│    agent_id: str | None
│    mission_id: str | None
│    task_id: str | None
│    reason: str
│    created_at: datetime


## backend.repositories

modules/backend/repositories/base.py (116 lines):
│class BaseRepository:
│    model: type[ModelType]
│    def __init__(session: AsyncSession) -> None
│    def get_by_id(id: str | UUID) -> ModelType
│    def get_by_id_or_none(id: str | UUID) -> ModelType | None
│    def get_all(limit: int, offset: int) -> list[ModelType]
│    def create() -> ModelType
│    def update(id: str | UUID) -> ModelType
│    def delete(id: str | UUID) -> None
│    def exists(id: str | UUID) -> bool
│    def count() -> int

modules/backend/repositories/mission.py (89 lines):
│class MissionRepository:
│    def get_by_name(name: str) -> Mission | None
│    def list_by_owner(owner_id: str, status: MissionStatus | None, limit: int, offset: int) -> list[Mission]
│    def list_active(limit: int, offset: int) -> list[Mission]
│class MissionMemberRepository:
│    def get_members(mission_id: str) -> list[MissionMember]
│    def get_membership(mission_id: str, user_id: str) -> MissionMember | None

modules/backend/repositories/api_key.py (80 lines):
│class ApiKeyRepository:
│    def get_by_prefix(prefix: str) -> list[ApiKey]
│    def list_by_user(user_id: str) -> list[ApiKey]
│    def revoke(key_id: str) -> ApiKey
│    def revoke_all_by_user(user_id: str) -> int
│    def update_last_used(key_id: str) -> None

modules/backend/repositories/user.py (52 lines):
│class UserRepository:
│    def get_by_email(email: str) -> User | None
│    def get_active(user_id: str) -> User | None
│    def list_all(limit: int, offset: int, role_filter: str | None) -> list[User]
│    def update_last_login(user_id: str) -> None

modules/backend/repositories/agent_catalog.py (79 lines):
│class AgentCatalogRepository:
│    def __init__(session: AsyncSession) -> None
│    def get_by_name(agent_name: str) -> AgentCatalog | None
│    def list_enabled(visibility: str | None, limit: int) -> list[AgentCatalog]
│    def list_by_type(agent_type: str, enabled_only: bool) -> list[AgentCatalog]
│    def search_by_keyword(text: str) -> list[AgentCatalog]
│    def is_empty() -> bool

modules/backend/repositories/mission_context.py (110 lines):
│class MissionContextRepository:
│    def get_by_mission_id(mission_id: str) -> MissionContext | None
│    def update_context(mission_id: str, context_data: dict, new_version: int, size_characters: int, size_tokens: int) -> int
│class ContextChangeRepository:
│    def list_by_context(context_id: str, limit: int) -> list[ContextChange]
│    def list_by_agent(context_id: str, agent_id: str, limit: int) -> list[ContextChange]
│class ContextMilestoneRepository:
│    def list_by_mission(mission_id: str, limit: int) -> list[ContextMilestone]

modules/backend/repositories/note.py (137 lines):
│class NoteRepository:
│    def __init__(session: AsyncSession) -> None
│    def get_all_active(limit: int, offset: int) -> list[Note]
│    def get_archived(limit: int, offset: int) -> list[Note]
│    def search_by_title(query: str, limit: int) -> list[Note]
│    def archive(id: str) -> Note
│    def unarchive(id: str) -> Note
│    def count_active() -> int

modules/backend/repositories/workflow_definition.py (60 lines):
│class WorkflowDefinitionRepository:
│    def __init__(session: AsyncSession) -> None
│    def list_by_mission(mission_id: str, enabled_only: bool) -> list[WorkflowDefinition]
│    def get_by_mission_and_name(mission_id: str, name: str) -> WorkflowDefinition | None
│    def list_templates() -> list[WorkflowDefinition]

modules/backend/repositories/execution_record.py (143 lines):
│class ExecutionRecordRepository:
│    def __init__(session: AsyncSession) -> None
│    def get_with_details(execution_id: str) -> ExecutionRecord | None
│    def get_by_session(session_id: str) -> list[ExecutionRecord]
│    def list_executions(status: ExecutionRecordStatus | None, roster_name: str | None, objective_category: str | None, mission_id: str | None, limit: int, offset: int) -> tuple[list[ExecutionRecord], int]
│    def get_decisions(execution_id: str) -> list[ExecutionDecision]
│    def get_task_executions(execution_id: str) -> list[TaskExecution]
│    def get_cost_by_model(execution_id: str) -> dict[str, float]
│    def get_replan_chain(execution_id: str) -> list[ExecutionRecord]

modules/backend/repositories/mission_plan.py (168 lines):
│class MissionPlanRepository:
│    def get_by_mission_id(mission_id: str) -> MissionPlan | None
│    def get_by_mission_id_required(mission_id: str) -> MissionPlan
│    def create_for_mission(mission_id: str) -> MissionPlan
│    def get_task_states(mission_plan_id: str) -> list[PlanTaskState]
│    def get_task_state(mission_plan_id: str, task_id: str) -> PlanTaskState | None
│    def get_task_state_required(mission_plan_id: str, task_id: str) -> PlanTaskState
│    def create_task_state(mission_plan_id: str, task_id: str) -> PlanTaskState
│    def delete_task_states(mission_plan_id: str) -> None

modules/backend/repositories/session.py (242 lines):
│class SessionRepository:
│    def __init__(session: AsyncSession) -> None
│    def get_active_by_user(user_id: str, limit: int, offset: int) -> list[Session]
│    def get_by_user(user_id: str | None, mission_id: str | None, status_filter: str | None, limit: int, offset: int) -> list[Session]
│    def count_by_user(user_id: str | None, mission_id: str | None, status_filter: str | None) -> int
│    def update_last_activity(session_id: str, new_expires_at: datetime | None) -> None
│    def find_expired(now: datetime | None) -> list[Session]
│    def bind_channel(session_id: str, channel_type: str, channel_id: str) -> SessionChannel
│    def unbind_channel(session_id: str, channel_type: str, channel_id: str) -> None
│    def get_session_by_channel(channel_type: str, channel_id: str) -> Session | None
│    def add_message(session_id: str, role: str, content: str, sender_id: str | None, model: str | None, input_tokens: int | None, output_tokens: int | None, cost_usd: float | None, tool_name: str | None, tool_call_id: str | None, thinking: str | None) -> SessionMessage
│    def get_messages(session_id: str, limit: int, offset: int) -> list[SessionMessage]
│    def count_messages(session_id: str) -> int

modules/backend/repositories/mission_history.py (73 lines):
│class MissionDecisionRepository:
│    def list_by_domain(mission_id: str, domain: str, limit: int) -> list[MissionDecision]
│    def list_active(mission_id: str, limit: int) -> list[MissionDecision]
│class MilestoneSummaryRepository:
│    def list_by_mission(mission_id: str, limit: int) -> list[MilestoneSummary]

modules/backend/repositories/mission_team.py (66 lines):
│class MissionTeamRepository:
│    def __init__(session: AsyncSession) -> None
│    def list_by_mission(mission_id: str, enabled_only: bool) -> list[MissionTeamMember]
│    def get_by_mission_and_agent(mission_id: str, agent_catalog_id: str) -> MissionTeamMember | None
│    def update_user_prompt(member_id: str, content: str) -> MissionTeamMember

modules/backend/repositories/prompt_version.py (89 lines):
│class PromptVersionRepository:
│    def __init__(session: AsyncSession) -> None
│    def list_versions(entity_type: str, entity_id: str, limit: int) -> list[PromptVersion]
│    def get_latest(entity_type: str, entity_id: str) -> PromptVersion | None
│    def _next_version(entity_type: str, entity_id: str) -> int
│    def create_version(entity_type: str, entity_id: str, prompt_type: str, content: str, changed_by: str, change_reason: str | None) -> PromptVersion

modules/backend/repositories/execution.py (99 lines):
│class ExecutionRepository:
│    def __init__(session: AsyncSession) -> None
│    def get_by_session(session_id: str) -> list[Execution]
│    def get_by_workflow_run(workflow_run_id: str) -> list[Execution]
│    def count_active() -> int
│    def list_executions(status: ExecutionState | None, workflow_run_id: str | None, mission_id: str | None, limit: int, offset: int) -> tuple[list[Execution], int]

modules/backend/repositories/workflow_schedule.py (112 lines):
│class WorkflowScheduleRepository:
│    def __init__(session: AsyncSession) -> None
│    def list_by_mission(mission_id: str, enabled_only: bool) -> list[WorkflowSchedule]
│    def list_by_workflow(workflow_definition_id: str) -> list[WorkflowSchedule]
│    def list_due(current_time_iso: str) -> list[WorkflowSchedule]
│    def record_fire(schedule_id: str, fired_at_iso: str, next_fire_at_iso: str | None) -> WorkflowSchedule
│    def count_by_mission_today(mission_id: str, today_start_iso: str) -> int

modules/backend/repositories/workflow_run.py (57 lines):
│class WorkflowRunRepository:
│    def __init__(session: AsyncSession) -> None
│    def list_runs(workflow_name: str | None, status: WorkflowRunState | None, limit: int, offset: int) -> tuple[list[WorkflowRun], int]

modules/backend/repositories/__init__.py (4 lines):


## backend.api

modules/backend/api/v1/endpoints/__init__.py (1 lines):

modules/backend/api/__init__.py (1 lines):

modules/backend/api/v1/__init__.py (64 lines):

modules/backend/api/health.py (228 lines):
│def check_database() -> dict[str, Any]
│def check_redis() -> dict[str, Any]
│@router.get
│def health_check() -> dict[str, str]
│@router.get
│def readiness_check() -> dict[str, Any]
│@router.get
│def detailed_health_check() -> dict[str, Any]

modules/backend/api/v1/endpoints/admin.py (433 lines):
│class CatalogCreateRequest(BaseModel):
│    agent_name: str
│    agent_type: str
│    description: str
│    system_prompt: str
│    version: str
│    tools: list[str]
│    keywords: list[str]
│    enabled: bool
│    visibility: str
│    model_config_json: dict[str, Any] | None
│    scope: dict[str, Any] | None
│    interface: dict[str, Any] | None
│    constraints: dict[str, Any] | None
│class CatalogUpdateRequest(BaseModel):
│    description: str | None
│    enabled: bool | None
│    visibility: str | None
│    version: str | None
│    tools: list[str] | None
│    keywords: list[str] | None
│    model_config_json: dict[str, Any] | None
│    scope: dict[str, Any] | None
│    interface: dict[str, Any] | None
│    constraints: dict[str, Any] | None
│class SystemPromptUpdateRequest(BaseModel):
│    content: str
│    change_reason: str | None
│class RoleAssignRequest(BaseModel):
│    user_id: str
│    role: str
│@router.get
│def admin_catalog_list(db: DbSession, request_id: RequestId, _role: AdminRole, ...) -> ApiResponse
│@router.post
│def admin_catalog_create(body: CatalogCreateRequest, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.patch
│def admin_catalog_update(agent_name: str, body: CatalogUpdateRequest, db: DbSession, ...) -> ApiResponse
│@router.delete
│def admin_catalog_delete(agent_name: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.put
│def admin_catalog_update_prompt(agent_name: str, body: SystemPromptUpdateRequest, db: DbSession, ...) -> ApiResponse
│@router.get
│def admin_catalog_prompt_history(agent_name: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.post
│def admin_seed_catalog(db: DbSession, request_id: RequestId, _role: AdminRole, ...) -> ApiResponse
│@router.get
│def admin_metrics_overview(db: DbSession, request_id: RequestId, _role: AdminRole) -> ApiResponse
│@router.get
│def admin_metrics_costs(db: DbSession, request_id: RequestId, _role: AdminRole) -> ApiResponse
│@router.get
│def admin_metrics_agents(db: DbSession, request_id: RequestId, _role: AdminRole) -> ApiResponse
│@router.get
│def admin_metrics_activity(db: DbSession, request_id: RequestId, _role: AdminRole, ...) -> ApiResponse
│@router.get
│def admin_view_config(request_id: RequestId, _role: AdminRole) -> ApiResponse
│@router.post
│def admin_health_check(request_id: RequestId, _role: AdminRole) -> ApiResponse

modules/backend/api/v1/endpoints/admin_users.py (254 lines):
│@router.post
│def create_user(body: UserCreate, _role: AdminRole, db: DbSession, ...) -> ApiResponse
│@router.get
│def list_users(_role: AdminRole, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.get
│def list_roles(request_id: RequestId, _role: AdminRole) -> ApiResponse
│@router.get
│def get_user(user_id: str, _role: AdminRole, db: DbSession, ...) -> ApiResponse
│@router.patch
│def update_user(user_id: str, body: UserUpdate, _role: AdminRole, ...) -> ApiResponse
│@router.delete
│def deactivate_user(user_id: str, _role: AdminRole, db: DbSession, ...) -> ApiResponse
│@router.post
│def reset_password(user_id: str, body: ResetPasswordRequest, _role: AdminRole, ...) -> ApiResponse
│@router.post
│def create_user_api_key(user_id: str, body: ApiKeyCreateRequest, _role: AdminRole, ...) -> ApiResponse
│@router.get
│def list_user_api_keys(user_id: str, _role: AdminRole, db: DbSession, ...) -> ApiResponse
│@router.delete
│def revoke_user_api_key(user_id: str, key_id: str, _role: AdminRole, ...) -> ApiResponse

modules/backend/api/v1/endpoints/agents.py (153 lines):
│class ChatRequest(BaseModel):
│    message: str
│    mission_id: str
│    agent: str | None
│    session_id: str | None
│class ChatResponse(BaseModel):
│    agent_name: str
│    output: str
│    session_id: str | None
│class AgentInfo(BaseModel):
│    agent_name: str
│    description: str
│    keywords: list[str]
│    tools: list[str]
│@router.post
│def agent_chat(data: ChatRequest, db: DbSession, request_id: RequestId) -> ApiResponse[ChatResponse]
│@router.post
│def agent_chat_stream(data: ChatRequest, db: DbSession) -> StreamingResponse
│@router.get
│def agent_registry(request_id: RequestId) -> ApiResponse[list[AgentInfo]]

modules/backend/api/v1/endpoints/auth.py (222 lines):
│@router.post
│def login(body: LoginRequest, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.post
│def refresh_token(body: TokenRefreshRequest, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.get
│def get_me(current_user: CurrentUser, request_id: RequestId) -> ApiResponse
│@router.patch
│def update_me(body: UpdateProfileRequest, current_user: CurrentUser, db: DbSession, ...) -> ApiResponse
│@router.put
│def set_current_mission(body: SetCurrentMissionRequest, current_user: CurrentUser, db: DbSession, ...) -> ApiResponse
│@router.post
│def create_api_key(body: ApiKeyCreateRequest, current_user: CurrentUser, db: DbSession, ...) -> ApiResponse
│@router.get
│def list_api_keys(current_user: CurrentUser, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.delete
│def revoke_api_key(key_id: str, current_user: CurrentUser, db: DbSession, ...) -> ApiResponse
│@router.post
│def change_password(body: ChangePasswordRequest, current_user: CurrentUser, db: DbSession, ...) -> ApiResponse

modules/backend/api/v1/endpoints/catalog.py (68 lines):
│@router.get
│def list_catalog_agents(db: DbSession, request_id: RequestId, agent_type: str | None, ...) -> ApiResponse
│@router.get
│def get_catalog_agent(agent_name: str, db: DbSession, request_id: RequestId) -> ApiResponse

modules/backend/api/v1/endpoints/client_errors.py (47 lines):
│@router.post
│def report_client_error(body: ClientErrorReport, request_id: RequestId) -> ApiResponse

modules/backend/api/v1/endpoints/executions.py (457 lines):
│@router.get
│def list_executions(db: DbSession, request_id: RequestId, status: str | None, ...) -> ApiResponse
│@router.get
│def get_execution(execution_id: str, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.get
│def get_execution_decisions(execution_id: str, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.get
│def get_execution_cost(execution_id: str, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.post
│def execute_execution(execution_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.post
│def cancel_execution(execution_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.post
│def submit_approval(execution_id: str, decision: str, responder_id: str, ...) -> ApiResponse
│@router.get
│def get_execution_status(execution_id: str, db: DbSession, request_id: RequestId) -> ApiResponse

modules/backend/api/v1/endpoints/missions.py (207 lines):
│@router.post
│def create_mission(data: MissionCreate, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.get
│def list_missions(db: DbSession, request_id: RequestId, current_user: CurrentUser, ...) -> ApiResponse
│@router.get
│def get_mission(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.get
│def get_mission_environment(mission_id: str, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.delete
│def delete_mission(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.patch
│def update_mission(mission_id: str, data: MissionUpdate, db: DbSession, ...) -> ApiResponse

modules/backend/api/v1/endpoints/missions_context.py (105 lines):
│@router.get
│def get_mission_context(mission_id: str, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.get
│def get_context_history(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.get
│def get_console_history(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse

modules/backend/api/v1/endpoints/missions_plan.py (334 lines):
│def _require_mission_access(db, mission_id: str, current_user) -> None
│@router.get
│def get_plan(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.patch
│def update_plan(mission_id: str, data: MissionPlanUpdate, db: DbSession, ...) -> ApiResponse
│@router.post
│def refine_plan(mission_id: str, data: MissionPlanRefineRequest, db: DbSession, ...) -> ApiResponse
│@router.post
│def dispatch_approved(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.post
│def approve_task(mission_id: str, task_id: str, db: DbSession, ...) -> ApiResponse
│@router.post
│def reject_task(mission_id: str, task_id: str, db: DbSession, ...) -> ApiResponse
│@router.post
│def retry_task(mission_id: str, task_id: str, db: DbSession, ...) -> ApiResponse

modules/backend/api/v1/endpoints/missions_team.py (302 lines):
│@router.get
│def list_mission_team(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.post
│def add_agent_to_team(mission_id: str, data: MissionTeamAddRequest, db: DbSession, ...) -> ApiResponse
│@router.post
│def seed_team_from_catalog(mission_id: str, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.delete
│def remove_agent_from_team(mission_id: str, member_id: str, db: DbSession, ...) -> ApiResponse
│@router.put
│def update_team_member_prompt(mission_id: str, member_id: str, data: UserPromptUpdateRequest, ...) -> ApiResponse
│@router.get
│def get_team_member_prompt_history(mission_id: str, member_id: str, db: DbSession, ...) -> ApiResponse
│@router.get
│def list_mission_members(mission_id: str, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.post
│def add_mission_member(mission_id: str, data: MissionMemberAddRequest, db: DbSession, ...) -> ApiResponse
│@router.patch
│def update_mission_member(mission_id: str, user_id: str, data: MissionMemberUpdateRequest, ...) -> ApiResponse
│@router.delete
│def remove_mission_member(mission_id: str, user_id: str, db: DbSession, ...) -> ApiResponse

modules/backend/api/v1/endpoints/missions_workflows.py (298 lines):
│@router.get
│def list_mission_workflows(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.post
│def import_workflow_template(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.get
│def get_mission_workflow(mission_id: str, workflow_name: str, db: DbSession, ...) -> ApiResponse
│@router.get
│def list_mission_schedules(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.post
│def create_mission_schedule(mission_id: str, data: WorkflowScheduleCreateRequest, db: DbSession, ...) -> ApiResponse
│@router.patch
│def update_mission_schedule(mission_id: str, schedule_id: str, data: WorkflowScheduleUpdateRequest, ...) -> ApiResponse
│@router.delete
│def delete_mission_schedule(mission_id: str, schedule_id: str, db: DbSession, ...) -> ApiResponse
│@router.post
│def architect_chat(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse

modules/backend/api/v1/endpoints/notes.py (193 lines):
│@router.post
│def create_note(data: NoteCreate, db: DbSession, request_id: RequestId) -> ApiResponse[NoteResponse]
│@router.get
│def list_notes(db: DbSession, request_id: RequestId, pagination: PaginationParams, ...) -> dict[str, Any]
│@router.get
│def search_notes(db: DbSession, request_id: RequestId, q: str, ...) -> ApiResponse[list[NoteListResponse]]
│@router.get
│def get_note(note_id: str, db: DbSession, request_id: RequestId) -> ApiResponse[NoteResponse]
│@router.patch
│def update_note(note_id: str, data: NoteUpdate, db: DbSession, ...) -> ApiResponse[NoteResponse]
│@router.delete
│def delete_note(note_id: str, db: DbSession, request_id: RequestId) -> None
│@router.post
│def archive_note(note_id: str, db: DbSession, request_id: RequestId) -> ApiResponse[NoteResponse]
│@router.post
│def unarchive_note(note_id: str, db: DbSession, request_id: RequestId) -> ApiResponse[NoteResponse]

modules/backend/api/v1/endpoints/sessions.py (299 lines):
│@router.post
│def create_session(data: SessionCreate, db: DbSession, request_id: RequestId, ...) -> ApiResponse[SessionResponse]
│@router.get
│def get_session(session_id: str, db: DbSession, request_id: RequestId) -> ApiResponse[SessionResponse]
│@router.patch
│def update_session(session_id: str, data: SessionUpdate, db: DbSession, ...) -> ApiResponse[SessionResponse]
│@router.get
│def list_sessions(db: DbSession, request_id: RequestId, pagination: PaginationParams, ...) -> dict
│@router.post
│def suspend_session(session_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse[SessionResponse]
│@router.post
│def resume_session(session_id: str, db: DbSession, request_id: RequestId) -> ApiResponse[SessionResponse]
│@router.post
│def complete_session(session_id: str, db: DbSession, request_id: RequestId) -> ApiResponse[SessionResponse]
│@router.post
│def bind_channel(session_id: str, data: ChannelBindRequest, db: DbSession, ...) -> ApiResponse[ChannelResponse]
│@router.delete
│def unbind_channel(session_id: str, channel_type: str, channel_id: str, ...) -> None
│@router.get
│def get_session_by_channel(channel_type: str, channel_id: str, db: DbSession, ...) -> ApiResponse[SessionResponse]
│@router.get
│def get_messages(session_id: str, db: DbSession, request_id: RequestId, ...) -> dict
│@router.post
│def send_message_stream(session_id: str, mission_id: str, data: SessionMessageCreate, ...) -> StreamingResponse

modules/backend/api/v1/endpoints/streams.py (242 lines):
│def _require_mission_access(db, mission_id: str, user: User) -> None
│def _require_session_access(db, session_id: str, user: User) -> None
│@router.get
│def stream_run_events(session_id: str, user: SseUser, db: DbSession) -> StreamingResponse
│@router.get
│def stream_notifications(user: SseUser, user_id: str) -> StreamingResponse
│@router.get
│def stream_mission_events(mission_id: str, user: SseUser, db: DbSession) -> StreamingResponse

modules/backend/api/v1/endpoints/workflows.py (185 lines):
│def _get_workflow_service() -> WorkflowService
│def _get_execution_service(db: DbSession) -> ExecutionService
│@router.get
│def list_workflows(request_id: RequestId, enabled_only: bool) -> ApiResponse
│@router.get
│def get_workflow(workflow_name: str, request_id: RequestId) -> ApiResponse
│@router.post
│def create_execution(data: ExecutionCreate, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.get
│def list_missions(db: DbSession, request_id: RequestId, status: str | None, ...) -> ApiResponse
│@router.get
│def get_mission(mission_id: str, db: DbSession, request_id: RequestId) -> ApiResponse
│@router.post
│def cancel_mission(mission_id: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse

modules/backend/api/v1/endpoints/workshop.py (123 lines):
│class WorkshopRunRequest(BaseModel):
│    inputs: dict[str, Any] | None
│    prompt_override: str | None
│    session_id: str | None
│    budget_usd: float | None
│@router.post
│def workshop_run(agent_name: str, body: WorkshopRunRequest, db: DbSession, ...) -> ApiResponse
│@router.get
│def workshop_cached_inputs(agent_name: str, db: DbSession, request_id: RequestId, ...) -> ApiResponse
│@router.get
│def workshop_list_runs(db: DbSession, request_id: RequestId, agent_name: str | None, ...) -> ApiResponse


## backend.events

modules/backend/events/types.py (487 lines):
│class SessionEvent(BaseModel):
│    event_id: uuid.UUID
│    event_type: str
│    session_id: uuid.UUID
│    timestamp: datetime
│    source: str
│    correlation_id: str | None
│    trace_id: str | None
│    metadata: dict
│class UserMessageEvent(SessionEvent):
│    event_type: str
│    content: str
│    channel: str
│    attachments: list[str]
│class UserApprovalEvent(SessionEvent):
│    event_type: str
│    decision: str
│    approval_request_id: str
│    reason: str | None
│    modified_params: dict
│class AgentThinkingEvent(SessionEvent):
│    event_type: str
│    agent_id: str
│class AgentToolCallEvent(SessionEvent):
│    event_type: str
│    agent_id: str
│    tool_name: str
│    tool_args: dict
│    tool_call_id: str
│class AgentToolResultEvent(SessionEvent):
│    event_type: str
│    agent_id: str
│    tool_name: str
│    tool_call_id: str
│    result: str | None
│    status: str
│    error_detail: str | None
│class AgentResponseChunkEvent(SessionEvent):
│    event_type: str
│    agent_id: str
│    content: str
│    is_final: bool
│class AgentResponseCompleteEvent(SessionEvent):
│    event_type: str
│    agent_id: str
│    full_content: str
│    input_tokens: int
│    output_tokens: int
│    cost_usd: float
│    model: str
│class ApprovalRequestedEvent(SessionEvent):
│    event_type: str
│    approval_request_id: str
│    agent_id: str
│    action: str
│    context: dict
│    allowed_decisions: list[str]
│    responder_options: list[str]
│    timeout_seconds: int
│class ApprovalResponseEvent(SessionEvent):
│    event_type: str
│    approval_request_id: str
│    decision: str
│    responder_type: str
│    responder_id: str | None
│    reason: str | None
│    modified_params: dict
│class PlanningPhaseEvent(SessionEvent):
│    event_type: str
│    step: str
│    message: str
│class PlanCreatedEvent(SessionEvent):
│    event_type: str
│    plan_id: str
│    goal: str
│    step_count: int
│class PlanStepStartedEvent(SessionEvent):
│    event_type: str
│    plan_id: str
│    step_id: str
│    step_name: str
│    assigned_agent: str
│class PlanStepCompletedEvent(SessionEvent):
│    event_type: str
│    plan_id: str
│    step_id: str
│    result_summary: str
│    status: str
│class PlanRevisedEvent(SessionEvent):
│    event_type: str
│    plan_id: str
│    revision_reason: str
│    steps_added: int
│    steps_removed: int
│    steps_modified: int
│class CostUpdateEvent(SessionEvent):
│    event_type: str
│    input_tokens: int
│    output_tokens: int
│    cost_usd: float
│    cumulative_cost_usd: float
│    budget_remaining_usd: float | None
│    model: str
│    source_event_type: str
│class WorkflowRunStartedEvent(SessionEvent):
│    event_type: str
│    workflow_run_id: str
│    workflow_name: str
│    workflow_version: int
│    step_count: int
│    trigger_type: str
│    triggered_by: str
│class WorkflowExecutionStartedEvent(SessionEvent):
│    event_type: str
│    workflow_run_id: str
│    mission_id: str
│    step_id: str
│    roster_ref: str
│    complexity_tier: str
│class WorkflowExecutionCompletedEvent(SessionEvent):
│    event_type: str
│    workflow_run_id: str
│    mission_id: str
│    step_id: str
│    success: bool
│    cost_usd: float
│class WorkflowRunCompletedEvent(SessionEvent):
│    event_type: str
│    workflow_run_id: str
│    workflow_name: str
│    total_cost_usd: float
│    mission_count: int
│    elapsed_seconds: float | None
│    result_summary: str | None
│class WorkflowRunFailedEvent(SessionEvent):
│    event_type: str
│    workflow_run_id: str
│    workflow_name: str
│    error: str
│    failed_step: str | None
│    total_cost_usd: float
│class WorkflowGraphEvent(SessionEvent):
│    event_type: str
│    graph_data: dict
│    workflow_name: str
│    step_count: int
│class ConvergenceIterationEvent(SessionEvent):
│    event_type: str
│    loop_task_id: str
│    cycle_number: int
│    findings_count: int
│    fixes_applied: int
│    convergence_metric: float | None
│    converged: bool
│class ConvergenceCompletedEvent(SessionEvent):
│    event_type: str
│    loop_task_id: str
│    total_cycles: int
│    final_metric: float | None
│    outcome: str
│class FinalVerificationEvent(SessionEvent):
│    event_type: str
│    loop_task_id: str
│    passed: bool
│    test_summary: str
│    environment_mode: str
│class MissionNarrativeEvent(SessionEvent):
│    event_type: str
│    mission_id: str
│    agent_id: str
│    narrative: str
│    phase: str
│    level: str
│class MissionArtifactFoundEvent(SessionEvent):
│    event_type: str
│    mission_id: str
│    agent_id: str
│    artifact_type: str
│    title: str
│    content: str
│    content_type: str
│    language: str
│class SystemEvent(SessionEvent):
│    event_type: str
│    level: str
│    message: str
│    mission_id: str
│class SystemExecutionCreatedEvent(SessionEvent):
│    event_type: str
│    execution_id: str
│    mission_id: str
│    objective: str
│    triggered_by: str
│class SystemExecutionCompletedEvent(SessionEvent):
│    event_type: str
│    execution_id: str
│    mission_id: str
│    status: str
│    total_cost_usd: float
│    duration_seconds: float
│    task_count: int
│class SystemBudgetWarningEvent(SessionEvent):
│    event_type: str
│    mission_id: str
│    current_cost_usd: float
│    budget_usd: float
│    message: str
│class SystemSessionCreatedEvent(SessionEvent):
│    event_type: str
│    target_session_id: str
│    mission_id: str
│    agent_id: str
│    goal: str
│def deserialize_event(data: dict) -> SessionEvent | None

modules/backend/events/schemas.py (33 lines):
│class EventEnvelope(BaseModel):
│    event_id: str
│    event_type: str
│    event_version: int
│    timestamp: str
│    source: str
│    correlation_id: str
│    trace_id: str | None
│    session_id: str | None
│    payload: dict

modules/backend/events/bus.py (120 lines):
│class SessionEventBus:
│    def __init__(redis: Redis) -> None
│    def _channel_name(session_id: uuid.UUID) -> str
│    def publish(event: SessionEvent) -> None
│    def _mission_channel_name(mission_id: str) -> str
│    def publish_to_mission(mission_id: str, event: SessionEvent) -> None
│    def subscribe(session_id: uuid.UUID) -> AsyncIterator[SessionEvent]

modules/backend/events/publishers.py (47 lines):
│class EventPublisher:
│    def publish(stream: str, event: EventEnvelope) -> None

modules/backend/events/__init__.py (57 lines):

modules/backend/events/broker.py (91 lines):
│def create_event_broker() -> 'RedisBroker'
│def get_event_broker() -> 'RedisBroker'
│def create_event_app() -> 'FastStream'

modules/backend/events/middleware.py (106 lines):
│class EventObservabilityMiddleware:
│    def __init__() -> None
│    def on_receive() -> None
│    def after_processed(exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any | None) -> bool | None
│    def __aenter__() -> 'EventObservabilityMiddleware'
│    def __aexit__(exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any | None) -> bool | None
│    def consume_scope(call_next: Callable, msg: Any) -> Any


## backend.gateway

modules/backend/gateway/adapters/base.py (115 lines):
│class ChannelAdapter(ABC):
│    def channel_name() -> str
│    def deliver_response(response: AgentResponse) -> bool
│    def format_text(text: str) -> str
│    def max_message_length() -> int
│    def chunk_message(text: str) -> list[str]
│class AgentResponse:
│    text: str
│    session_key: str
│    channel: str
│    reply_to_message_id: str | None
│    media: list[dict] | None
│    cost_usd: float | None
│    token_input: int | None
│    token_output: int | None
│    duration_ms: int | None
│    agent_name: str | None
│class ChannelMessage:
│    channel: str
│    user_id: str
│    text: str
│    session_key: str
│    message_id: str | None
│    group_id: str | None
│    is_group: bool
│    reply_to_message_id: str | None
│    media: list[dict] | None
│    raw_event: dict | None
│    received_at: str

modules/backend/gateway/adapters/__init__.py (13 lines):

modules/backend/gateway/__init__.py (1 lines):

modules/backend/gateway/adapters/telegram.py (110 lines):
│class TelegramAdapter(ChannelAdapter):
│    def __init__(bot: 'Bot') -> None
│    def channel_name() -> str
│    def max_message_length() -> int
│    def deliver_response(response: AgentResponse) -> bool
│    def format_text(text: str) -> str
│def _convert_markdown_bold(text: str) -> str
│def _convert_markdown_italic(text: str) -> str
│def _convert_markdown_code(text: str) -> str

modules/backend/gateway/registry.py (68 lines):
│def _register_enabled_adapters() -> None
│def get_adapter(channel_name: str) -> ChannelAdapter | None
│def get_all_adapters() -> dict[str, ChannelAdapter]
│def is_channel_enabled(channel_name: str) -> bool

modules/backend/gateway/security/__init__.py (1 lines):

modules/backend/gateway/security/rate_limiter.py (118 lines):
│class RateLimitResult:
│    def __init__(allowed: bool, retry_after_seconds: int) -> None
│class GatewayRateLimiter:
│    def __init__() -> None
│    def check(channel: str, user_id: str) -> RateLimitResult
│    def _get_limits(channel: str) -> dict | None
│    def _check_window(key: str, store: dict[str, list[float]], now: float, window_seconds: int, max_requests: int) -> RateLimitResult
│def get_rate_limiter() -> GatewayRateLimiter

modules/backend/gateway/security/startup_checks.py (137 lines):
│class StartupSecurityError(RuntimeError):
│def run_startup_checks() -> None
│def _check_secret_strength(settings: Settings, security_config: SecuritySchema, features: FeaturesSchema, ...) -> None
│def _check_channel_secrets(settings: Settings, features: FeaturesSchema, errors: list[str]) -> None
│def _check_production_safety(app_config: AppConfig, is_production: bool, errors: list[str]) -> None
│def _check_channel_allowlists(app_config: AppConfig, features: FeaturesSchema, errors: list[str]) -> None


## backend.temporal

modules/backend/temporal/models.py (84 lines):
│class MissionWorkflowInput:
│    mission_run_id: str
│    session_id: str
│    mission_brief: str
│    roster_name: str
│    mission_budget_usd: float
│    mission_id: str | None
│    execution_mode: str | None
│    approval_timeout_seconds: int
│    escalation_timeout_seconds: int
│    notification_timeout_seconds: int
│class WorkflowStatus:
│    mission_id: str
│    workflow_status: str
│    mission_status: str | None
│    total_cost_usd: float
│    waiting_for_approval: bool
│    error: str | None
│class ApprovalDecision:
│    decision: str
│    responder_type: str
│    responder_id: str
│    reason: str | None
│class NotificationPayload:
│    channel: str
│    recipient: str
│    title: str
│    body: str
│    action_url: str
│    urgency: str
│class MissionExecutionResult:
│    mission_id: str
│    status: str
│    total_cost_usd: float
│    total_duration_seconds: float
│    task_count: int
│    success_count: int
│    failed_count: int
│    outcome_json: dict
│class MissionModification:
│    instruction: str
│    reasoning: str

modules/backend/temporal/activities.py (145 lines):
│@activity.defn
│def execute_mission(input: MissionWorkflowInput) -> MissionExecutionResult
│@activity.defn
│def persist_mission_outcome(mission_run_id: str, session_id: str, roster_name: str, ...) -> bool
│@activity.defn
│def send_notification(payload: NotificationPayload) -> bool

modules/backend/temporal/client.py (55 lines):
│def get_temporal_config()
│def get_temporal_client()

modules/backend/temporal/workflow.py (249 lines):
│class AgentMissionWorkflow:
│    def __init__() -> None
│    def submit_approval(decision: ApprovalDecision) -> None
│    def get_status() -> WorkflowStatus
│    def run(input: MissionWorkflowInput) -> WorkflowStatus
│    def _wait_for_approval_with_escalation(input: MissionWorkflowInput, notification_timeout: timedelta) -> None

modules/backend/temporal/__init__.py (1 lines):

modules/backend/temporal/worker.py (54 lines):
│def start_worker() -> None
│def main() -> None


## backend.migrations

modules/backend/migrations/env.py (130 lines):
│def get_database_url() -> str
│def run_migrations_offline() -> None
│def do_run_migrations(connection: Connection) -> None
│def run_async_migrations() -> None
│def run_migrations_online() -> None

modules/backend/migrations/versions/20260320_phase2_schema_expansion.py (116 lines):
│def upgrade() -> None
│def downgrade() -> None

modules/backend/migrations/versions/20260320_phase2b_workflow_schedules.py (54 lines):
│def upgrade() -> None
│def downgrade() -> None

modules/backend/migrations/versions/20260321_phase3_users_and_api_keys.py (149 lines):
│def upgrade() -> None
│def downgrade() -> None

modules/backend/migrations/versions/20260325_phase4_current_mission.py (36 lines):
│def upgrade() -> None
│def downgrade() -> None

modules/backend/migrations/versions/20260402_phase5_mission_tier.py (86 lines):
│def _column_names(bind: sa.Connection, table: str) -> set[str]
│def upgrade() -> None
│def downgrade() -> None

modules/backend/migrations/versions/20260410_plan42_mission_plans.py (239 lines):
│def _table_exists(bind: sa.Connection, table: str) -> bool
│def upgrade() -> None
│def downgrade() -> None

modules/backend/migrations/versions/325b823b2aaa_add_gate_mode_to_missions.py (28 lines):
│def upgrade() -> None
│def downgrade() -> None


## backend.tasks

modules/backend/tasks/__init__.py (28 lines):
│def __getattr__(name: str)

modules/backend/tasks/broker.py (96 lines):
│def create_broker() -> 'ListQueueBroker'
│def get_broker() -> 'ListQueueBroker'
│def __getattr__(name: str)

modules/backend/tasks/example.py (232 lines):
│def send_notification(user_id: str, message: str, channel: str) -> dict[str, Any]
│def process_data(data: dict[str, Any], operation: str) -> dict[str, Any]
│def cleanup_expired_records(table_name: str, older_than_days: int) -> dict[str, Any]
│def generate_report(report_type: str, parameters: dict[str, Any], user_id: str) -> dict[str, Any]
│def register_tasks() -> dict[str, Any]

modules/backend/tasks/scheduled.py (318 lines):
│def daily_cleanup(older_than_days: int) -> dict[str, Any]
│def hourly_health_check() -> dict[str, Any]
│def weekly_report_generation() -> dict[str, Any]
│def metrics_aggregation(interval_minutes: int) -> dict[str, Any]
│def cleanup_stale_environments(idle_timeout_minutes: int, max_lifetime_hours: int) -> dict[str, Any]
│def _container_has_recent_activity(container: Any) -> bool
│def register_scheduled_tasks() -> dict[str, Any]

modules/backend/tasks/scheduler.py (79 lines):
│def create_scheduler() -> 'TaskiqScheduler'
│def get_scheduler() -> 'TaskiqScheduler'
│def __getattr__(name: str)

modules/backend/tasks/workflow_scheduler.py (138 lines):
│def evaluate_workflow_schedules() -> dict[str, Any]
│def _notify_schedule_failure(schedule_id: str, error: str) -> None


## root

modules/__init__.py (6 lines):


## frontend

modules/frontend/node_modules/flatted/python/flatted.py (144 lines):
│class _Known:
│    def __init__()
│class _String:
│    def __init__(value)
│def _array_keys(value)
│def _object_keys(value)
│def _is_array(value)
│def _is_object(value)
│def _is_string(value)
│def _index(known, input, value)
│def _relate(known, input, value)
│def _resolver(input, lazy, parsed)
│def _transform(known, input, value)
│def _wrap(value)
│def parse(value)
│def stringify(value)

