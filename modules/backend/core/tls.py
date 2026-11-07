"""Outbound TLS trust.

Python verifies server certificates against its own bundled CA list. On a
network with a TLS-inspecting proxy the proxy's CA is installed in the
operating system's trust store only, so every call to an LLM provider fails
verification. ``truststore`` makes ``ssl`` verify against the OS store instead.

Call ``configure_tls_trust()`` once at process start, before the first HTTPS
client is created: an SSL context built earlier keeps the old trust.

Scope: this covers HTTPS made through Python's ``ssl`` module in this process.
It does not reach libraries that do their own TLS (Temporal's gRPC client) or
child processes with their own runtime (the Copilot and Claude Code CLIs).
"""

import os
from collections.abc import Mapping

import truststore

from modules.backend.core.config import get_app_config
from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Standard variables that point Python and curl at a custom CA bundle. The OS
# trust store replaces the bundle, so setting one has no effect while it is on.
_CA_BUNDLE_VARIABLES = ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


def ignored_ca_bundle_variables(environ: Mapping[str, str]) -> list[str]:
    """Names of the CA-bundle variables set in ``environ``."""
    return [name for name in _CA_BUNDLE_VARIABLES if environ.get(name)]


def apply_os_trust_store() -> None:
    """Make ``ssl`` verify certificates against the OS trust store. Idempotent."""
    truststore.inject_into_ssl()


def configure_tls_trust() -> None:
    """Apply the OS trust store when security.yaml asks for it (security.tls)."""
    if not get_app_config().security.tls.use_os_trust_store:
        logger.info("TLS trust: using Python's bundled certificates (security.tls)")
        return

    apply_os_trust_store()
    logger.info("TLS trust: verifying server certificates against the OS trust store")

    ignored = ignored_ca_bundle_variables(os.environ)
    if ignored:
        logger.warning(
            "TLS trust: these CA bundle variables are ignored while security.tls."
            "use_os_trust_store is true; add the CA to the OS trust store instead",
            extra={"variables": ignored},
        )
