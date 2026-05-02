"""Tests for secret detection redaction (S-02).

Validates that raw secret values never appear in SARIF output or
tool return values when redact_output is True.
"""

import json
from pathlib import Path

import pytest

from modules.backend.agents.security.tool_runner import strip_secret_values


class TestStripSecretValues:
    """S-02: Secret values stripped from SARIF output."""

    def test_api_key_redacted(self, tmp_path: Path):
        sarif = {
            "runs": [{
                "tool": {"driver": {"name": "betterleaks"}},
                "results": [{
                    "ruleId": "generic-api-key",
                    "message": {"text": "Found API key: sk-live-abc123def456ghi789jkl012mno345pqr678"},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": "config.py"},
                            "region": {
                                "startLine": 5,
                                "snippet": {"text": 'API_KEY = "sk-live-abc123def456ghi789jkl012mno345pqr678"'},
                            },
                        },
                    }],
                }],
            }],
        }
        sarif_path = tmp_path / "secrets.sarif"
        sarif_path.write_text(json.dumps(sarif))

        strip_secret_values(str(sarif_path))

        result = json.loads(sarif_path.read_text())
        msg = result["runs"][0]["results"][0]["message"]["text"]
        snippet = result["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]["snippet"]["text"]

        assert "sk-live-abc123" not in msg
        assert "sk-live-abc123" not in snippet
        assert "<<REDACTED>>" in msg or "<<REDACTED>>" in snippet

    def test_github_pat_redacted(self, tmp_path: Path):
        sarif = {
            "runs": [{
                "tool": {"driver": {"name": "betterleaks"}},
                "results": [{
                    "ruleId": "github-pat",
                    "message": {"text": "GitHub PAT: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"},
                    "locations": [],
                }],
            }],
        }
        sarif_path = tmp_path / "github.sarif"
        sarif_path.write_text(json.dumps(sarif))

        strip_secret_values(str(sarif_path))

        result = json.loads(sarif_path.read_text())
        msg = result["runs"][0]["results"][0]["message"]["text"]
        assert "ghp_ABCDEF" not in msg

    def test_jwt_token_redacted(self, tmp_path: Path):
        sarif = {
            "runs": [{
                "tool": {"driver": {"name": "betterleaks"}},
                "results": [{
                    "ruleId": "jwt-token",
                    "message": {"text": "JWT found: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjg"},
                    "locations": [],
                }],
            }],
        }
        sarif_path = tmp_path / "jwt.sarif"
        sarif_path.write_text(json.dumps(sarif))

        strip_secret_values(str(sarif_path))

        result = json.loads(sarif_path.read_text())
        msg = result["runs"][0]["results"][0]["message"]["text"]
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in msg

    def test_non_secret_text_unchanged(self, tmp_path: Path):
        sarif = {
            "runs": [{
                "tool": {"driver": {"name": "opengrep"}},
                "results": [{
                    "ruleId": "python.sqli",
                    "message": {"text": "SQL injection via f-string interpolation"},
                    "locations": [],
                }],
            }],
        }
        sarif_path = tmp_path / "clean.sarif"
        sarif_path.write_text(json.dumps(sarif))

        strip_secret_values(str(sarif_path))

        result = json.loads(sarif_path.read_text())
        msg = result["runs"][0]["results"][0]["message"]["text"]
        assert msg == "SQL injection via f-string interpolation"

    def test_missing_file_no_error(self, tmp_path: Path):
        """Missing SARIF file should not raise."""
        strip_secret_values(str(tmp_path / "nonexistent.sarif"))

    def test_invalid_json_no_error(self, tmp_path: Path):
        """Invalid JSON should not raise."""
        bad = tmp_path / "bad.sarif"
        bad.write_text("not json")
        strip_secret_values(str(bad))
