"""Tests for SSRF prevention in validate_url.

Validates that validate_url blocks all private/reserved address ranges
and allows legitimate public URLs.
"""

import pytest

from modules.backend.agents.security.roe import validate_url


class TestValidateUrl:
    def test_public_url_allowed(self):
        # google.com should resolve to a public IP
        result = validate_url("https://www.google.com")
        assert result == "https://www.google.com"

    def test_http_scheme_allowed(self):
        result = validate_url("http://www.google.com")
        assert result == "http://www.google.com"

    def test_blocked_localhost_127(self):
        with pytest.raises(ValueError, match="private address"):
            validate_url("http://127.0.0.1")

    def test_blocked_localhost_name(self):
        with pytest.raises(ValueError, match="private address"):
            validate_url("http://localhost")

    def test_blocked_10_network(self):
        with pytest.raises(ValueError, match="private address"):
            validate_url("http://10.0.0.1")

    def test_blocked_172_16_network(self):
        with pytest.raises(ValueError, match="private address"):
            validate_url("http://172.16.0.1")

    def test_blocked_192_168_network(self):
        with pytest.raises(ValueError, match="private address"):
            validate_url("http://192.168.1.1")

    def test_blocked_metadata_169_254(self):
        """Cloud metadata endpoint must be blocked."""
        with pytest.raises(ValueError, match="private address"):
            validate_url("http://169.254.169.254/latest/meta-data/")

    def test_blocked_ftp_scheme(self):
        with pytest.raises(ValueError, match="Blocked scheme"):
            validate_url("ftp://example.com/file")

    def test_blocked_file_scheme(self):
        with pytest.raises(ValueError, match="Blocked scheme"):
            validate_url("file:///etc/passwd")

    def test_unresolvable_hostname(self):
        with pytest.raises(ValueError, match="Cannot resolve"):
            validate_url("http://this-host-does-not-exist-xyz-123.invalid")

    def test_no_hostname(self):
        with pytest.raises(ValueError, match="No hostname"):
            validate_url("http://")
