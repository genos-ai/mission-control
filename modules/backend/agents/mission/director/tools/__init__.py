"""Director tool modules — one module per tool.

Follows the shared-tool layout of `modules/backend/tools/`: each module
holds the implementation as a plain async function with explicit
parameters, plus a `register(agent)` that attaches the thin
`@agent.tool` wrapper (P7).

These tools are agent-specific, so they live in the agent's own
directory rather than `modules/backend/tools/`, per the rule in
`docs/10-reference-architecture/47-agentic-module-organization.md`
("When to Create an Agent-Specific Tool"). They deliberately omit the
`TOOL_DEF` dict used by shared tools: `ToolRegistry` only auto-discovers
within `modules.backend.tools`, so a `TOOL_DEF` here would be metadata
nothing reads.
"""
