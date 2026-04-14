"""
Background Tasks Package.

Plain async functions for scheduled maintenance work. Previously used TaskIQ
for scheduling; now triggered by Temporal Schedules (Plan 56 Phase C).

Submodules:
    scheduled           — Maintenance task functions (daily cleanup, health checks, etc.)
    workflow_scheduler   — Workflow schedule evaluation
"""
