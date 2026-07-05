"""Patient check-in submission business rules: persistence + automatic
clinical alerting + domain-event emission.

Moved out of `api/views.py` (previously inline in
`PatientCheckInViewSet.create`) — see `api/services/triage.py`'s module
docstring for the shared ARC-01 rationale.
"""
from __future__ import annotations

import logging
from typing import Any

from api.models import ClinicalAlert
from api.services.alerts import checkin_alert_payload
from api.services.workflow_engine import emit_domain_event

logger = logging.getLogger('careflow.app')


def submit_checkin(serializer, submitted_by) -> dict[str, Any]:
    """Persist a check-in, raise an alert if warranted, and emit a domain event.

    `serializer` must already be schema-valid. Returns a dict with the
    persisted `checkin`, `alert_created` (bool), and `alert_id`.
    """
    checkin = serializer.save(submitted_by=submitted_by)

    alert_id = None
    alert_payload = checkin_alert_payload(checkin)
    if alert_payload:
        alert = ClinicalAlert.objects.create(patient=checkin.patient, **alert_payload)
        alert_id = alert.id
        logger.info(
            'clinical_alert_created',
            extra={
                'alert_id': alert.id,
                'patient_id': checkin.patient_id,
                'severity': alert.severity,
                'source': 'checkin',
            },
        )

    emit_domain_event(
        event_type='checkin.submitted',
        source='checkins.create',
        payload={
            'checkin_id': checkin.id,
            'patient_id': checkin.patient_id,
            'patient_age': checkin.patient.age,
            'symptom_severity': checkin.symptom_severity,
            'mood_score': checkin.mood_score,
            'medication_taken': checkin.medication_taken,
            'systolic_bp': checkin.systolic_bp,
            'oxygen_saturation': checkin.oxygen_saturation,
            'heart_rate': checkin.heart_rate,
            'auto_alert_id': alert_id,
        },
    )

    return {'checkin': checkin, 'alert_created': bool(alert_id), 'alert_id': alert_id}
