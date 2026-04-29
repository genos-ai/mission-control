"""WASA configuration — thin re-export from platform config.

Usage:
    from modules.backend.agents.security.config import get_security_assessment_config
    config = get_security_assessment_config()
"""

from modules.backend.core.config import get_app_config
from modules.backend.core.config_schema import SecurityAssessmentSchema


def get_security_assessment_config() -> SecurityAssessmentSchema:
    """Load WASA config from config/settings/security_assessment.yaml."""
    return get_app_config().security_assessment
