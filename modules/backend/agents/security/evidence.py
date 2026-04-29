"""WASA evidence integrity — SHA-256 manifest for chain of custody.

Every file written to the evidence store gets a SHA-256 entry in the
manifest. The manifest is append-only during an assessment (EV-02).
Spec Section 2.7, invariants EV-01, EV-02.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)


def sha256_file(path: str | Path) -> str:
    """Compute SHA-256 hex digest of a file, reading in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class EvidenceManifest:
    """Append-only SHA-256 integrity manifest for assessment evidence.

    Usage:
        manifest = EvidenceManifest()
        manifest.add("/workspace/evidence/sarif/merged.sarif")
        manifest.save("/workspace/evidence/integrity/manifest.json")

    Invariants:
        EV-01: Every file written to evidence has an entry.
        EV-02: Manifest is append-only — no removals or modifications.
    """

    def __init__(self) -> None:
        self._entries: dict[str, str] = {}

    @property
    def entries(self) -> dict[str, str]:
        """Read-only view of path → SHA-256 entries."""
        return dict(self._entries)

    def add(self, path: str | Path) -> str:
        """Hash a file and append to the manifest. Returns the hex digest.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the path already has an entry (append-only — EV-02).
        """
        path_str = str(path)
        if path_str in self._entries:
            raise ValueError(
                f"Manifest is append-only: '{path_str}' already has entry "
                f"(existing hash: {self._entries[path_str][:16]}...)"
            )
        digest = sha256_file(path)
        self._entries[path_str] = digest
        logger.debug(
            "Evidence manifest entry added",
            extra={"path": path_str, "sha256": digest[:16]},
        )
        return digest

    def verify(self, path: str | Path) -> bool:
        """Check that a file's current hash matches the manifest entry.

        Returns False if the file is not in the manifest or the hash
        does not match. Does NOT raise — callers decide the response.
        """
        path_str = str(path)
        expected = self._entries.get(path_str)
        if expected is None:
            return False
        try:
            actual = sha256_file(path)
        except FileNotFoundError:
            return False
        return actual == expected

    def save(self, manifest_path: str | Path) -> None:
        """Write the manifest to a JSON file."""
        Path(manifest_path).parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w") as f:
            json.dump(self._entries, f, indent=2, sort_keys=True)
        logger.info(
            "Evidence manifest saved",
            extra={"path": str(manifest_path), "entry_count": len(self._entries)},
        )

    @classmethod
    def load(cls, manifest_path: str | Path) -> EvidenceManifest:
        """Load a manifest from a JSON file."""
        with open(manifest_path) as f:
            entries = json.load(f)
        manifest = cls()
        manifest._entries = dict(entries)
        return manifest
