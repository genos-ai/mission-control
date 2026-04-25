"""
Shared tool implementations (Plan 65 — Tool Registry).

One tool per file. File name matches the exported function name.
Convention: verb_noun (e.g. search_web, fetch_url, read_file).

Tools are pure async functions with no PydanticAI dependency.
They accept explicit parameters and delegate to the service layer.
Agent @agent.tool wrappers extract deps from RunContext and call these.
"""
