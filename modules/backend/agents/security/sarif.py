"""WASA SARIF utilities — parsing, merging, and format conversion.

All scanner tools produce or are converted to SARIF 2.1.0. This module
provides the shared parsing and merge logic consumed by the scanner
agent (merge_sarif), triage agent (load_sarif), and tool runner
(convert_to_sarif). Spec Sections 1.2, 2.5.2.

Invariant S-04: Merged SARIF produces exactly one finding per unique
(cwe_id, file_path, line_number) triple, taking the highest severity
when tools disagree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.backend.core.logging import get_logger

logger = get_logger(__name__)

# Severity ordering for conflict resolution (highest wins)
_SEVERITY_RANK = {
    "error": 4,
    "warning": 3,
    "note": 2,
    "none": 1,
}

# SARIF level → WASA severity mapping
SARIF_LEVEL_TO_SEVERITY = {
    "error": "HIGH",
    "warning": "MEDIUM",
    "note": "LOW",
    "none": "INFORMATIONAL",
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_sarif(path: str) -> list[dict[str, Any]]:
    """Read a SARIF file and return a flat list of normalised findings.

    Each finding dict contains:
        rule_id, cwe_id, file_path, line_number, severity, message,
        tool_name, sarif_level
    """
    data = json.loads(Path(path).read_text())
    findings: list[dict[str, Any]] = []

    for run in data.get("runs", []):
        tool_name = (
            run.get("tool", {}).get("driver", {}).get("name", "unknown")
        )
        # Build rule_id → CWE mapping from tool rules
        rule_cwe: dict[str, str | None] = {}
        for rule in run.get("tool", {}).get("driver", {}).get("rules", []):
            rid = rule.get("id", "")
            cwe = _extract_cwe_from_rule(rule)
            rule_cwe[rid] = cwe

        for result in run.get("results", []):
            rule_id = result.get("ruleId", "unknown")
            level = result.get("level", "warning").lower()
            message = result.get("message", {}).get("text", "")

            # Extract location
            file_path = None
            line_number = None
            for loc in result.get("locations", []):
                phys = loc.get("physicalLocation", {})
                artifact = phys.get("artifactLocation", {})
                file_path = artifact.get("uri")
                region = phys.get("region", {})
                line_number = region.get("startLine")
                break  # use first location

            findings.append({
                "rule_id": rule_id,
                "cwe_id": rule_cwe.get(rule_id),
                "file_path": file_path,
                "line_number": line_number,
                "severity": SARIF_LEVEL_TO_SEVERITY.get(level, "MEDIUM"),
                "sarif_level": level,
                "message": message,
                "tool_name": tool_name,
            })

    return findings


def _extract_cwe_from_rule(rule: dict) -> str | None:
    """Extract CWE ID from a SARIF rule's properties or tags."""
    # Check properties.tags
    props = rule.get("properties", {})
    for tag in props.get("tags", []):
        if isinstance(tag, str) and tag.upper().startswith("CWE-"):
            return tag.upper()
    # Check relationships
    for rel in rule.get("relationships", []):
        target = rel.get("target", {})
        tid = target.get("id", "")
        if tid.upper().startswith("CWE-"):
            return tid.upper()
    return None


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def merge_sarif(paths: list[str], output_path: str) -> str:
    """Merge multiple SARIF files into one, deduplicating by composite key.

    Dedup key: (cwe_id, file_path, line_number). When tools disagree on
    severity, the highest wins (S-04).

    Returns the output_path.
    """
    merged_runs: list[dict] = []
    all_findings: list[dict[str, Any]] = []

    for path in paths:
        if not Path(path).exists():
            logger.warning("SARIF file not found, skipping", extra={"path": path})
            continue
        try:
            data = json.loads(Path(path).read_text())
            merged_runs.extend(data.get("runs", []))
            all_findings.extend(load_sarif(path))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(
                "Failed to parse SARIF file",
                extra={"path": path, "error": str(e)},
            )

    # Deduplicate by (cwe_id, file_path, line_number)
    deduped: dict[tuple, dict] = {}
    for finding in all_findings:
        key = (
            finding.get("cwe_id"),
            finding.get("file_path"),
            finding.get("line_number"),
        )
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = finding
        else:
            # Take highest severity
            existing_rank = _SEVERITY_RANK.get(
                existing.get("sarif_level", "warning"), 0,
            )
            new_rank = _SEVERITY_RANK.get(
                finding.get("sarif_level", "warning"), 0,
            )
            if new_rank > existing_rank:
                deduped[key] = finding

    # Rebuild SARIF document from deduped findings
    results = []
    for finding in deduped.values():
        result: dict[str, Any] = {
            "ruleId": finding["rule_id"],
            "level": finding.get("sarif_level", "warning"),
            "message": {"text": finding["message"]},
        }
        if finding.get("file_path") or finding.get("line_number"):
            location: dict[str, Any] = {"physicalLocation": {}}
            if finding.get("file_path"):
                location["physicalLocation"]["artifactLocation"] = {
                    "uri": finding["file_path"],
                }
            if finding.get("line_number"):
                location["physicalLocation"]["region"] = {
                    "startLine": finding["line_number"],
                }
            result["locations"] = [location]
        results.append(result)

    merged_sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "wasa-merged",
                    "version": "1.0.0",
                },
            },
            "results": results,
        }],
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(merged_sarif, indent=2))

    logger.info(
        "SARIF merge complete",
        extra={
            "input_files": len(paths),
            "total_findings": len(all_findings),
            "deduped_findings": len(deduped),
            "output_path": output_path,
        },
    )
    return output_path


