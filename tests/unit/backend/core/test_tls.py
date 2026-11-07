"""Tests for outbound TLS trust.

``truststore`` replaces ssl.SSLContext for the whole process, so each check
that applies it runs in its own interpreter and cannot leak into other tests.
"""

import subprocess
import sys

import pytest
from pydantic import ValidationError

from modules.backend.core.config import find_project_root, get_app_config
from modules.backend.core.config_schema import TlsSchema
from modules.backend.core.tls import ignored_ca_bundle_variables


def _run(code: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=find_project_root(),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


class TestApplyOsTrustStore:
    def test_ssl_uses_python_bundle_until_applied(self):
        assert _run("import ssl; print(ssl.SSLContext.__module__)") == "ssl"

    def test_ssl_context_is_truststores_after_applying(self):
        code = (
            "from modules.backend.core.tls import apply_os_trust_store; "
            "import ssl; apply_os_trust_store(); print(ssl.SSLContext.__module__)"
        )

        assert _run(code).startswith("truststore")

    def test_applying_twice_is_harmless(self):
        code = (
            "from modules.backend.core.tls import apply_os_trust_store; import ssl; "
            "apply_os_trust_store(); first = ssl.SSLContext; apply_os_trust_store(); "
            "print(first is ssl.SSLContext)"
        )

        assert _run(code) == "True"

    def test_applied_context_still_verifies_certificates(self):
        code = (
            "from modules.backend.core.tls import apply_os_trust_store; import ssl; "
            "apply_os_trust_store(); "
            "print(ssl.create_default_context().verify_mode == ssl.CERT_REQUIRED)"
        )

        assert _run(code) == "True"


class TestConfigureTlsTrust:
    def test_configured_setting_drives_the_process(self):
        enabled = get_app_config().security.tls.use_os_trust_store
        code = (
            "from modules.backend.core.tls import configure_tls_trust; import ssl; "
            "configure_tls_trust(); print(ssl.SSLContext.__module__)"
        )

        assert _run(code).startswith("truststore") is enabled


class TestTlsSchema:
    def test_setting_is_required(self):
        with pytest.raises(ValidationError):
            TlsSchema()

    def test_unknown_keys_are_refused(self):
        with pytest.raises(ValidationError):
            TlsSchema(use_os_trust_store=True, verify=False)


class TestIgnoredCaBundleVariables:
    def test_set_variables_are_named(self):
        environ = {"SSL_CERT_FILE": "/tmp/ca.pem", "REQUESTS_CA_BUNDLE": "/tmp/other.pem"}

        assert ignored_ca_bundle_variables(environ) == ["SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"]

    def test_empty_values_do_not_count(self):
        assert ignored_ca_bundle_variables({"SSL_CERT_FILE": ""}) == []

    def test_unrelated_variables_are_ignored(self):
        assert ignored_ca_bundle_variables({"PATH": "/usr/bin", "HOME": "/home/x"}) == []
