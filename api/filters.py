"""Declared `django-filter` FilterSets for every list endpoint.

Replaces the hand-rolled `request.query_params.get(...)` blocks that
previously lived inline in each ViewSet's `get_queryset()` override
(one of the project's explicitly-documented "Known Tradeoffs"). Declaring
filters here instead: (1) is self-documenting — `SpectacularAPIView`
introspects `FilterSet` classes to generate accurate OpenAPI query-param
docs automatically, which hand-rolled filtering never got; (2) centralizes
validation of filter *values* (e.g. an invalid `date_from` now produces a
field-keyed 400 through the same `careflow_exception_handler` envelope as
every other validation error, instead of the ad hoc per-view handling this
replaces); (3) removes near-identical filtering boilerplate duplicated
across 10+ `get_queryset()` methods.

`RiskAssessmentFilterSet` is also reused directly (not just via
`DjangoFilterBackend`) by `AssessmentExportCSVView`, which is a plain
`APIView` rather than a `ViewSet` and so has no `filter_backends` of its
own — see that view for the manual `.qs` usage. This is the same filtering
logic applied to two different call sites, which is exactly the kind of
duplication `django-filter` is meant to remove.
"""
from __future__ import annotations

import django_filters as filters

from .models import (
    Admission,
    Appointment,
    Bed,
    ClinicalAlert,
    CommunityResource,
    DomainEvent,
    LabOrder,
    MedicationOrder,
    Patient,
    PatientCheckIn,
    ResourceReferral,
    RiskAssessment,
    WorkflowRule,
)


class PatientFilterSet(filters.FilterSet):
    min_age = filters.NumberFilter(field_name='age', lookup_expr='gte')
    max_age = filters.NumberFilter(field_name='age', lookup_expr='lte')
    blood_type = filters.CharFilter(field_name='blood_type', lookup_expr='iexact')

    class Meta:
        model = Patient
        fields = ['gender', 'blood_type', 'min_age', 'max_age']


class AppointmentFilterSet(filters.FilterSet):
    patient = filters.NumberFilter(field_name='patient_id')
    date_from = filters.DateFilter(field_name='scheduled_at', lookup_expr='date__gte')
    date_to = filters.DateFilter(field_name='scheduled_at', lookup_expr='date__lte')

    class Meta:
        model = Appointment
        fields = ['patient', 'status', 'date_from', 'date_to']


class BedFilterSet(filters.FilterSet):
    ward = filters.NumberFilter(field_name='ward_id')
    available_only = filters.BooleanFilter(method='filter_available_only')

    class Meta:
        model = Bed
        fields = ['ward', 'status', 'available_only']

    def filter_available_only(self, queryset, name, value):
        if value:
            return queryset.filter(status=Bed.STATUS_AVAILABLE)
        return queryset


class AdmissionFilterSet(filters.FilterSet):
    patient = filters.NumberFilter(field_name='patient_id')
    active = filters.BooleanFilter(method='filter_active')

    class Meta:
        model = Admission
        fields = ['patient', 'status', 'active']

    def filter_active(self, queryset, name, value):
        if value:
            return queryset.filter(status=Admission.STATUS_ADMITTED)
        return queryset


class MedicationOrderFilterSet(filters.FilterSet):
    patient = filters.NumberFilter(field_name='patient_id')
    admission = filters.NumberFilter(field_name='admission_id')

    class Meta:
        model = MedicationOrder
        fields = ['patient', 'admission', 'status']


class LabOrderFilterSet(filters.FilterSet):
    patient = filters.NumberFilter(field_name='patient_id')
    admission = filters.NumberFilter(field_name='admission_id')

    class Meta:
        model = LabOrder
        fields = ['patient', 'admission', 'status', 'priority']


class PatientCheckInFilterSet(filters.FilterSet):
    patient = filters.NumberFilter(field_name='patient_id')
    urgent = filters.BooleanFilter(method='filter_urgent')

    class Meta:
        model = PatientCheckIn
        fields = ['patient', 'urgent']

    def filter_urgent(self, queryset, name, value):
        if value:
            return queryset.urgent()
        return queryset


class CommunityResourceFilterSet(filters.FilterSet):
    class Meta:
        model = CommunityResource
        fields = ['category', 'active']


class ResourceReferralFilterSet(filters.FilterSet):
    patient = filters.NumberFilter(field_name='patient_id')

    class Meta:
        model = ResourceReferral
        fields = ['patient', 'status']


class WorkflowRuleFilterSet(filters.FilterSet):
    class Meta:
        model = WorkflowRule
        fields = ['event_type', 'active']


class DomainEventFilterSet(filters.FilterSet):
    class Meta:
        model = DomainEvent
        fields = ['event_type', 'status']


class ClinicalAlertFilterSet(filters.FilterSet):
    class Meta:
        model = ClinicalAlert
        fields = ['resolved', 'severity']


class RiskAssessmentFilterSet(filters.FilterSet):
    patient = filters.NumberFilter(field_name='patient_id')
    date_from = filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    date_to = filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = RiskAssessment
        fields = ['patient', 'risk_level', 'date_from', 'date_to']
