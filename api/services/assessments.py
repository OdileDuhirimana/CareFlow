"""Risk-assessment persistence + automatic high-risk alerting business rules.

Moved out of `api/views.py` (previously inline in
`TriageAssessmentView.post`) — see `api/services/triage.py`'s module
docstring for the shared ARC-01 rationale. Uses
`api.services.triage.score_health_risk` for the actual scoring, keeping
"compute the score" and "persist the assessment + react to it" as two
separate, independently testable responsibilities.
"""
from __future__ import annotations

import logging
from typing import Any

from api.models import ClinicalAlert, RiskAssessment
from api.services.triage import score_health_risk
from api.services.workflow_engine import emit_domain_event

logger = logging.getLogger('careflow.app')

#: Risk levels that warrant an automatic clinical alert when a patient is
#: linked to the assessment. Assessments with no linked patient (the public
#: `/predict/health-risk/` demo endpoint) never create alerts or persist a
#: `RiskAssessment` row — see `PredictHealthRiskView`, which calls
#: `score_health_risk` directly rather than this function.
ALERT_WORTHY_RISK_LEVELS = (RiskAssessment.LEVEL_HIGH, RiskAssessment.LEVEL_CRITICAL)


def record_triage_assessment(validated_data: dict[str, Any], assessed_by) -> dict[str, Any]:
    """Score, persist, and react to a clinician-submitted triage assessment.

    Returns a dict with the persisted `assessment`, `alert_created` (bool),
    and `alert_id`.
    """
    scored = score_health_risk(validated_data)

    assessment = RiskAssessment.objects.create(
        patient=validated_data.get('patient'),
        assessed_by=assessed_by,
        age=validated_data['age'],
        bmi=validated_data['bmi'],
        blood_pressure=validated_data['blood_pressure'],
        cholesterol=validated_data['cholesterol'],
        smoker=validated_data['smoker'],
        exercise_minutes=validated_data['exercise_minutes'],
        chronic_conditions=validated_data['chronic_conditions'],
        risk_score=scored['risk_score'],
        risk_level=scored['risk_level'],
        recommended_action=scored['recommended_action'],
        key_drivers=scored['key_drivers'],
    )

    alert_id = None
    if assessment.patient and assessment.risk_level in ALERT_WORTHY_RISK_LEVELS:
        severity = (
            ClinicalAlert.SEVERITY_CRITICAL
            if assessment.risk_level == RiskAssessment.LEVEL_CRITICAL
            else ClinicalAlert.SEVERITY_HIGH
        )
        alert = ClinicalAlert.objects.create(
            patient=assessment.patient,
            assessment=assessment,
            severity=severity,
            title=f'{assessment.risk_level} risk patient flagged',
            message=assessment.recommended_action,
        )
        alert_id = alert.id
        logger.info(
            'clinical_alert_created',
            extra={
                'alert_id': alert.id,
                'patient_id': assessment.patient_id,
                'severity': alert.severity,
                'source': 'triage_assessment',
            },
        )

    emit_domain_event(
        event_type='triage.assessed',
        source='triage.assess',
        payload={
            'assessment_id': assessment.id,
            'patient_id': assessment.patient_id,
            'age': assessment.age,
            'risk_score': assessment.risk_score,
            'risk_level': assessment.risk_level,
            'recommended_action': assessment.recommended_action,
            'alert_id': alert_id,
        },
    )

    return {'assessment': assessment, 'alert_created': bool(alert_id), 'alert_id': alert_id}
