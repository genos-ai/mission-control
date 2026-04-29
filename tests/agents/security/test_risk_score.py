"""Tests for composite risk score calculation (R-02).

Validates the report_risk_score_weights config and the composite
formula: (CVSS * 0.40) + (exploitability * 0.30) + (business_impact * 0.30).
"""

import pytest

from modules.backend.core.config_schema import SecurityAssessmentSchema


class TestRiskScoreWeights:
    def test_default_weights_sum_to_one(self):
        schema = SecurityAssessmentSchema(roe_opa_endpoint="http://localhost:8181")
        weights = schema.report_risk_score_weights
        total = weights.cvss + weights.exploitability + weights.business_impact
        assert abs(total - 1.0) < 1e-9

    def test_default_cvss_weight(self):
        schema = SecurityAssessmentSchema(roe_opa_endpoint="http://localhost:8181")
        assert schema.report_risk_score_weights.cvss == 0.40

    def test_default_exploitability_weight(self):
        schema = SecurityAssessmentSchema(roe_opa_endpoint="http://localhost:8181")
        assert schema.report_risk_score_weights.exploitability == 0.30

    def test_default_business_impact_weight(self):
        schema = SecurityAssessmentSchema(roe_opa_endpoint="http://localhost:8181")
        assert schema.report_risk_score_weights.business_impact == 0.30


class TestCompositeRiskScore:
    """Test the composite risk formula application."""

    def test_formula_calculation(self):
        """(CVSS * 0.40) + (exploitability * 0.30) + (business_impact * 0.30)"""
        schema = SecurityAssessmentSchema(roe_opa_endpoint="http://localhost:8181")
        w = schema.report_risk_score_weights

        cvss = 9.0
        exploitability = 8.0
        business_impact = 7.0

        score = (cvss * w.cvss) + (exploitability * w.exploitability) + (business_impact * w.business_impact)
        expected = (9.0 * 0.40) + (8.0 * 0.30) + (7.0 * 0.30)
        assert abs(score - expected) < 1e-9
        assert abs(score - 8.1) < 1e-9

    def test_all_zeros(self):
        schema = SecurityAssessmentSchema(roe_opa_endpoint="http://localhost:8181")
        w = schema.report_risk_score_weights
        score = (0.0 * w.cvss) + (0.0 * w.exploitability) + (0.0 * w.business_impact)
        assert score == 0.0

    def test_all_tens(self):
        schema = SecurityAssessmentSchema(roe_opa_endpoint="http://localhost:8181")
        w = schema.report_risk_score_weights
        score = (10.0 * w.cvss) + (10.0 * w.exploitability) + (10.0 * w.business_impact)
        assert abs(score - 10.0) < 1e-9

    def test_report_risk_score_range(self):
        """SecurityAssessmentReport enforces 0.0 <= overall_risk_score <= 10.0."""
        from modules.backend.agents.security.models import SecurityAssessmentReport

        with pytest.raises(ValueError):
            SecurityAssessmentReport(
                report_id="R", target_name="T", assessment_date="2026-04-29",
                engagement_id="E", roe_sha256="h",
                overall_risk_score=11.0,  # out of range
                overall_risk_posture="CRITICAL",
                executive_summary="x" * 300,
                finding_counts={}, owasp_coverage={},
                confirmed_findings=[], remediation_roadmap=[],
                phases_completed=["scan"], scanners_run=["opengrep"],
                dast_performed=False, exploit_stage_reached=0,
                total_tool_calls=1, total_cost_usd=1.0,
                duration_hours=0.1, assessment_scope="SAST",
                evidence_manifest_sha256="h",
                known_limitations=["Phase 1"],
            )
