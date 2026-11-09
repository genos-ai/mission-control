"""The admin health checks for Temporal, its worker and the Foundry login.

Real config objects and a real network failure; the Azure credential is a stand-in, since
no test can depend on a developer's `az login`.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError

from modules.backend.core.config import get_app_config
from modules.backend.services import health
from modules.backend.services.health import (
    HealthCheckService,
    check_foundry,
    check_temporal,
    check_temporal_worker,
)

CREDENTIAL = "modules.backend.core.model_providers.get_foundry_credential"


class _Credential:
    """What DefaultAzureCredential offers the health check: an awaitable get_token."""

    def __init__(self, token=None, error=None, delay=0.0):
        self._token, self._error, self._delay = token, error, delay

    async def get_token(self, *scopes):
        await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._token


@pytest.fixture
def fast_probe(monkeypatch):
    monkeypatch.setattr(get_app_config().application.timeouts, "health_probe", 1)


# ---- Temporal ----


async def test_temporal_disabled_is_not_configured(monkeypatch):
    monkeypatch.setattr(get_app_config().temporal, "enabled", False)

    for check in (check_temporal, check_temporal_worker):
        result = await check()
        assert result["status"] == "not_configured"
        assert "temporal.enabled" in result["detail"]


async def test_unreachable_temporal_is_unhealthy_and_answers_within_the_probe_timeout(
    monkeypatch, fast_probe
):
    from modules.backend.temporal import client as temporal_client

    monkeypatch.setattr(get_app_config().temporal, "enabled", True)
    monkeypatch.setattr(get_app_config().temporal, "server_url", "127.0.0.1:1")  # nothing listens
    monkeypatch.setattr(temporal_client, "_client", None)

    for check in (check_temporal, check_temporal_worker):
        started = time.monotonic()
        result = await check()

        assert result["status"] == "unhealthy"
        assert result["error"]
        assert time.monotonic() - started < 5
    monkeypatch.setattr(temporal_client, "_client", None)


# ---- Foundry ----


async def test_foundry_reports_when_the_token_expires_and_never_the_token(fast_probe):
    token = AccessToken("secret-token-value", int(time.time()) + 3600)

    with patch(CREDENTIAL, return_value=_Credential(token)):
        result = await check_foundry()

    assert result["status"] == "healthy"
    assert result["detail"].startswith("Entra token valid for 5")
    assert "secret-token-value" not in repr(result)


async def test_a_lapsed_login_is_unhealthy_with_the_reason(fast_probe):
    failing = _Credential(error=ClientAuthenticationError("run az login"))

    with patch(CREDENTIAL, return_value=failing):
        result = await check_foundry()

    assert result["status"] == "unhealthy"
    assert "ClientAuthenticationError" in result["error"]
    assert "az login" in result["error"]


async def test_a_login_that_never_answers_times_out(fast_probe):
    with patch(CREDENTIAL, return_value=_Credential(delay=30)):
        started = time.monotonic()
        result = await check_foundry()

    assert result["status"] == "unhealthy"
    assert result["error"] == "no answer within 1 s"
    assert time.monotonic() - started < 5


async def test_a_static_credential_provider_is_checked_without_a_network_call(monkeypatch):
    monkeypatch.setattr(get_app_config().providers.foundry, "auth_mode", "api_key")

    with patch("modules.backend.core.model_providers.credential_status", return_value="missing"):
        result = await check_foundry()

    assert result["status"] == "unhealthy"
    assert "api_key credential is missing" in result["error"]


# ---- The report ----

HEALTHY = {"status": "healthy"}


def _patched(**overrides):
    results = {
        "check_temporal": HEALTHY,
        "check_temporal_worker": HEALTHY,
        "check_foundry": HEALTHY,
        **overrides,
    }
    return [
        patch.object(health, name, new=AsyncMock(return_value=value))
        for name, value in results.items()
    ] + [
        patch("modules.backend.api.health.check_database", new=AsyncMock(return_value=HEALTHY)),
        patch("modules.backend.api.health.check_redis", new=AsyncMock(return_value=HEALTHY)),
    ]


async def _report(**overrides):
    patches = _patched(**overrides)
    for p in patches:
        p.start()
    try:
        return await HealthCheckService().check_readiness()
    finally:
        for p in patches:
            p.stop()


async def test_the_report_lists_every_hard_dependency():
    report = await _report()

    assert [c.name for c in report.components] == [
        "database",
        "redis",
        "temporal",
        "temporal_worker",
        "foundry",
    ]
    assert report.overall_status == "healthy"


async def test_a_stopped_worker_makes_the_whole_report_degraded():
    report = await _report(check_temporal_worker={"status": "unhealthy", "error": "no worker"})

    assert report.overall_status == "degraded"
    worker = next(c for c in report.components if c.name == "temporal_worker")
    assert worker.error == "no worker"


async def test_a_disabled_service_does_not_degrade_the_report():
    report = await _report(check_temporal={"status": "not_configured", "detail": "off"})

    assert report.overall_status == "healthy"


async def test_a_check_that_raises_is_reported_unhealthy_not_lost():
    patches = _patched()
    patches[0] = patch.object(
        health, "check_temporal", new=AsyncMock(side_effect=RuntimeError("boom"))
    )
    for p in patches:
        p.start()
    try:
        report = await HealthCheckService().check_readiness()
    finally:
        for p in patches:
            p.stop()

    temporal = next(c for c in report.components if c.name == "temporal")
    assert temporal.status == "unhealthy" and "boom" in temporal.error
    assert report.overall_status == "degraded"
