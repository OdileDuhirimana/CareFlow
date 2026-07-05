"""Patient care-plan recommendation business rules ("next actions").

Moved out of `api/views.py` (previously inline in
`PatientViewSet.care_plan`) — see `api/services/triage.py`'s module
docstring for the shared ARC-01 rationale.
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone

from api.models import Appointment, Patient, RiskAssessment

#: Bounded so the response stays a short, actionable list rather than an
#: unbounded narrative.
NEXT_ACTIONS_LIMIT = 5
UPCOMING_APPOINTMENTS_LIMIT = 3


def build_care_plan(patient: Patient) -> dict[str, Any]:
    latest_assessment = patient.risk_assessments.first()
    upcoming_appointments = patient.appointments.filter(
        status=Appointment.STATUS_SCHEDULED,
        scheduled_at__gte=timezone.now(),
    ).order_by('scheduled_at')[:UPCOMING_APPOINTMENTS_LIMIT]

    actions: list[str] = []
    if latest_assessment:
        if latest_assessment.risk_level in [RiskAssessment.LEVEL_HIGH, RiskAssessment.LEVEL_CRITICAL]:
            actions.append('Prioritize clinician outreach within 24 hours.')
            if not upcoming_appointments:
                actions.append('Book urgent follow-up appointment this week.')
        elif latest_assessment.risk_level == RiskAssessment.LEVEL_MEDIUM:
            actions.append('Plan follow-up in 2-4 weeks with updated vitals.')
        else:
            actions.append('Continue routine monitoring and preventive screenings.')

    if patient.diagnosis:
        actions.append(f'Review current treatment protocol for: {patient.diagnosis}.')
    else:
        actions.append('Capture a formal diagnosis to personalize future risk tracking.')

    return {
        'latest_assessment': latest_assessment,
        'upcoming_appointments': upcoming_appointments,
        'next_actions': actions[:NEXT_ACTIONS_LIMIT],
    }
