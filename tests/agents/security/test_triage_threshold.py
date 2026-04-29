"""Tests for triage invariants T-01 through T-04.

Validates:
- T-01: FP verdict requires non-empty triage_rationale
- T-02: FP confidence must be >= 0.75 to classify as FP; below = UNCERTAIN
- T-03: (Behavioural — tested at integration level, not here)
- T-04: Suppressed findings tracked for audit trail
"""

import pytest

from modules.backend.agents.security.models import (
    Finding,
    TriageVerdict,
)


def _triaged_finding(**overrides: object) -> dict:
    """Build a minimal triaged finding dict."""
    base = {
        "finding_id": "F-001",
        "title": "SQL Injection in user query",
        "description": "Raw SQL with f-string interpolation allows injection",
        "severity": "HIGH",
        "owasp_category": "A03",
        "evidence": "text(f\"SELECT * FROM users WHERE id = {user_id}\")",
        "source_phase": "scan",
        "source_tool": "opengrep",
        "remediation": "Use parameterised queries via SQLAlchemy ORM",
        "file_path": "app/routes/users.py",
        "line_number": 42,
    }
    base.update(overrides)
    return base


class TestT01FpRequiresRationale:
    """T-01: Every FP verdict has a non-empty triage_rationale."""

    def test_fp_without_rationale_rejected(self):
        with pytest.raises(ValueError, match="triage_rationale required"):
            Finding(**_triaged_finding(
                triage_verdict="FALSE_POSITIVE",
                fp_confidence=0.9,
                triage_rationale=None,
            ))

    def test_fp_with_empty_rationale_rejected(self):
        with pytest.raises(ValueError, match="triage_rationale required"):
            Finding(**_triaged_finding(
                triage_verdict="FALSE_POSITIVE",
                fp_confidence=0.9,
                triage_rationale="",
            ))

    def test_fp_with_rationale_accepted(self):
        f = Finding(**_triaged_finding(
            triage_verdict="FALSE_POSITIVE",
            fp_confidence=0.9,
            triage_rationale="ORM parameterised query — not injectable",
        ))
        assert f.triage_verdict == TriageVerdict.FALSE_POSITIVE

    def test_tp_without_rationale_ok(self):
        f = Finding(**_triaged_finding(
            triage_verdict="TRUE_POSITIVE",
            triage_rationale=None,
        ))
        assert f.triage_verdict == TriageVerdict.TRUE_POSITIVE

    def test_uncertain_without_rationale_ok(self):
        f = Finding(**_triaged_finding(
            triage_verdict="UNCERTAIN",
            triage_rationale=None,
        ))
        assert f.triage_verdict == TriageVerdict.UNCERTAIN


class TestT02FpConfidenceThreshold:
    """T-02: FP confidence >= 0.75 required for FALSE_POSITIVE.

    This is a behavioural invariant enforced by the triage agent's
    prompt and the config threshold — not a Pydantic validator. We test
    that the config default is 0.75 and that the Finding model accepts
    confidence values in [0, 1].
    """

    def test_config_default_threshold(self):
        from modules.backend.core.config_schema import SecurityAssessmentSchema
        schema = SecurityAssessmentSchema(roe_opa_endpoint="http://localhost:8181")
        assert schema.triage_fp_confidence_threshold == 0.75

    def test_confidence_below_threshold_is_valid_pydantic(self):
        """The model accepts any float in [0,1] — threshold is prompt-enforced."""
        f = Finding(**_triaged_finding(
            triage_verdict="UNCERTAIN",
            fp_confidence=0.5,
        ))
        assert f.fp_confidence == 0.5

    def test_confidence_above_threshold_for_fp(self):
        f = Finding(**_triaged_finding(
            triage_verdict="FALSE_POSITIVE",
            fp_confidence=0.85,
            triage_rationale="Confirmed safe by ORM usage",
        ))
        assert f.fp_confidence == 0.85

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            Finding(**_triaged_finding(fp_confidence=1.5))


class TestT04SuppressedFindingsAuditTrail:
    """T-04: Suppressed (FP) findings available for audit trail."""

    def test_fp_finding_can_be_serialised(self):
        """FP findings must be serialisable for the suppressed_findings list."""
        f = Finding(**_triaged_finding(
            triage_verdict="FALSE_POSITIVE",
            fp_confidence=0.9,
            triage_rationale="Known test placeholder value",
        ))
        data = f.model_dump()
        assert data["triage_verdict"] == "FALSE_POSITIVE"
        assert data["triage_rationale"] == "Known test placeholder value"

    def test_report_accepts_suppressed_findings(self):
        from modules.backend.agents.security.models import SecurityAssessmentReport

        fp_finding = Finding(**_triaged_finding(
            triage_verdict="FALSE_POSITIVE",
            fp_confidence=0.9,
            triage_rationale="ORM safe",
        ))

        report = SecurityAssessmentReport(
            report_id="RPT-001",
            target_name="Test App",
            assessment_date="2026-04-29",
            engagement_id="ENG-001",
            roe_sha256="abc123",
            overall_risk_score=3.0,
            overall_risk_posture="LOW",
            executive_summary="x" * 300,
            finding_counts={"LOW": 0},
            owasp_coverage={},
            confirmed_findings=[],
            suppressed_findings=[fp_finding],
            remediation_roadmap=[],
            phases_completed=["scan", "triage"],
            scanners_run=["opengrep"],
            dast_performed=False,
            exploit_stage_reached=0,
            total_tool_calls=5,
            total_cost_usd=2.0,
            duration_hours=0.1,
            assessment_scope="SAST only",
            evidence_manifest_sha256="def456",
            known_limitations=["Phase 1 — SAST only"],
        )
        assert len(report.suppressed_findings) == 1
        assert report.suppressed_findings[0].triage_verdict == TriageVerdict.FALSE_POSITIVE
