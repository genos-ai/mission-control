"""Tests for WASA evidence integrity manifest.

Validates invariants EV-01 and EV-02:
- EV-01: Every file added has a SHA-256 entry in the manifest.
- EV-02: The manifest is append-only — no entries removed or modified.
"""

import json
from pathlib import Path

import pytest

from modules.backend.agents.security.evidence import EvidenceManifest, sha256_file


@pytest.fixture
def tmp_evidence(tmp_path: Path) -> Path:
    """Create a temp directory with sample evidence files."""
    (tmp_path / "finding.sarif").write_text('{"runs": []}')
    (tmp_path / "secret.json").write_text('{"matched": "sk-live-abc123"}')
    return tmp_path


class TestSha256File:
    def test_hash_consistency(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = sha256_file(f)
        h2 = sha256_file(f)
        assert h1 == h2
        assert len(h1) == 64  # full hex digest

    def test_different_content_different_hash(self, tmp_path: Path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert sha256_file(f1) != sha256_file(f2)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            sha256_file("/nonexistent/file.txt")


class TestEvidenceManifest:
    def test_add_creates_entry(self, tmp_evidence: Path):
        """EV-01: Every added file has a SHA-256 entry."""
        manifest = EvidenceManifest()
        digest = manifest.add(tmp_evidence / "finding.sarif")
        assert len(digest) == 64
        assert str(tmp_evidence / "finding.sarif") in manifest.entries

    def test_all_files_have_entries(self, tmp_evidence: Path):
        """EV-01: All added files present in manifest."""
        manifest = EvidenceManifest()
        manifest.add(tmp_evidence / "finding.sarif")
        manifest.add(tmp_evidence / "secret.json")
        assert len(manifest.entries) == 2

    def test_append_only_rejects_duplicate(self, tmp_evidence: Path):
        """EV-02: Cannot re-add the same path."""
        manifest = EvidenceManifest()
        manifest.add(tmp_evidence / "finding.sarif")
        with pytest.raises(ValueError, match="append-only"):
            manifest.add(tmp_evidence / "finding.sarif")

    def test_verify_detects_tamper(self, tmp_evidence: Path):
        """Verify returns False if file content changes after add."""
        f = tmp_evidence / "finding.sarif"
        manifest = EvidenceManifest()
        manifest.add(f)
        assert manifest.verify(f) is True
        # Tamper with the file
        f.write_text('{"runs": [{"results": []}]}')
        assert manifest.verify(f) is False

    def test_verify_missing_file(self, tmp_evidence: Path):
        manifest = EvidenceManifest()
        manifest.add(tmp_evidence / "finding.sarif")
        assert manifest.verify(tmp_evidence / "nonexistent.json") is False

    def test_verify_not_in_manifest(self, tmp_evidence: Path):
        manifest = EvidenceManifest()
        assert manifest.verify(tmp_evidence / "finding.sarif") is False

    def test_save_and_load(self, tmp_evidence: Path):
        manifest = EvidenceManifest()
        manifest.add(tmp_evidence / "finding.sarif")
        manifest.add(tmp_evidence / "secret.json")

        manifest_path = tmp_evidence / "manifest.json"
        manifest.save(manifest_path)

        loaded = EvidenceManifest.load(manifest_path)
        assert loaded.entries == manifest.entries

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("test")
        manifest = EvidenceManifest()
        manifest.add(f)
        deep_path = tmp_path / "sub" / "dir" / "manifest.json"
        manifest.save(deep_path)
        assert deep_path.exists()

    def test_saved_manifest_is_valid_json(self, tmp_evidence: Path):
        manifest = EvidenceManifest()
        manifest.add(tmp_evidence / "finding.sarif")
        manifest_path = tmp_evidence / "manifest.json"
        manifest.save(manifest_path)
        data = json.loads(manifest_path.read_text())
        assert isinstance(data, dict)
        assert len(data) == 1
