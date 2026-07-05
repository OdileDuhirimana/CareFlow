"""Clinical alerting business rules.

Moved out of `api/views.py` (previously the private `_checkin_alert_payload`
function) — see `api/services/triage.py`'s module docstring for the shared
ARC-01 rationale that applies to every module in this package.
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from api.models import ClinicalAlert, PatientCheckIn


def checkin_alert_payload(checkin: PatientCheckIn) -> dict[str, Any] | None:
    """Decide whether a check-in should raise an automatic clinical alert.

    Reuses the same named thresholds as `PatientCheckInQuerySet.urgent()`
    (`PatientCheckIn.SEVERE_SYMPTOM_SEVERITY` etc., see `api/models.py`) so
    "what counts as urgent for filtering/analytics" and "what raises an
    alert" can never silently drift apart into two different definitions.

    Returns `None` if no signal crosses a threshold, otherwise a dict with
    `severity`, `title`, and `message` ready to pass to
    `ClinicalAlert.objects.create(patient=..., **payload)`.
    """
    signals = []
    if checkin.symptom_severity >= PatientCheckIn.SEVERE_SYMPTOM_SEVERITY:
        signals.append('severe symptoms')
    if checkin.oxygen_saturation is not None and checkin.oxygen_saturation < PatientCheckIn.LOW_OXYGEN_SATURATION:
        signals.append('low oxygen saturation')
    if checkin.systolic_bp is not None and checkin.systolic_bp >= PatientCheckIn.CRITICAL_SYSTOLIC_BP:
        signals.append('critical blood pressure')
    if checkin.heart_rate is not None and checkin.heart_rate >= PatientCheckIn.HIGH_HEART_RATE:
        signals.append('very high heart rate')
    if checkin.mood_score <= PatientCheckIn.LOW_MOOD_SCORE and not checkin.medication_taken:
        signals.append('acute mental health/medication adherence concern')

    if not signals:
        return None

    severity = ClinicalAlert.SEVERITY_CRITICAL if len(signals) >= 2 else ClinicalAlert.SEVERITY_HIGH
    return {
        'severity': severity,
        'title': 'Urgent remote monitoring check-in',
        'message': f"Patient reported {', '.join(signals)}. Escalate care outreach today.",
    }


def sync_alert_resolution_timestamp(alert: ClinicalAlert, was_resolved_before_update: bool) -> ClinicalAlert:
    """Keep `resolved_at` consistent with `resolved` after a state change.

    Moved out of `api/views.py` (previously inline in
    `ClinicalAlertViewSet.perform_update`) — the rule "resolving sets a
    timestamp, un-resolving clears it" is a business rule about what an
    alert's resolution state means, not a detail of how the HTTP PATCH
    request was shaped.
    """
    if not was_resolved_before_update and alert.resolved and not alert.resolved_at:
        alert.resolved_at = timezone.now()
        alert.save(update_fields=['resolved_at'])
    elif was_resolved_before_update and not alert.resolved and alert.resolved_at:
        alert.resolved_at = None
        alert.save(update_fields=['resolved_at'])
    return alert
