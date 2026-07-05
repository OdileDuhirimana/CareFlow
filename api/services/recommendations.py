"""Community-resource recommendation and auto-referral business rules.

Moved out of `api/views.py` (previously the private
`_resource_recommendation_bundle` function, plus the auto-referral loop
inline in `PatientViewSet.community_recommendations`) — see
`api/services/triage.py`'s module docstring for the shared ARC-01 rationale.
"""
from __future__ import annotations

from typing import Any

from api.models import CommunityResource, Patient, ResourceReferral, RiskAssessment


def resource_recommendation_bundle(patient: Patient) -> list[dict[str, Any]]:
    """Build category-grouped community-resource recommendations for a patient.

    Recommendations are derived from the patient's latest risk assessment,
    diagnosis keywords, latest check-in mood/adherence, and age — each
    signal contributes a category + a human-readable reason, and matching
    active resources are attached (capped at 5 per category to keep
    responses bounded).
    """
    diagnosis = (patient.diagnosis or '').lower()
    latest_assessment = patient.risk_assessments.first()
    latest_checkin = patient.checkins.first()

    categories: dict[str, str] = {}
    if latest_assessment and latest_assessment.risk_level in [RiskAssessment.LEVEL_HIGH, RiskAssessment.LEVEL_CRITICAL]:
        categories[CommunityResource.CATEGORY_CHRONIC_CARE] = 'High clinical risk requires longitudinal disease support.'
        categories[CommunityResource.CATEGORY_TRANSPORT] = 'Close follow-up visits benefit from transport support.'

    if any(keyword in diagnosis for keyword in ['diabet', 'hypertension', 'asthma', 'cardiac']):
        categories[CommunityResource.CATEGORY_CHRONIC_CARE] = 'Diagnosis suggests need for chronic care programs.'
    if any(keyword in diagnosis for keyword in ['depress', 'anxiety', 'stress']):
        categories[CommunityResource.CATEGORY_MENTAL_HEALTH] = 'Diagnosis indicates behavioral health support needs.'

    if latest_checkin and latest_checkin.mood_score <= 3:
        categories[CommunityResource.CATEGORY_MENTAL_HEALTH] = 'Recent check-in indicates emotional distress.'
    if latest_checkin and not latest_checkin.medication_taken:
        categories[CommunityResource.CATEGORY_FINANCIAL] = 'Medication adherence concerns may be linked to affordability.'
    if patient.age >= 65:
        categories[CommunityResource.CATEGORY_WELLNESS] = 'Older adults benefit from preventive and social wellness programs.'

    if not categories:
        categories[CommunityResource.CATEGORY_WELLNESS] = 'General prevention and wellness support.'

    resources = CommunityResource.objects.filter(active=True, category__in=list(categories.keys())).order_by('name')
    grouped: dict[str, list[CommunityResource]] = {}
    for resource in resources:
        grouped.setdefault(resource.category, []).append(resource)

    return [
        {
            'category': category,
            'reason': reason,
            'resources': grouped.get(category, [])[:5],
        }
        for category, reason in categories.items()
    ]


def create_auto_referrals(patient: Patient, bundle: list[dict[str, Any]], referred_by) -> list[int]:
    """Create a referral for the first recommended resource in each category.

    Idempotent per (patient, resource) pair via `get_or_create` — calling
    this twice for the same patient/bundle does not create duplicate
    referrals.
    """
    created_referral_ids: list[int] = []
    for item in bundle:
        resource = item['resources'][0] if item['resources'] else None
        if not resource:
            continue
        referral, created = ResourceReferral.objects.get_or_create(
            patient=patient,
            resource=resource,
            defaults={
                'referred_by': referred_by,
                'reason': item['reason'],
            },
        )
        if created:
            created_referral_ids.append(referral.id)
    return created_referral_ids
