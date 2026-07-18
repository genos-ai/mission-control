"""Tests for WASA Pydantic output models.

Validates structural invariants from spec Section 4.3:
- T-01: FP verdict requires non-empty triage_rationale
- R-01: AttackPath requires >= 2 source findings
- R-02: Executive summary >= 300 chars
- R-04: known_limitations non-empty
- Severity normalisation (lowercase → uppercase)
- Finding must have (file_path + line_number) or (url)
- HttpResponseSummary notes clamped to 200 chars
"""

import pytest

from modules.backend.agents.security.models import (
    AttackPath,
    ExploitStage,
    Finding,
    HttpResponseSummary,
    OWASPCategory,
    RemediationItem,
    SecurityAssessmentReport,
    SeverityLevel,
    TriageVerdict,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_finding(**overrides: object) -> dict:
    """Build a minimal valid Finding dict."""
    base = {
        "finding_id": "F-001",
        "title": "SQL Injection in user query",
        "description": "Raw SQL with f-string interpolation allows injection",
        "severity": "HIGH",
        "owasp_category": "A03",
        "evidence": 'text(f"SELECT * FROM users WHERE id = {user_id}")',
        "source_phase": "scan",
        "source_tool": "opengrep",
        "remediation": "Use parameterised queries via SQLAlchemy ORM",
        "file_path": "app/routes/users.py",
        "line_number": 42,
    }
    base.update(overrides)
    return base


def _minimal_report(**overrides: object) -> dict:
    """Build a minimal valid SecurityAssessmentReport dict."""
    base = {
        "report_id": "RPT-001",
        "target_name": "Test App",
        "assessment_date": "2026-04-29",
        "engagement_id": "ENG-001",
        "roe_sha256": "abc123",
        "overall_risk_score": 7.5,
        "overall_risk_posture": "HIGH",
        "executive_summary": "x" * 300,
        "finding_counts": {"HIGH": 3, "MEDIUM": 2},
        "owasp_coverage": {"A03": ["F-001"]},
        "confirmed_findings": [],
        "remediation_roadmap": [
            {
                "finding_ref": "F-001",
                "priority": "IMMEDIATE",
                "action": "Replace raw SQL with ORM parameterised queries",
                "effort_estimate": "2 hours",
            }
        ],
        "phases_completed": ["scan", "triage", "report"],
        "scanners_run": ["opengrep", "ruff"],
        "dast_performed": False,
        "exploit_stage_reached": 0,
        "total_tool_calls": 12,
        "total_cost_usd": 8.50,
        "duration_hours": 0.25,
        "assessment_scope": "SAST only",
        "evidence_manifest_sha256": "def456",
        "known_limitations": ["Timing side channels not tested"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Finding tests
# ---------------------------------------------------------------------------


class TestFinding:
    def test_valid_finding(self):
        f = Finding(**_minimal_finding())
        assert f.finding_id == "F-001"
        assert f.severity == SeverityLevel.HIGH

    def test_severity_normalisation(self):
        """Lowercase severity string is coerced to uppercase enum."""
        f = Finding(**_minimal_finding(severity="high"))
        assert f.severity == SeverityLevel.HIGH

    def test_severity_mixed_case(self):
        f = Finding(**_minimal_finding(severity="Medium"))
        assert f.severity == SeverityLevel.MEDIUM

    def test_finding_requires_file_or_url(self):
        """A finding without both file and URL locations is rejected."""
        with pytest.raises(ValueError, match="file_path.*line_number.*url"):
            Finding(**_minimal_finding(file_path=None, line_number=None, url=None))

    def test_finding_with_url_only(self):
        """DAST finding with URL but no file_path is valid."""
        f = Finding(
            **_minimal_finding(
                file_path=None,
                line_number=None,
                url="https://example.com/api/users",
            )
        )
        assert f.url == "https://example.com/api/users"

    def test_finding_with_file_only(self):
        """SAST finding with file_path + line_number but no URL is valid."""
        f = Finding(**_minimal_finding(url=None))
        assert f.file_path == "app/routes/users.py"

    def test_fp_requires_rationale(self):
        """T-01: FALSE_POSITIVE verdict without rationale is rejected."""
        with pytest.raises(ValueError, match="triage_rationale required"):
            Finding(
                **_minimal_finding(
                    triage_verdict="FALSE_POSITIVE",
                    triage_rationale=None,
                )
            )

    def test_fp_with_rationale_accepted(self):
        f = Finding(
            **_minimal_finding(
                triage_verdict="FALSE_POSITIVE",
                fp_confidence=0.9,
                triage_rationale="ORM parameterised query confirmed safe",
            )
        )
        assert f.triage_verdict == TriageVerdict.FALSE_POSITIVE

    def test_tp_without_rationale_accepted(self):
        """TRUE_POSITIVE does not require triage_rationale."""
        f = Finding(
            **_minimal_finding(
                triage_verdict="TRUE_POSITIVE",
                triage_rationale=None,
            )
        )
        assert f.triage_verdict == TriageVerdict.TRUE_POSITIVE

    def test_title_min_length(self):
        with pytest.raises(ValueError):
            Finding(**_minimal_finding(title="SQL"))

    def test_description_min_length(self):
        with pytest.raises(ValueError):
            Finding(**_minimal_finding(description="Short"))

    def test_remediation_min_length(self):
        with pytest.raises(ValueError):
            Finding(**_minimal_finding(remediation="Fix it"))


# ---------------------------------------------------------------------------
# AttackPath tests
# ---------------------------------------------------------------------------


class TestAttackPath:
    def test_valid_attack_path(self):
        ap = AttackPath(
            path_id="AP-001",
            title="SQLi to data exfil",
            scenario="Attacker exploits SQL injection then extracts PII",
            source_findings=["F-001", "F-002"],
            combined_severity="CRITICAL",
            attacker_prerequisites="Network access",
            business_impact="Customer data breach",
        )
        assert len(ap.source_findings) == 2

    def test_attack_path_requires_two_findings(self):
        """R-01: AttackPath must reference >= 2 distinct findings."""
        with pytest.raises(ValueError):
            AttackPath(
                path_id="AP-001",
                title="Single finding",
                scenario="Only one finding",
                source_findings=["F-001"],
                combined_severity="HIGH",
                attacker_prerequisites="None",
                business_impact="Minor",
            )


# ---------------------------------------------------------------------------
# Report tests
# ---------------------------------------------------------------------------


class TestSecurityAssessmentReport:
    def test_valid_report(self):
        r = SecurityAssessmentReport(**_minimal_report())
        assert r.report_id == "RPT-001"

    def test_executive_summary_min_length(self):
        """R-02: executive_summary must be >= 300 chars."""
        with pytest.raises(ValueError):
            SecurityAssessmentReport(
                **_minimal_report(
                    executive_summary="Too short",
                )
            )

    def test_known_limitations_required(self):
        """R-04: known_limitations must be non-empty."""
        with pytest.raises(ValueError):
            SecurityAssessmentReport(
                **_minimal_report(
                    known_limitations=[],
                )
            )

    def test_report_with_findings(self):
        finding = Finding(**_minimal_finding())
        r = SecurityAssessmentReport(
            **_minimal_report(
                confirmed_findings=[finding.model_dump()],
            )
        )
        assert len(r.confirmed_findings) == 1


# ---------------------------------------------------------------------------
# HttpResponseSummary tests
# ---------------------------------------------------------------------------


class TestHttpResponseSummary:
    def test_valid_summary(self):
        s = HttpResponseSummary(status=200, notes="Login page detected")
        assert s.status == 200

    def test_notes_max_length(self):
        """Notes field clamped to 200 chars."""
        with pytest.raises(ValueError):
            HttpResponseSummary(status=200, notes="x" * 201)

    def test_notes_at_limit(self):
        s = HttpResponseSummary(status=200, notes="x" * 200)
        assert len(s.notes) == 200


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    def test_owasp_category_values(self):
        assert OWASPCategory.A01_BROKEN_ACCESS_CONTROL.value == "A01"
        assert OWASPCategory.A10_SSRF.value == "A10"

    def test_exploit_stage_ordering(self):
        assert ExploitStage.PASSIVE_RECON < ExploitStage.DESTRUCTIVE
        assert ExploitStage.AUTHENTICATED_TESTING.value == 2

    def test_remediation_priority_values(self):
        from modules.backend.agents.security.models import RemediationPriority

        assert RemediationPriority.IMMEDIATE.value == "IMMEDIATE"
