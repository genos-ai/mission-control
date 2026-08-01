"""Step-executor implementations for WorkflowRunWavesMixin (Plan 84 Phase 5.1).

Split out of workflow_run_waves.py, which had grown past 1800 lines.
Each module holds a cluster of node_type executors; workflow_run_waves.py
keeps the wave-execution engine (_execute_steps, _execute_wave,
_execute_step's dispatch table) and imports these as plain functions.
"""
