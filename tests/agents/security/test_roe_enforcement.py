"""Tests for ROE path-based scope enforcement.

Validates:
- validate_target_path blocks out-of-scope paths
- validate_target_path allows in-scope paths
- Denylist takes precedence over allowlist
- verify_roe_hash detects ROE changes (ROE-02)
"""

import pytest

from modules.backend.agents.security.errors import SecurityAssessmentError
from modules.backend.agents.security.roe import (
    RoeScopeViolationError,
    RulesOfEngagement,
    validate_target_path,
    verify_roe_hash,
)


def _roe(**overrides: object) -> RulesOfEngagement:
    base = {
        "engagement_id": "ENG-001",
        "roe_sha256": "placeholder",
        "scope_allowlist": ["/workspace/target/*"],
    }
    base.update(overrides)
    return RulesOfEngagement(**base)


class TestValidateTargetPath:
    def test_in_scope_allowed(self):
        roe = _roe(scope_allowlist=["/workspace/target/*"])
        result = validate_target_path("/workspace/target/app/main.py", roe)
        assert result == "/workspace/target/app/main.py"

    def test_out_of_scope_rejected(self):
        roe = _roe(scope_allowlist=["/workspace/target/*"])
        with pytest.raises(RoeScopeViolationError, match="not in ROE scope"):
            validate_target_path("/etc/passwd", roe)

    def test_denylist_overrides_allowlist(self):
        roe = _roe(
            scope_allowlist=["/workspace/*"],
            scope_denylist=["/workspace/target/secrets/*"],
        )
        with pytest.raises(RoeScopeViolationError, match="denylist"):
            validate_target_path("/workspace/target/secrets/keys.yaml", roe)

    def test_denylist_does_not_affect_other_paths(self):
        roe = _roe(
            scope_allowlist=["/workspace/*"],
            scope_denylist=["/workspace/target/secrets/*"],
        )
        result = validate_target_path("/workspace/target/app/main.py", roe)
        assert result == "/workspace/target/app/main.py"

    def test_multiple_allowlist_patterns(self):
        roe = _roe(scope_allowlist=["/workspace/target/*", "/workspace/config/*"])
        assert validate_target_path("/workspace/config/app.yaml", roe)

    def test_empty_allowlist_rejects_all(self):
        """scope_allowlist requires min_length=1 so this tests the validator."""
        with pytest.raises(Exception):
            _roe(scope_allowlist=[])

    def test_glob_pattern_matching(self):
        roe = _roe(scope_allowlist=["*/target/*"])
        result = validate_target_path("/workspace/target/app.py", roe)
        assert result == "/workspace/target/app.py"


class TestVerifyRoeHash:
    def test_matching_hash_passes(self):
        import hashlib

        roe = _roe()
        roe_json = roe.model_dump_json(exclude={"roe_sha256"})
        expected = hashlib.sha256(roe_json.encode()).hexdigest()
        # Should not raise
        verify_roe_hash(roe, expected)

    def test_mismatched_hash_raises(self):
        roe = _roe()
        with pytest.raises(SecurityAssessmentError, match="ROE hash changed"):
            verify_roe_hash(roe, "0000000000000000000000000000000000000000000000000000000000000000")

    def test_modified_roe_detected(self):
        import hashlib

        roe = _roe()
        roe_json = roe.model_dump_json(exclude={"roe_sha256"})
        original_hash = hashlib.sha256(roe_json.encode()).hexdigest()

        # Modify the ROE
        modified_roe = _roe(max_cost_usd=999.0)
        with pytest.raises(SecurityAssessmentError, match="ROE hash changed"):
            verify_roe_hash(modified_roe, original_hash)
