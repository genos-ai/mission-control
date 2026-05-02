"""Shared fixtures for WASA security assessment tests."""

import json
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def vulnerable_fastapi_app() -> Path:
    """Deliberately vulnerable FastAPI app.

    Contains: SQL injection (text(f"...")), hardcoded API key, IDOR,
    weak JWT secret, missing Dockerfile USER directive.
    Expected: >= 5 TRUE_POSITIVE across SAST and AppSec phases.
    """
    return Path("tests/fixtures/vulnerable_fastapi_app/")


@pytest.fixture
def clean_fastapi_app() -> Path:
    """Deliberately clean FastAPI app.

    Uses: ORM, no hardcoded secrets, all endpoints auth-guarded,
    ownership checks. Expected: 0 TRUE_POSITIVE after triage.
    """
    return Path("tests/fixtures/clean_fastapi_app/")


@pytest.fixture
def sample_roe() -> dict:
    """Known-good ROE for testing."""
    return yaml.safe_load(
        Path("tests/fixtures/roe/sample_roe.yaml").read_text(),
    )


@pytest.fixture
def sample_sarif() -> dict:
    """5 findings from 2 tools, with 1 duplicate for dedup testing."""
    return json.loads(
        Path("tests/fixtures/sarif/sample_merged.sarif.json").read_text(),
    )


@pytest.fixture
def secret_detection_raw() -> dict:
    """Raw secret detection output with matched secret values."""
    return json.loads(
        Path("tests/fixtures/secret_detection/raw_output.json").read_text(),
    )