# ---------------------------------------------------------------------------
# Format conversion (non-SARIF → SARIF)
# ---------------------------------------------------------------------------

def convert_to_sarif(
    source_path: str,
    source_format: str,
    tool_name: str,
) -> None:
    """Convert a non-SARIF tool output file to SARIF 2.1.0 in-place.

    Supports: json (ruff, pip-audit, hadolint), jsonl (nuclei).
    The original file is overwritten with the SARIF version.
    """
    try:
        raw = Path(source_path).read_text()
    except FileNotFoundError:
        logger.warning(
            "Source file not found for SARIF conversion",
            extra={"path": source_path, "format": source_format},
        )
        return

    results: list[dict] = []

    if source_format == "json":
        results = _convert_json_to_sarif_results(raw, tool_name)
    elif source_format == "jsonl":
        results = _convert_jsonl_to_sarif_results(raw, tool_name)
    else:
        logger.warning(
            "Unsupported format for SARIF conversion",
            extra={"format": source_format, "tool": tool_name},
        )
        return

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": tool_name,
                    "version": "converted",
                },
            },
            "results": results,
        }],
    }

    Path(source_path).write_text(json.dumps(sarif, indent=2))


def _convert_json_to_sarif_results(
    raw: str, tool_name: str,
) -> list[dict]:
    """Convert JSON array of findings to SARIF results."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    results: list[dict] = []
    items = data if isinstance(data, list) else data.get("results", data.get("vulnerabilities", []))

    for item in items:
        if not isinstance(item, dict):
            continue
        result: dict[str, Any] = {
            "ruleId": item.get("code", item.get("rule", item.get("id", "unknown"))),
            "level": _map_severity_to_sarif_level(
                item.get("severity", item.get("level", "warning")),
            ),
            "message": {
                "text": item.get("message", item.get("description", str(item))),
            },
        }
        # Extract location
        file_path = item.get("filename", item.get("file", item.get("path")))
        line = item.get("line", item.get("line_number"))
        if file_path or line:
            loc: dict[str, Any] = {"physicalLocation": {}}
            if file_path:
                loc["physicalLocation"]["artifactLocation"] = {"uri": file_path}
            if line:
                loc["physicalLocation"]["region"] = {"startLine": int(line)}
            result["locations"] = [loc]
        results.append(result)

    return results


def _convert_jsonl_to_sarif_results(
    raw: str, tool_name: str,
) -> list[dict]:
    """Convert JSONL (one JSON object per line) to SARIF results."""
    results: list[dict] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        results.append({
            "ruleId": item.get("template-id", item.get("id", "unknown")),
            "level": _map_severity_to_sarif_level(
                item.get("severity", item.get("info", {}).get("severity", "medium")),
            ),
            "message": {
                "text": item.get("name", item.get("info", {}).get("name", str(item))),
            },
        })
    return results


def _map_severity_to_sarif_level(severity: str) -> str:
    """Map tool-specific severity strings to SARIF levels."""
    s = severity.lower().strip()
    if s in ("critical", "high", "error"):
        return "error"
    if s in ("medium", "warning"):
        return "warning"
    if s in ("low", "info", "informational", "note"):
        return "note"
    return "warning"
