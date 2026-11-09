"""redact_secrets (Plan 88 step 88.1.6, contract 3.5.5)."""

import re

from modules.backend.core.config import find_project_root
from modules.backend.core.redaction import redact_secrets


def test_redacts_bot_token() -> None:
    out = redact_secrets("https://api.telegram.org/bot123:AA-b_c/sendMessage")
    assert "123:AA-b_c" not in out
    assert "bot<redacted>" in out


def test_redacts_action_token() -> None:
    raw = "g:" + "A" * 22 + ":approve"
    out = redact_secrets(f"callback {raw}")
    assert "A" * 22 not in out
    assert "g:<redacted>:approve" in out


def test_redacts_provider_key() -> None:
    out = redact_secrets("key sk-ant-api03-abcDEF_123 and sk-abcdefghijklmnop1234")
    assert "abcDEF_123" not in out
    assert "abcdefghijklmnop1234" not in out
    assert out.count("sk-<redacted>") == 2


def test_redacts_bearer() -> None:
    out = redact_secrets("Authorization: Bearer abc.def-ghi~jkl")
    assert "abc.def-ghi~jkl" not in out
    assert "Bearer <redacted>" in out


def test_redacts_url_credentials() -> None:
    out = redact_secrets("postgresql://admin:hunter2@db.local:5432/app")
    assert "hunter2" not in out
    assert "admin" not in out
    assert "postgresql://<redacted>@db.local:5432/app" == out


def test_redacts_key_value_secret() -> None:
    out = redact_secrets('{"client_secret": "s3cr3tvalue", other}')
    assert "s3cr3tvalue" not in out
    assert "<redacted>" in out


def test_redacts_github_token() -> None:
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k"
    pat = "github_pat_" + "11ABCDEFG0123456789_xyz"
    out = redact_secrets(f"push failed with {token} or {pat}")
    assert token not in out
    assert pat not in out
    assert out.count("gh<redacted>") == 2


def test_redacts_aws_key() -> None:
    out = redact_secrets("credentials AKIAABCDEFGHIJKLMNOP were rejected")
    assert "ABCDEFGHIJKLMNOP" not in out
    assert "AKIA<redacted>" in out


def test_redacts_jwt() -> None:
    jwt = "eyJ" + "a" * 24 + "." + "b" * 24 + "." + "c" * 10
    out = redact_secrets(f"token rejected: {jwt}")
    assert jwt not in out
    assert "b" * 24 not in out


def test_redacts_stripe_style_key() -> None:
    key = "pk_live_" + "A1b2C3d4E5f6G7h8"
    out = redact_secrets(f"charge with {key}")
    assert key not in out
    assert "<redacted>" in out


def test_redacts_env_style_names() -> None:
    env_example = find_project_root() / "config" / ".env.example"
    names = re.findall(r"^([A-Z][A-Z0-9_]*)=", env_example.read_text(), flags=re.MULTILINE)
    assert names, ".env.example has no NAME= lines"
    value = "VeryS3cretValue42"
    for name in names:
        for text in (f"{name}={value}", f"{name}: {value}"):
            out = redact_secrets(text)
            assert value not in out, f"{text!r} not redacted: {out!r}"
            assert out.startswith(name)
