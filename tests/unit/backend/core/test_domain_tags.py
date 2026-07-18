"""
Unit tests for domain tag taxonomy.

No database, no mocks — pure function tests against the public interface.
"""

import pytest

from modules.backend.core.domain_tags import (
    CROSS_CUTTING_TAGS,
    infer_tags_from_manifest,
    normalize_tag,
    validate_tags,
)

# ── normalize_tag ────────────────────────────────────────────


class TestNormalizeTag:
    def test_lowercase(self):
        assert normalize_tag("Auth") == "auth"

    def test_strip_whitespace(self):
        assert normalize_tag("  deployment  ") == "deployment"

    def test_collapse_spaces(self):
        assert normalize_tag("Bug Fix") == "bugfix"

    def test_collapse_hyphens(self):
        assert normalize_tag("code--quality") == "codequality"

    def test_empty_string(self):
        assert normalize_tag("") == ""

    def test_already_normalized(self):
        assert normalize_tag("testing") == "testing"

    def test_mixed_case_with_spaces(self):
        assert normalize_tag("  API  ") == "api"


# ── validate_tags ────────────────────────────────────────────


class TestValidateTags:
    def test_all_valid(self):
        valid, invalid = validate_tags(["auth", "api", "testing"])
        assert valid == ["auth", "api", "testing"]
        assert invalid == []

    def test_mixed_valid_invalid(self):
        valid, invalid = validate_tags(["auth", "foobar", "testing"])
        assert valid == ["auth", "testing"]
        assert invalid == ["foobar"]

    def test_normalizes_before_validating(self):
        valid, invalid = validate_tags(["Auth", "API"])
        assert valid == ["auth", "api"]
        assert invalid == []

    def test_dedup(self):
        valid, invalid = validate_tags(["auth", "Auth", "auth"])
        assert valid == ["auth"]
        assert invalid == []

    def test_empty_list(self):
        valid, invalid = validate_tags([])
        assert valid == []
        assert invalid == []

    def test_all_invalid(self):
        valid, invalid = validate_tags(["xxx", "yyy"])
        assert valid == []
        assert invalid == ["xxx", "yyy"]

    def test_with_mcd_components(self):
        mcd = {
            "architecture": {
                "components": {
                    "mission_control": {"purpose": "orchestration"},
                    "planning_agent": {"purpose": "planning"},
                }
            }
        }
        valid, invalid = validate_tags(
            ["missioncontrol", "planningagent", "foobar"],
            mcd,
        )
        assert "missioncontrol" in valid
        assert "planningagent" in valid
        assert "foobar" in invalid

    def test_empty_string_tags_skipped(self):
        valid, invalid = validate_tags(["", "auth", ""])
        assert valid == ["auth"]
        assert invalid == []

    def test_no_mcd(self):
        valid, _ = validate_tags(["auth"])
        assert valid == ["auth"]


# ── CROSS_CUTTING_TAGS ───────────────────────────────────────


class TestCrossCuttingTags:
    def test_is_frozenset(self):
        assert isinstance(CROSS_CUTTING_TAGS, frozenset)

    def test_contains_core_tags(self):
        for tag in ["auth", "api", "database", "testing", "security", "backend", "frontend"]:
            assert tag in CROSS_CUTTING_TAGS, f"Missing: {tag}"

    def test_all_lowercase(self):
        for tag in CROSS_CUTTING_TAGS:
            assert tag == tag.lower(), f"Not lowercase: {tag}"

    def test_minimum_count(self):
        assert len(CROSS_CUTTING_TAGS) >= 20


# ── infer_tags_from_manifest ─────────────────────────────────


class TestInferTags:
    def test_none_manifest(self):
        assert infer_tags_from_manifest(None) == []

    def test_empty_manifest(self):
        class EmptyManifest:
            read_first = []
            modify = []
            read_for_pattern = []

        assert infer_tags_from_manifest(EmptyManifest()) == []

    def test_infers_from_path_segments(self):
        """Inferred tags must still pass validation — use MCD with matching components."""
        mcd = {
            "identity": {"repo_structure": {}},
            "architecture": {
                "components": {
                    "services": {},
                    "models": {},
                }
            },
        }

        class Manifest:
            class Entry:
                def __init__(self, p):
                    self.path = p

            modify = [Entry("modules/backend/services/auth.py")]
            read_first = [Entry("modules/backend/models/user.py")]
            read_for_pattern = []

        tags = infer_tags_from_manifest(Manifest(), mcd)
        assert "services" in tags or "models" in tags

    def test_infers_with_mcd_repo_structure(self):
        mcd = {
            "identity": {
                "repo_structure": {
                    "modules/backend/services/": "business logic",
                }
            },
            "architecture": {"components": {"services": {}}},
        }

        class Manifest:
            class Entry:
                def __init__(self, p):
                    self.path = p

            modify = [Entry("modules/backend/services/auth.py")]
            read_first = []
            read_for_pattern = []

        tags = infer_tags_from_manifest(Manifest(), mcd)
        assert "services" in tags
