"""End-to-end SAST pipeline test using fixture SARIF data.

Validates invariant S-01: Scanner phase completes even if individual
scanners fail; partial results are valid output.

Uses pre-generated fixture SARIF (not live tool binaries) — CI-safe.
Live tool integration tests require the security-assessment-worker
Docker image (Phase 2).
"""

import json
from pathlib import Path

import pytest

from modules.backend.agents.security.evidence import EvidenceManifest
from modules.backend.agents.security.sarif import load_sarif, merge_sarif
from modules.backend.agents.security.tool_registry import detect_surface


class TestSastPipeline:
    """End-to-end scan → merge → triage-ready pipeline with fixture data."""

    def test_surface_detection_on_vulnerable_app(
        self,
        vulnerable_fastapi_app: Path,
    ):
        """detect_surface identifies Python, Dockerfile, requirements.txt."""
        result = detect_surface(str(vulnerable_fastapi_app))
        assert result.has_python is True
        assert result.has_dockerfile is True
        assert result.has_requirements_txt is True

    def test_surface_detection_on_clean_app(
        self,
        clean_fastapi_app: Path,
    ):
        result = detect_surface(str(clean_fastapi_app))
        assert result.has_python is True
        assert result.has_dockerfile is True

    def test_sarif_load_and_merge(self, sample_sarif: dict, tmp_path: Path):
        """Full pipeline: load SARIF → merge → evidence manifest."""
        # Write fixture to temp
        sarif_path = tmp_path / "input.sarif"
        sarif_path.write_text(json.dumps(sample_sarif))

        # Load
        findings = load_sarif(str(sarif_path))
        assert len(findings) >= 4  # 5 raw, 4 after dedup

        # Merge (single file — dedup within)
        merged_path = str(tmp_path / "merged.sarif")
        merge_sarif([str(sarif_path)], merged_path)
        assert Path(merged_path).exists()

        merged_findings = load_sarif(merged_path)
        assert len(merged_findings) == 4  # deduped

        # Evidence manifest
        manifest = EvidenceManifest()
        manifest.add(merged_path)
        assert manifest.verify(merged_path) is True

    def test_pipeline_with_empty_sarif(self, tmp_path: Path):
        """S-01: Pipeline handles empty scanner output gracefully."""
        empty_sarif = tmp_path / "empty.sarif"
        empty_sarif.write_text(
            json.dumps(
                {
                    "version": "2.1.0",
                    "runs": [{"tool": {"driver": {"name": "opengrep"}}, "results": []}],
                }
            )
        )

        merged_path = str(tmp_path / "merged.sarif")
        merge_sarif([str(empty_sarif)], merged_path)

        findings = load_sarif(merged_path)
        assert len(findings) == 0

    def test_pipeline_with_missing_sarif_files(self, tmp_path: Path):
        """S-01: Pipeline continues when some scanner outputs are missing."""
        valid_sarif = tmp_path / "valid.sarif"
        valid_sarif.write_text(
            json.dumps(
                {
                    "version": "2.1.0",
                    "runs": [
                        {
                            "tool": {"driver": {"name": "ruff"}},
                            "results": [
                                {
                                    "ruleId": "S105",
                                    "level": "warning",
                                    "message": {"text": "Hardcoded password"},
                                    "locations": [
                                        {
                                            "physicalLocation": {
                                                "artifactLocation": {"uri": "config.py"},
                                                "region": {"startLine": 3},
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

        merged_path = str(tmp_path / "merged.sarif")
        # Mix of valid + missing files
        merge_sarif(
            [str(valid_sarif), "/nonexistent/opengrep.sarif", "/nonexistent/trivy.sarif"],
            merged_path,
        )

        findings = load_sarif(merged_path)
        assert len(findings) == 1  # only from valid file

    def test_findings_have_tool_attribution(self, sample_sarif: dict, tmp_path: Path):
        """Each finding carries the source tool name."""
        sarif_path = tmp_path / "input.sarif"
        sarif_path.write_text(json.dumps(sample_sarif))

        findings = load_sarif(str(sarif_path))
        tools = {f["tool_name"] for f in findings}
        assert len(tools) >= 1
        assert all(t != "unknown" for t in tools)
