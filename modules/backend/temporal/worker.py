"""
Temporal Worker.

Starts a Temporal Worker that executes AgentMissionWorkflow and its
Activities. Run via CLI: python -m modules.backend.temporal.worker
"""

import asyncio

from temporalio.worker import Worker

from modules.backend.core.logging import get_logger
from modules.backend.temporal.activities import (
    execute_mission,
    persist_mission_outcome,
    send_notification,
)
from modules.backend.temporal.chat_activities import (
    execute_chat_turn,
    persist_assistant_message,
    persist_user_message,
)
from modules.backend.temporal.client import get_temporal_client, get_temporal_config
from modules.backend.temporal.chat_workflow import ChatTurnWorkflow
from modules.backend.temporal.mission_run_workflow import MissionRunWorkflow
from modules.backend.temporal.supervisor_activities import (
    approve_proposed_tasks,
    evaluate_post_run,
    fetch_plan_task_counts,
    start_director_turn,
)
from modules.backend.temporal.workflow import AgentMissionWorkflow

logger = get_logger(__name__)


async def start_worker() -> None:
    """Start the Temporal Worker."""
    config = get_temporal_config()
    client = await get_temporal_client()

    worker = Worker(
        client,
        task_queue=config.task_queue,
        workflows=[AgentMissionWorkflow, ChatTurnWorkflow, MissionRunWorkflow],
        activities=[
            # Mission execution (Plan 16)
            execute_mission,
            persist_mission_outcome,
            send_notification,
            # Chat turn (Plan 52 Phase B)
            persist_user_message,
            execute_chat_turn,
            persist_assistant_message,
            # Supervisor loop (Plan 52 Phase C)
            evaluate_post_run,
            approve_proposed_tasks,
            fetch_plan_task_counts,
            start_director_turn,
        ],
    )

    logger.info(
        "Temporal worker starting",
        extra={"task_queue": config.task_queue},
    )

    await worker.run()


def main() -> None:
    """Entry point for running the worker."""
    asyncio.run(start_worker())


if __name__ == "__main__":
    main()
