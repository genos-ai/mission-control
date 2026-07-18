"""Tests for SARIF parsing, merging, and format conversion.

Validates:
- S-04: Merged SARIF deduplicates by (cwe_id, file_path, line_number)
- S-04: Highest severity wins when tools disagree
- load_sarif returns normalised finding dicts
- convert_to_sarif handles JSON and JSONL inputs
"""

import json
from pathlib import Path

import pytest

from modules.backend.agents.security.sarif import convert_to_sarif, load_sarif, merge_sarif


@pytest.fixture
def sample_sarif_path() -> str:
    path = "tests/fixtures/sarif/sample_merged.sarif.json"
    if not Path(path).exists():
        pytest.skip("Sample SARIF fixture not found")
    return path


class TestLoadSarif:
    def test_loads_findings(self, sample_sarif_path: str):
        findings = load_sarif(sample_sarif_path)
        assert len(findings) == 5  # 3 from opengrep + 2 from ruff

    def test_finding_has_required_fields(self, sample_sarif_path: str):
        findings = load_sarif(sample_sarif_path)
        f = findings[0]
        assert "rule_id" in f
        assert "file_path" in f
        assert "line_number" in f
        assert "severity" in f
        assert "message" in f
        assert "tool_name" in f

    def test_tool_names_extracted(self, sample_sarif_path: str):
        findings = load_sarif(sample_sarif_path)
        tools = {f["tool_name"] for f in findings}
        assert "opengrep" in tools
        assert "ruff" in tools

    def test_cwe_extracted_from_rules(self, sample_sarif_path: str):
        findings = load_sarif(sample_sarif_path)
        sqli = [f for f in findings if f["rule_id"] == "python.sqli.text-interpolation"]
        assert len(sqli) >= 1
        assert sqli[0]["cwe_id"] == "CWE-89"

    def test_severity_mapped(self, sample_sarif_path: str):
        findings = load_sarif(sample_sarif_path)
        severities = {f["severity"] for f in findings}
        assert "HIGH" in severities  # error → HIGH
        assert "MEDIUM" in severities  # warning → MEDIUM


class TestMergeSarif:
    def test_deduplication(self, sample_sarif_path: str, tmp_path: Path):
        """S-04: Duplicate (cwe_id, file_path, line_number) produces one finding."""
        output = str(tmp_path / "merged.sarif")
        merge_sarif([sample_sarif_path], output)

        merged = json.loads(Path(output).read_text())
        results = merged["runs"][0]["results"]

        # The fixture has 5 findings but one duplicate:
        # opengrep CWE-89 at users.py:42 AND ruff CWE-89 at users.py:42
        # After dedup, should be 4 unique findings
        assert len(results) == 4

    def test_highest_severity_wins(self, sample_sarif_path: str, tmp_path: Path):
        """S-04: When tools disagree on severity, highest wins."""
        output = str(tmp_path / "merged.sarif")
        merge_sarif([sample_sarif_path], output)

        merged = json.loads(Path(output).read_text())
        results = merged["runs"][0]["results"]

        # The CWE-89 at users.py:42 was "error" in opengrep, "warning" in ruff
        # Merged result should keep "error" (highest)
        users_sqli = [
            r
            for r in results
            if any(
                loc.get("physicalLocation", {}).get("artifactLocation", {}).get("uri")
                == "app/routes/users.py"
                and loc.get("physicalLocation", {}).get("region", {}).get("startLine") == 42
                for loc in r.get("locations", [])
            )
        ]
        assert len(users_sqli) == 1
        assert users_sqli[0]["level"] == "error"

    def test_empty_input_produces_empty_sarif(self, tmp_path: Path):
        output = str(tmp_path / "merged.sarif")
        merge_sarif([], output)

        merged = json.loads(Path(output).read_text())
        assert merged["version"] == "2.1.0"
        assert len(merged["runs"][0]["results"]) == 0

    def test_missing_file_skipped(self, tmp_path: Path):
        output = str(tmp_path / "merged.sarif")
        merge_sarif(["/nonexistent/file.sarif"], output)

        merged = json.loads(Path(output).read_text())
        assert len(merged["runs"][0]["results"]) == 0

    def test_merge_multiple_files(self, tmp_path: Path):
        # Create two SARIF files with distinct findings
        sarif_a = tmp_path / "a.sarif"
        sarif_b = tmp_path / "b.sarif"

        sarif_a.write_text(
            json.dumps(
                {
                    "version": "2.1.0",
                    "runs": [
                        {
                            "tool": {"driver": {"name": "tool-a"}},
                            "results": [
                                {
                                    "ruleId": "R1",
                                    "level": "error",
                                    "message": {"text": "Finding A"},
                                    "locations": [
                                        {
                                            "physicalLocation": {
                                                "artifactLocation": {"uri": "a.py"},
                                                "region": {"startLine": 1},
                                            }
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            )
        )
        sarif_b.write_text(
            json.dumps(
                {
                    "version": "2.1.0",
                    "runs": [
                        {
                            "tool": {"driver": {"name": "tool-b"}},
                            "results": [
                                {
                                    "ruleId": "R2",
                                    "level": "warning",
                                    "message": {"text": "Finding B"},
                                    "locations": [
                                        {
                                            "physicalLocation": {
                                                "artifactLocation": {"uri": "b.py"},
                                                "region": {"startLine": 2},
                                            }
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            )
        )

        output = str(tmp_path / "merged.sarif")
        merge_sarif([str(sarif_a), str(sarif_b)], output)

        merged = json.loads(Path(output).read_text())
        assert len(merged["runs"][0]["results"]) == 2


class TestConvertToSarif:
    def test_json_conversion(self, tmp_path: Path):
        """Convert ruff-style JSON output to SARIF."""
        source = tmp_path / "ruff_output.json"
        source.write_text(
            json.dumps(
                [
                    {
                        "code": "S608",
                        "message": "SQL injection",
                        "filename": "app.py",
                        "line": 10,
                        "severity": "high",
                    },
                    {
                        "code": "S105",
                        "message": "Hardcoded password",
                        "filename": "config.py",
                        "line": 5,
                        "severity": "medium",
                    },
                ]
            )
        )

        convert_to_sarif(str(source), "json", "ruff")

        sarif = json.loads(source.read_text())
        assert sarif["version"] == "2.1.0"
        assert sarif["runs"][0]["tool"]["driver"]["name"] == "ruff"
        assert len(sarif["runs"][0]["results"]) == 2

    def test_jsonl_conversion(self, tmp_path: Path):
        """Convert nuclei-style JSONL output to SARIF."""
        source = tmp_path / "nuclei_output.jsonl"
        source.write_text(
            '{"template-id": "CVE-2021-44228", "severity": "critical", "name": "Log4Shell"}\n'
            '{"template-id": "misconfig-01", "severity": "medium", "name": "Missing headers"}\n'
        )

        convert_to_sarif(str(source), "jsonl", "nuclei")

        sarif = json.loads(source.read_text())
        assert len(sarif["runs"][0]["results"]) == 2
        assert sarif["runs"][0]["results"][0]["level"] == "error"  # critical → error

    def test_missing_file_no_error(self, tmp_path: Path):
        """Missing source file should not raise."""
        convert_to_sarif(str(tmp_path / "missing.json"), "json", "tool")
        # No exception — just logs a warning
