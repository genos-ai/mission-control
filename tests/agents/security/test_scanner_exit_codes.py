"""Tests for security tool registry and exit code handling.

Validates:
- S-03: Exit code 1 from Opengrep, Ruff, pip-audit treated as success
- Registry loads YAML correctly
- get_applicable() filters by surface conditions
- check_installed() returns False for missing binary
- detect_surface() identifies file types correctly
"""

from pathlib import Path

import pytest

from modules.backend.agents.security.tool_registry import (
    SecurityToolRegistry,
    SecurityToolSpec,
    SurfaceDetectionResult,
    ToolCapability,
    detect_surface,
)


@pytest.fixture
def registry() -> SecurityToolRegistry:
    """Load the real Phase 1 tools.yaml."""
    config_path = Path("config/security/tools.yaml")
    if not config_path.exists():
        pytest.skip("config/security/tools.yaml not found")
    return SecurityToolRegistry(config_path)


class TestRegistryLoading:
    def test_loads_phase1_tools(self, registry: SecurityToolRegistry):
        """Registry loads all Phase 1 capabilities from YAML."""
        assert registry.get_all(ToolCapability.CODE_SCAN)
        assert registry.get_all(ToolCapability.CODE_LINT)
        assert registry.get_all(ToolCapability.DEPS_SCAN)
        assert registry.get_all(ToolCapability.SECRETS_DETECT)
        assert registry.get_all(ToolCapability.CONTAINER_SCAN)
        assert registry.get_all(ToolCapability.DOCKERFILE_LINT)
        assert registry.get_all(ToolCapability.INFRA_SCAN)

    def test_primary_returns_first(self, registry: SecurityToolRegistry):
        spec = registry.get_primary(ToolCapability.CODE_SCAN)
        assert spec.name == "opengrep"

    def test_missing_capability_raises(self, registry: SecurityToolRegistry):
        with pytest.raises(KeyError):
            registry.get_primary(ToolCapability.AUTH_TEST_JWT)

    def test_empty_capability_returns_empty_list(self, registry: SecurityToolRegistry):
        assert registry.get_all(ToolCapability.AUTH_TEST_JWT) == []


class TestExitCodes:
    """S-03: Exit code 1 = findings found, not failure."""

    def test_opengrep_exit_1_is_success(self, registry: SecurityToolRegistry):
        spec = registry.get_primary(ToolCapability.CODE_SCAN)
        assert spec.name == "opengrep"
        assert 1 in spec.success_exit_codes

    def test_ruff_exit_1_is_success(self, registry: SecurityToolRegistry):
        spec = registry.get_primary(ToolCapability.CODE_LINT)
        assert spec.name == "ruff"
        assert 1 in spec.success_exit_codes

    def test_pip_audit_exit_1_is_success(self, registry: SecurityToolRegistry):
        spec = registry.get_primary(ToolCapability.DEPS_SCAN)
        assert spec.name == "pip-audit"
        assert 1 in spec.success_exit_codes

    def test_betterleaks_exit_1_is_success(self, registry: SecurityToolRegistry):
        spec = registry.get_primary(ToolCapability.SECRETS_DETECT)
        assert spec.name == "betterleaks"
        assert 1 in spec.success_exit_codes

    def test_trivy_exit_0_only(self, registry: SecurityToolRegistry):
        spec = registry.get_primary(ToolCapability.CONTAINER_SCAN)
        assert spec.name == "trivy"
        assert spec.success_exit_codes == [0]


class TestSurfaceFiltering:
    def test_python_surface_includes_code_scan(self, registry: SecurityToolRegistry):
        surface = SurfaceDetectionResult(has_python=True)
        applicable = registry.get_applicable(surface)
        names = [s.name for s in applicable]
        assert "opengrep" in names
        assert "ruff" in names

    def test_no_dockerfile_excludes_hadolint(self, registry: SecurityToolRegistry):
        surface = SurfaceDetectionResult(has_python=True, has_dockerfile=False)
        applicable = registry.get_applicable(surface)
        names = [s.name for s in applicable]
        assert "hadolint" not in names

    def test_always_run_tools_included(self, registry: SecurityToolRegistry):
        """Tools with empty applies_when always run."""
        surface = SurfaceDetectionResult()  # nothing detected
        applicable = registry.get_applicable(surface)
        names = [s.name for s in applicable]
        assert "betterleaks" in names
        assert "trivy" in names

    def test_dockerfile_includes_hadolint(self, registry: SecurityToolRegistry):
        surface = SurfaceDetectionResult(has_dockerfile=True)
        applicable = registry.get_applicable(surface)
        names = [s.name for s in applicable]
        assert "hadolint" in names


class TestCheckInstalled:
    def test_missing_binary(self, registry: SecurityToolRegistry):
        spec = SecurityToolSpec(
            name="fake-tool",
            capability=ToolCapability.CODE_SCAN,
            binary="nonexistent-binary-xyz-123",
            version_cmd="nonexistent-binary-xyz-123 --version",
            output_format="sarif",
            sarif_native=True,
            run_template="{binary} {target_path}",
        )
        assert registry.check_installed(spec) is False

    def test_python_is_installed(self, registry: SecurityToolRegistry):
        spec = SecurityToolSpec(
            name="python-check",
            capability=ToolCapability.CODE_SCAN,
            binary="python3",
            version_cmd="python3 --version",
            output_format="json",
            sarif_native=False,
            run_template="{binary} {target_path}",
        )
        assert registry.check_installed(spec) is True


class TestDetectSurface:
    def test_python_project(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("from fastapi import FastAPI")
        (tmp_path / "requirements.txt").write_text("fastapi>=0.100.0")
        result = detect_surface(str(tmp_path))
        assert result.has_python is True
        assert result.has_requirements_txt is True
        assert "fastapi" in result.detected_frameworks

    def test_empty_directory(self, tmp_path: Path):
        result = detect_surface(str(tmp_path))
        assert result.has_python is False
        assert result.has_javascript is False

    def test_dockerfile_detected(self, tmp_path: Path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.12")
        result = detect_surface(str(tmp_path))
        assert result.has_dockerfile is True

    def test_nonexistent_path_raises(self):
        with pytest.raises(FileNotFoundError):
            detect_surface("/nonexistent/path")

    def test_docker_compose_detected(self, tmp_path: Path):
        (tmp_path / "docker-compose.yaml").write_text("version: '3'")
        result = detect_surface(str(tmp_path))
        assert result.has_docker_compose is True

    def test_terraform_detected(self, tmp_path: Path):
        (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "b" {}')
        result = detect_surface(str(tmp_path))
        assert result.has_terraform is True
