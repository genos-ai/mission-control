"""failures.yaml is required and complete (Plan 88, 88.2.3b; contracts 3.4.9)."""

import pytest
from pydantic import ValidationError

from modules.backend.core import config as config_module
from modules.backend.core.config import AppConfig, get_app_config, load_yaml_config
from modules.backend.core.config_schema import FailuresSchema


def test_loads_from_yaml() -> None:
    failures = get_app_config().failures
    assert failures.evidence.max_summary_chars == 300
    assert failures.supervisor.max_failure_digests == 10
    assert failures.unknown_retryable is True


def test_file_required(monkeypatch) -> None:
    def _load(filename: str) -> dict:
        if filename == "failures.yaml":
            raise FileNotFoundError(filename)
        return load_yaml_config(filename)

    monkeypatch.setattr(config_module, "load_yaml_config", _load)
    with pytest.raises(FileNotFoundError, match=r"failures\.yaml"):
        AppConfig()


@pytest.mark.parametrize(
    "path",
    [
        ("unknown_retryable",),
        ("evidence", "max_message_chars"),
        ("evidence", "max_summary_chars"),
        ("evidence", "max_traceback_frames"),
        ("supervisor", "max_failure_digests"),
    ],
)
def test_missing_key_rejected(path) -> None:
    data = load_yaml_config("failures.yaml")
    parent = data
    for key in path[:-1]:
        parent = parent[key]
    del parent[path[-1]]
    with pytest.raises(ValidationError):
        FailuresSchema(**data)


def test_bounds_at_least_one() -> None:
    data = load_yaml_config("failures.yaml")
    data["evidence"]["max_traceback_frames"] = 0
    with pytest.raises(ValidationError):
        FailuresSchema(**data)
