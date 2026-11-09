"""Secret redaction for stored and emitted error text (Plan 88, contract 3.5.5).

The platform's only secret redactor. Every service that stores exception text
(temporal_sync_error, mission_runs.status_detail) or puts it in an event
payload passes it through redact_secrets first. The patterns, their order and
the replacements are fixed by contract 3.5.5.
"""

import re

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # 1. Telegram bot tokens.
    (re.compile(r"bot\d+:[A-Za-z0-9_-]+"), "bot<redacted>"),
    # 2. Raw action tokens in callback data.
    (re.compile(r"g:[A-Za-z0-9_-]{22}:"), "g:<redacted>:"),
    # 3. Provider keys.
    (re.compile(r"sk-ant-[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{16,}"), "sk-<redacted>"),
    # 4. Bearer tokens.
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
    # 5. URL credentials.
    (re.compile(r"://[^/\s:@]+:[^/\s@]+@"), "://<redacted>@"),
    # 6. NAME=value and key: value secrets, including the platform's own .env names.
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|token|secret|password|passwd|salt|credential))"
            r"([\"']?\s*[=:]\s*)[\"']?[^\s\"',}]+"
        ),
        r"\1\2<redacted>",
    ),
    # 7. GitHub tokens.
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"), "gh<redacted>"),
    # 8. AWS access key ids.
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA<redacted>"),
    # 9. JWTs.
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}(\.[A-Za-z0-9_-]+)?"),
        "eyJ<redacted>",
    ),
    # 10. Stripe-style keys.
    (re.compile(r"(?:sk|pk|ak|rk)[-_](?:live|test|prod)[-_][A-Za-z0-9]{16,}"), "<redacted>"),
)


def redact_secrets(text: str) -> str:
    """Replace every secret the contract 3.5.5 patterns match, in order."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
