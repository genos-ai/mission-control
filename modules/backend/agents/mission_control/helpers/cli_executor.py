"""CLI agent executor — dispatches tasks to CLI coding agents.

Counterpart to agent_executor.py which handles PydanticAI in-process agents.
Each engine function spawns a subprocess, passes the system prompt and task
instructions, and returns the agent's output as a dict matching the _meta
structure expected by retry_handler.py.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from modules.backend.agents.mission_control.models import EventBusProtocol
from modules.backend.core.config import find_project_root
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

CLI_SUBPROCESS_TIMEOUT_SECONDS = 600


def _cli_result(output: str) -> dict:
    """Normalize CLI executor output to match PydanticAI agent return structure."""
    return {
        "output": output,
        "_meta": {
            "cost_usd": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
        },
    }


def _compose_user_message(instructions: str, inputs: dict) -> str:
    """Build the user message from task instructions and inputs."""
    message = instructions
    if inputs:
        message += f"\n\nInputs:\n```json\n{json.dumps(inputs, indent=2)}\n```"
    return message


async def _run_subprocess(
    cmd: list[str],
    *,
    cwd: str,
    env: dict[str, str] | None = None,
    timeout: float = CLI_SUBPROCESS_TIMEOUT_SECONDS,
    agent_name: str = "",
    engine_label: str = "",
) -> str:
    """Run a CLI subprocess with timeout and cleanup."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        logger.error(
            f"{engine_label} subprocess timed out",
            extra={"agent": agent_name, "timeout": timeout},
        )
        return f"ERROR: {engine_label} subprocess timed out after {timeout}s"

    if proc.returncode != 0:
        logger.error(
            f"{engine_label} subprocess failed",
            extra={
                "agent": agent_name,
                "returncode": proc.returncode,
                "stderr": stderr.decode("utf-8", errors="replace")[:500],
            },
        )

    return stdout.decode("utf-8", errors="replace").strip()


async def execute_claude_code(
    agent_name: str,
    instructions: str,
    inputs: dict,
    *,
    system_prompt: str,
    working_dir: str | Path | None = None,
    effort: str | None = None,
    max_turns: int = 50,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
    scope_read: list[str] | None = None,
    scope_write: list[str] | None = None,
) -> dict:
    """Execute a task via Claude Code Agent SDK."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query, AssistantMessage, TextBlock
    except ImportError:
        raise ImportError(
            "claude-agent-sdk is required for engine='claude_code'. "
            "Install with: pip install claude-agent-sdk"
        )

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        cwd=str(working_dir or find_project_root()),
        max_turns=max_turns,
    )

    allowed_tools = ["Read", "Grep", "Glob"]
    if scope_write:
        allowed_tools.extend(["Write", "Edit", "Bash"])
    options.allowed_tools = allowed_tools

    if effort:
        os.environ["CLAUDE_CODE_EFFORT_LEVEL"] = effort

    user_message = _compose_user_message(instructions, inputs)
    response_parts: list[str] = []

    try:
        async for message in query(prompt=user_message, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_parts.append(block.text)
    finally:
        os.environ.pop("CLAUDE_CODE_EFFORT_LEVEL", None)

    return _cli_result("\n".join(response_parts))


async def execute_codex(
    agent_name: str,
    instructions: str,
    inputs: dict,
    *,
    system_prompt: str,
    working_dir: str | Path | None = None,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
) -> dict:
    """Execute a task via OpenAI Codex CLI (codex exec)."""
    cwd = str(working_dir or find_project_root())
    user_message = _compose_user_message(instructions, inputs)

    cmd = [
        "codex", "exec", user_message,
        "--approval-mode", "never",
        "--full-auto",
    ]
    if system_prompt:
        cmd.extend(["--config", f"developer_instructions={system_prompt}"])

    output = await _run_subprocess(
        cmd, cwd=cwd, agent_name=agent_name, engine_label="Codex",
    )
    return _cli_result(output)


async def execute_copilot(
    agent_name: str,
    instructions: str,
    inputs: dict,
    *,
    system_prompt: str,
    working_dir: str | Path | None = None,
    event_bus: EventBusProtocol | None = None,
    session_id: str | None = None,
) -> dict:
    """Execute a task via GitHub Copilot CLI (copilot -p)."""
    cwd = str(working_dir or find_project_root())
    agents_md = Path(cwd) / "AGENTS.md"
    agents_md_backup = None

    try:
        if system_prompt:
            if agents_md.exists():
                agents_md_backup = agents_md.read_text(encoding="utf-8")
            agents_md.write_text(system_prompt, encoding="utf-8")

        user_message = _compose_user_message(instructions, inputs)
        cmd = ["copilot", "-p", user_message, "-s"]

        output = await _run_subprocess(
            cmd, cwd=cwd, agent_name=agent_name, engine_label="Copilot",
        )
    finally:
        if agents_md_backup is not None:
            agents_md.write_text(agents_md_backup, encoding="utf-8")
        elif system_prompt and agents_md.exists():
            agents_md.unlink()

    return _cli_result(output)
