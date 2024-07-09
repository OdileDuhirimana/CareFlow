import csv
from datetime import timedelta

import numpy as np
from django.db import connection, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Admission,
    Appointment,
    Bed,
    ClinicalAlert,
    CommunityResource,
    DomainEvent,
    HospitalWard,
    LabOrder,
    MedicationOrder,
    Patient,
    PatientCheckIn,
    ResourceReferral,
    RiskAssessment,
    WorkflowRule,
)
from .permissions import (
    AlertPermission,
    ClinicianAdminOnly,
    ClinicalWritePermission,
    CommunityCatalogPermission,
    CommunityWorkflowPermission,
    HasCareflowRole,
    InfrastructureCatalogPermission,
    WorkflowEventPermission,
    WorkflowRulePermission,
)
from .services.workflow_engine import emit_domain_event, process_pending_domain_events
from .serializers import (
    AdmissionDischargeRequestSerializer,
    AdmissionSerializer,
    AdmissionTransferRequestSerializer,
    AnalyticsOverviewSerializer,
    AppointmentSerializer,
    BedSerializer,
    ClinicalAlertSerializer,
    CommunityRecommendationResponseSerializer,
    CommunityResourceSerializer,
    CheckInResponseSerializer,
    CurrentUserProfileSerializer,
    DomainEventSerializer,
    HospitalFlowOverviewSerializer,
    HospitalWardSerializer,
    ImpactOverviewSerializer,
    LabOrderCompleteSerializer,
    LabOrderSerializer,
    MedicationOrderSerializer,
    MedicationStatusUpdateSerializer,
    PatientSerializer,
    PatientCheckInSerializer,
    ProcessDomainEventsRequestSerializer,
    ProcessDomainEventsResponseSerializer,
    ResourceReferralSerializer,
    RiskPredictionSerializer,
    RiskAssessmentSerializer,
    TriageAssessmentResponseSerializer,
    TriageAssessmentRequestSerializer,
    WorkflowRuleSerializer,
)


def _score_health_risk(data):
    age = data['age']
    bmi = data['bmi']
    blood_pressure = data['blood_pressure']
    cholesterol = data['cholesterol']
    smoker = data.get('smoker', False)
    exercise_minutes = data.get('exercise_minutes', 0)
    chronic_conditions = data.get('chronic_conditions', 0)

    age_component = min(age / 100, 1)
    bmi_component = np.clip((bmi - 18.5) / 21.5, 0, 1)
    bp_component = np.clip((blood_pressure - 90) / 90, 0, 1)
    chol_component = np.clip((cholesterol - 130) / 220, 0, 1)
    smoker_component = 1.0 if smoker else 0.0
    exercise_component = 1.0 - np.clip(exercise_minutes / 300, 0, 1)
    chronic_component = np.clip(chronic_conditions / 5, 0, 1)

    contributions = {
        'age': float(age_component * 0.16),
        'bmi': float(bmi_component * 0.18),
        'blood_pressure': float(bp_component * 0.22),
        'cholesterol': float(chol_component * 0.14),
        'smoking': float(smoker_component * 0.14),
        'exercise_deficit': float(exercise_component * 0.06),
        'chronic_conditions': float(chronic_component * 0.10),
    }

    score = float(np.clip(sum(contributions.values()), 0, 1))

    if score >= 0.78:
        level = RiskAssessment.LEVEL_CRITICAL
        recommendation = 'Immediate physician escalation and same-day diagnostics.'
    elif score >= 0.60:
        level = RiskAssessment.LEVEL_HIGH
        recommendation = 'Schedule specialist review within 72 hours and monitor vitals daily.'
    elif score >= 0.38:
        level = RiskAssessment.LEVEL_MEDIUM
        recommendation = 'Initiate lifestyle intervention plan and reassess within 30 days.'
    else:
        level = RiskAssessment.LEVEL_LOW
        recommendation = 'Maintain preventive care and standard quarterly follow-up.'

    key_drivers = [
        {'factor': factor, 'impact': round(impact, 3)}
        for factor, impact in sorted(contributions.items(), key=lambda item: item[1], reverse=True)
        if impact > 0
    ][:3]

    return {
        'risk_score': round(score, 2),
        'risk_level': level,
        'recommended_action': recommendation,
        'key_drivers': key_drivers,
    }


def _parse_optional_date(value, label):
    if not value:
        return None, None
    parsed = parse_date(value)
    if parsed is None:
        return None, f'Invalid {label}. Expected YYYY-MM-DD.'
    return parsed, None


def _set_bed_available(bed):
    if not bed:
        return
    bed.status = Bed.STATUS_AVAILABLE
    bed.current_patient = None
    bed.save(update_fields=['status', 'current_patient', 'updated_at'])


def _assign_bed_to_patient(bed, patient):
    bed.status = Bed.STATUS_OCCUPIED
    bed.current_patient = patient
    bed.save(update_fields=['status', 'current_patient', 'updated_at'])


def _checkin_alert_payload(checkin):
    signals = []
    if checkin.symptom_severity >= 8:
        signals.append('severe symptoms')
    if checkin.oxygen_saturation is not None and checkin.oxygen_saturation < 92:
        signals.append('low oxygen saturation')
    if checkin.systolic_bp is not None and checkin.systolic_bp >= 180:
        signals.append('critical blood pressure')
    if checkin.heart_rate is not None and checkin.heart_rate >= 130:
        signals.append('very high heart rate')
    if checkin.mood_score <= 2 and not checkin.medication_taken:
        signals.append('acute mental health/medication adherence concern')

    if not signals:
        return None

    severity = ClinicalAlert.SEVERITY_CRITICAL if len(signals) >= 2 else ClinicalAlert.SEVERITY_HIGH
    return {
        'severity': severity,
        'title': 'Urgent remote monitoring check-in',
        'message': f"Patient reported {', '.join(signals)}. Escalate care outreach today.",
    }


def _resource_recommendation_bundle(patient):
    diagnosis = (patient.diagnosis or '').lower()
    latest_assessment = patient.risk_assessments.first()
    latest_checkin = patient.checkins.first()

    categories = {}
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
    grouped = {}
    for resource in resources:
        grouped.setdefault(resource.category, []).append(resource)

    results = []
    for category, reason in categories.items():
        results.append(
            {
                'category': category,
                'reason': reason,
                'resources': grouped.get(category, [])[:5],
            }
        )
    return results


class PatientViewSet(viewsets.ModelViewSet):
    queryset = Patient.objects.all().order_by('-created_at')
    serializer_class = PatientSerializer
    permission_classes = [ClinicalWritePermission]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'diagnosis', 'blood_type']
    ordering_fields = ['name', 'age', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        gender = self.request.query_params.get('gender')
        blood_type = self.request.query_params.get('blood_type')
        min_age = self.request.query_params.get('min_age')
        max_age = self.request.query_params.get('max_age')

        if gender:
            queryset = queryset.filter(gender=gender)
        if blood_type:
            queryset = queryset.filter(blood_type__iexact=blood_type)
        if min_age and min_age.isdigit():
            queryset = queryset.filter(age__gte=int(min_age))
        if max_age and max_age.isdigit():
            queryset = queryset.filter(age__lte=int(max_age))
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'], url_path='care-plan')
    def care_plan(self, request, pk=None):
        patient = self.get_object()
        latest_assessment = patient.risk_assessments.first()
        upcoming_appointments = patient.appointments.filter(
            status=Appointment.STATUS_SCHEDULED,
            scheduled_at__gte=timezone.now(),
        ).order_by('scheduled_at')[:3]

        actions = []
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
        if not patient.diagnosis:
            actions.append('Capture a formal diagnosis to personalize future risk tracking.')

        return Response(
            {
                'patient': PatientSerializer(patient).data,
                'latest_assessment': RiskAssessmentSerializer(latest_assessment).data if latest_assessment else None,
                'upcoming_appointments': AppointmentSerializer(upcoming_appointments, many=True).data,
                'next_actions': actions[:5],
            }
        )

    @extend_schema(responses={200: CommunityRecommendationResponseSerializer})
    @action(detail=True, methods=['get'], url_path='community-recommendations')
    def community_recommendations(self, request, pk=None):
        patient = self.get_object()
        bundle = _resource_recommendation_bundle(patient)
        auto_refer = request.query_params.get('auto_refer') == 'true'
        created_referrals = []

        if auto_refer:
            for item in bundle:
                resource = item['resources'][0] if item['resources'] else None
                if not resource:
                    continue
                referral, created = ResourceReferral.objects.get_or_create(
                    patient=patient,
                    resource=resource,
                    defaults={
                        'referred_by': request.user,
                        'reason': item['reason'],
                    },
                )
                if created:
                    created_referrals.append(referral.id)

        serialized_bundle = [
            {
                'category': item['category'],
                'reason': item['reason'],
                'resources': CommunityResourceSerializer(item['resources'], many=True).data,
            }
            for item in bundle
        ]
        return Response(
            {
                'patient_id': patient.id,
                'recommendations': serialized_bundle,
                'auto_referrals_created': created_referrals,
            }
        )

    @action(detail=True, methods=['get'], url_path='journey')
    def patient_journey(self, request, pk=None):
        patient = self.get_object()
        active_admission = patient.admissions.filter(status=Admission.STATUS_ADMITTED).first()
        return Response(
            {
                'patient': PatientSerializer(patient).data,
                'latest_assessment': RiskAssessmentSerializer(patient.risk_assessments.first()).data
                if patient.risk_assessments.exists()
                else None,
                'latest_checkin': PatientCheckInSerializer(patient.checkins.first()).data
                if patient.checkins.exists()
                else None,
                'active_admission': AdmissionSerializer(active_admission).data if active_admission else None,
                'active_medication_orders': MedicationOrderSerializer(
                    patient.medication_orders.filter(status=MedicationOrder.STATUS_ACTIVE)[:5],
                    many=True,
                ).data,
                'pending_lab_orders': LabOrderSerializer(
                    patient.lab_orders.exclude(status=LabOrder.STATUS_COMPLETED).exclude(status=LabOrder.STATUS_CANCELLED)[:5],
                    many=True,
                ).data,
                'open_alerts': ClinicalAlertSerializer(patient.alerts.filter(resolved=False)[:5], many=True).data,
                'active_referrals': ResourceReferralSerializer(
                    patient.referrals.exclude(status=ResourceReferral.STATUS_COMPLETED)[:5],
                    many=True,
                ).data,
            }
        )


class AppointmentViewSet(viewsets.ModelViewSet):
    queryset = Appointment.objects.select_related('patient').all()
    serializer_class = AppointmentSerializer
    permission_classes = [ClinicalWritePermission]
    filter_backends = [OrderingFilter]
    ordering_fields = ['scheduled_at', 'created_at']
    ordering = ['scheduled_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.query_params.get('patient')
        status_value = self.request.query_params.get('status')
        date_from_raw = self.request.query_params.get('date_from')
        date_to_raw = self.request.query_params.get('date_to')

        if patient_id and patient_id.isdigit():
            queryset = queryset.filter(patient_id=int(patient_id))
        if status_value:
            queryset = queryset.filter(status=status_value)
        if date_from_raw:
            date_from, error = _parse_optional_date(date_from_raw, 'date_from')
            if error:
                return queryset.none()
            queryset = queryset.filter(scheduled_at__date__gte=date_from)
        if date_to_raw:
            date_to, error = _parse_optional_date(date_to_raw, 'date_to')
            if error:
                return queryset.none()
            queryset = queryset.filter(scheduled_at__date__lte=date_to)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class HospitalWardViewSet(viewsets.ModelViewSet):
    serializer_class = HospitalWardSerializer
    permission_classes = [InfrastructureCatalogPermission]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'code', 'specialty']
    ordering_fields = ['code', 'name', 'floor', 'capacity']
    ordering = ['code']

    def get_queryset(self):
        return HospitalWard.objects.annotate(
            occupied_beds=Count('beds', filter=Q(beds__status=Bed.STATUS_OCCUPIED))
        )


class BedViewSet(viewsets.ModelViewSet):
    queryset = Bed.objects.select_related('ward', 'current_patient').all()
    serializer_class = BedSerializer
    permission_classes = [InfrastructureCatalogPermission]
    filter_backends = [OrderingFilter]
    ordering_fields = ['ward__code', 'bed_number', 'status']
    ordering = ['ward__code', 'bed_number']

    def get_queryset(self):
        queryset = super().get_queryset()
        ward_id = self.request.query_params.get('ward')
        status_value = self.request.query_params.get('status')
        available_only = self.request.query_params.get('available_only')

        if ward_id and ward_id.isdigit():
            queryset = queryset.filter(ward_id=int(ward_id))
        if status_value:
            queryset = queryset.filter(status=status_value)
        if available_only == 'true':
            queryset = queryset.filter(status=Bed.STATUS_AVAILABLE)
        return queryset


class AdmissionViewSet(viewsets.ModelViewSet):
    queryset = Admission.objects.select_related('patient', 'bed__ward', 'admitted_by').all()
    serializer_class = AdmissionSerializer
    permission_classes = [ClinicalWritePermission]
    filter_backends = [OrderingFilter]
    ordering_fields = ['admitted_at', 'status', 'expected_discharge_date']
    ordering = ['-admitted_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.query_params.get('patient')
        status_value = self.request.query_params.get('status')
        active_only = self.request.query_params.get('active')

        if patient_id and patient_id.isdigit():
            queryset = queryset.filter(patient_id=int(patient_id))
        if status_value:
            queryset = queryset.filter(status=status_value)
        if active_only == 'true':
            queryset = queryset.filter(status=Admission.STATUS_ADMITTED)
        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        patient = serializer.validated_data['patient']
        bed = serializer.validated_data.get('bed')

        has_active_admission = Admission.objects.filter(
            patient=patient,
            status=Admission.STATUS_ADMITTED,
        ).exists()
        if has_active_admission:
            raise ValidationError({'patient': 'Patient already has an active admission.'})

        if bed:
            bed.refresh_from_db()
            if bed.status != Bed.STATUS_AVAILABLE:
                raise ValidationError({'bed': 'Selected bed is not available.'})

        admission = serializer.save(admitted_by=self.request.user)

        if bed:
            _assign_bed_to_patient(bed, patient)

        emit_domain_event(
            event_type='admission.created',
            source='admissions.perform_create',
            payload={
                'admission_id': admission.id,
                'patient_id': patient.id,
                'patient_age': patient.age,
                'bed_id': bed.id if bed else None,
                'ward_code': bed.ward.code if bed else '',
                'reason': admission.reason,
                'status': admission.status,
            },
        )

        return admission

    def perform_update(self, serializer):
        instance = serializer.instance
        next_bed = serializer.validated_data.get('bed', instance.bed)
        next_status = serializer.validated_data.get('status', instance.status)

        if next_bed != instance.bed:
            raise ValidationError({'bed': 'Use the transfer endpoint to change bed assignments.'})
        if next_status != instance.status and next_status in [Admission.STATUS_DISCHARGED, Admission.STATUS_TRANSFERRED]:
            raise ValidationError({'status': 'Use dedicated admission actions for discharge/transfer.'})
        serializer.save()

    @transaction.atomic
    def perform_destroy(self, instance):
        if instance.status == Admission.STATUS_ADMITTED and instance.bed_id:
            _set_bed_available(instance.bed)
        instance.delete()

    @transaction.atomic
    @action(detail=True, methods=['post'], url_path='transfer')
    def transfer(self, request, pk=None):
        admission = self.get_object()
        if admission.status != Admission.STATUS_ADMITTED:
            return Response({'detail': 'Only active admissions can be transferred.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = AdmissionTransferRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_bed = serializer.validated_data['bed']
        reason = serializer.validated_data.get('reason', '')

        if new_bed.id == admission.bed_id:
            return Response({'detail': 'Admission is already assigned to this bed.'}, status=status.HTTP_400_BAD_REQUEST)

        new_bed.refresh_from_db()
        if new_bed.status != Bed.STATUS_AVAILABLE:
            return Response({'detail': 'Target bed is not available.'}, status=status.HTTP_400_BAD_REQUEST)

        old_bed = admission.bed
        _assign_bed_to_patient(new_bed, admission.patient)
        _set_bed_available(old_bed)

        admission.bed = new_bed
        if reason:
            suffix = f"\nTransfer note: {reason}"
            admission.discharge_summary = f"{admission.discharge_summary}{suffix}".strip()
        admission.save(update_fields=['bed', 'discharge_summary'])

        emit_domain_event(
            event_type='admission.transferred',
            source='admissions.transfer',
            payload={
                'admission_id': admission.id,
                'patient_id': admission.patient_id,
                'patient_age': admission.patient.age,
                'from_bed_id': old_bed.id if old_bed else None,
                'to_bed_id': new_bed.id,
                'to_ward_code': new_bed.ward.code,
                'reason': reason,
            },
        )

        return Response(AdmissionSerializer(admission).data)

    @transaction.atomic
    @extend_schema(request=AdmissionDischargeRequestSerializer, responses={200: AdmissionSerializer})
    @action(detail=True, methods=['post'], url_path='discharge')
    def discharge(self, request, pk=None):
        admission = self.get_object()
        if admission.status != Admission.STATUS_ADMITTED:
            return Response({'detail': 'Admission is not active.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = AdmissionDischargeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        admission.status = Admission.STATUS_DISCHARGED
        admission.discharge_at = timezone.now()
        summary = serializer.validated_data.get('discharge_summary')
        if summary:
            admission.discharge_summary = summary
        admission.save(update_fields=['status', 'discharge_at', 'discharge_summary'])

        _set_bed_available(admission.bed)

        emit_domain_event(
            event_type='admission.discharged',
            source='admissions.discharge',
            payload={
                'admission_id': admission.id,
                'patient_id': admission.patient_id,
                'patient_age': admission.patient.age,
                'bed_id': admission.bed_id,
                'summary': admission.discharge_summary,
                'status': admission.status,
            },
        )

        return Response(AdmissionSerializer(admission).data)


class MedicationOrderViewSet(viewsets.ModelViewSet):
    queryset = MedicationOrder.objects.select_related('patient', 'admission', 'prescribed_by').all()
    serializer_class = MedicationOrderSerializer
    permission_classes = [ClinicalWritePermission]
    filter_backends = [OrderingFilter]
    ordering_fields = ['created_at', 'status', 'start_at']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.query_params.get('patient')
        admission_id = self.request.query_params.get('admission')
        status_value = self.request.query_params.get('status')

        if patient_id and patient_id.isdigit():
            queryset = queryset.filter(patient_id=int(patient_id))
        if admission_id and admission_id.isdigit():
            queryset = queryset.filter(admission_id=int(admission_id))
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    def perform_create(self, serializer):
        serializer.save(prescribed_by=self.request.user)

    @extend_schema(request=MedicationStatusUpdateSerializer, responses={200: MedicationOrderSerializer})
    @action(detail=True, methods=['post'], url_path='mark-status')
    def mark_status(self, request, pk=None):
        order = self.get_object()
        serializer = MedicationStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']
        notes = serializer.validated_data.get('notes', '')

        order.status = new_status
        if new_status in [MedicationOrder.STATUS_COMPLETED, MedicationOrder.STATUS_STOPPED] and not order.end_at:
            order.end_at = timezone.now()
        if notes:
            order.instructions = f"{order.instructions}\nStatus note: {notes}".strip()
        order.save(update_fields=['status', 'end_at', 'instructions'])
        return Response(MedicationOrderSerializer(order).data)


class LabOrderViewSet(viewsets.ModelViewSet):
    queryset = LabOrder.objects.select_related('patient', 'admission', 'ordered_by').all()
    serializer_class = LabOrderSerializer
    permission_classes = [ClinicalWritePermission]
    filter_backends = [OrderingFilter]
    ordering_fields = ['ordered_at', 'status', 'priority']
    ordering = ['-ordered_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.query_params.get('patient')
        admission_id = self.request.query_params.get('admission')
        status_value = self.request.query_params.get('status')
        priority = self.request.query_params.get('priority')

        if patient_id and patient_id.isdigit():
            queryset = queryset.filter(patient_id=int(patient_id))
        if admission_id and admission_id.isdigit():
            queryset = queryset.filter(admission_id=int(admission_id))
        if status_value:
            queryset = queryset.filter(status=status_value)
        if priority:
            queryset = queryset.filter(priority=priority)
        return queryset

    def perform_create(self, serializer):
        serializer.save(ordered_by=self.request.user)

    @action(detail=True, methods=['post'], url_path='start')
    def start(self, request, pk=None):
        order = self.get_object()
        if order.status not in [LabOrder.STATUS_ORDERED, LabOrder.STATUS_IN_PROGRESS]:
            return Response({'detail': 'Only ordered lab requests can be started.'}, status=status.HTTP_400_BAD_REQUEST)
        if not order.sample_collected_at:
            order.sample_collected_at = timezone.now()
        order.status = LabOrder.STATUS_IN_PROGRESS
        order.save(update_fields=['status', 'sample_collected_at'])
        return Response(LabOrderSerializer(order).data)

    @extend_schema(request=LabOrderCompleteSerializer, responses={200: LabOrderSerializer})
    @action(detail=True, methods=['post'], url_path='complete')
    def complete(self, request, pk=None):
        order = self.get_object()
        if order.status == LabOrder.STATUS_CANCELLED:
            return Response({'detail': 'Cancelled lab requests cannot be completed.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = LabOrderCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order.status = LabOrder.STATUS_COMPLETED
        order.completed_at = timezone.now()
        order.result_value = serializer.validated_data.get('result_value', order.result_value)
        order.result_summary = serializer.validated_data.get('result_summary', order.result_summary)
        if not order.sample_collected_at:
            order.sample_collected_at = timezone.now()
        order.save(
            update_fields=[
                'status',
                'completed_at',
                'result_value',
                'result_summary',
                'sample_collected_at',
            ]
        )

        emit_domain_event(
            event_type='lab_order.completed',
            source='lab_orders.complete',
            payload={
                'lab_order_id': order.id,
                'patient_id': order.patient_id,
                'patient_age': order.patient.age,
                'priority': order.priority,
                'result_value': order.result_value,
                'result_summary': order.result_summary,
                'status': order.status,
            },
        )
        return Response(LabOrderSerializer(order).data)


class PatientCheckInViewSet(viewsets.ModelViewSet):
    queryset = PatientCheckIn.objects.select_related('patient', 'submitted_by').all()
    serializer_class = PatientCheckInSerializer
    permission_classes = [CommunityWorkflowPermission]
    filter_backends = [OrderingFilter]
    ordering_fields = ['created_at', 'symptom_severity', 'mood_score']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.query_params.get('patient')
        urgent_only = self.request.query_params.get('urgent')

        if patient_id and patient_id.isdigit():
            queryset = queryset.filter(patient_id=int(patient_id))
        if urgent_only == 'true':
            queryset = queryset.filter(
                Q(symptom_severity__gte=8)
                | Q(oxygen_saturation__lt=92)
                | Q(systolic_bp__gte=180)
                | Q(heart_rate__gte=130)
                | (Q(mood_score__lte=2) & Q(medication_taken=False))
            )
        return queryset

    @extend_schema(request=PatientCheckInSerializer, responses={201: CheckInResponseSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        checkin = serializer.save(submitted_by=request.user)

        alert_id = None
        alert_payload = _checkin_alert_payload(checkin)
        if alert_payload:
            alert = ClinicalAlert.objects.create(
                patient=checkin.patient,
                severity=alert_payload['severity'],
                title=alert_payload['title'],
                message=alert_payload['message'],
            )
            alert_id = alert.id

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

        return Response(
            {
                'checkin': PatientCheckInSerializer(checkin).data,
                'alert_created': bool(alert_id),
                'alert_id': alert_id,
            },
            status=status.HTTP_201_CREATED,
        )


class CommunityResourceViewSet(viewsets.ModelViewSet):
    queryset = CommunityResource.objects.all()
    serializer_class = CommunityResourceSerializer
    permission_classes = [CommunityCatalogPermission]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'description', 'eligibility', 'location']
    ordering_fields = ['name', 'category', 'created_at']
    ordering = ['category', 'name']

    def get_queryset(self):
        queryset = super().get_queryset()
        category = self.request.query_params.get('category')
        active = self.request.query_params.get('active')
        if category:
            queryset = queryset.filter(category=category)
        if active in {'true', 'false'}:
            queryset = queryset.filter(active=active == 'true')
        return queryset


class ResourceReferralViewSet(viewsets.ModelViewSet):
    queryset = ResourceReferral.objects.select_related('patient', 'resource', 'referred_by').all()
    serializer_class = ResourceReferralSerializer
    permission_classes = [CommunityWorkflowPermission]
    filter_backends = [OrderingFilter]
    ordering_fields = ['created_at', 'status', 'follow_up_date']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.query_params.get('patient')
        status_value = self.request.query_params.get('status')
        if patient_id and patient_id.isdigit():
            queryset = queryset.filter(patient_id=int(patient_id))
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    def perform_create(self, serializer):
        serializer.save(referred_by=self.request.user)


class WorkflowRuleViewSet(viewsets.ModelViewSet):
    queryset = WorkflowRule.objects.select_related('created_by').all()
    serializer_class = WorkflowRuleSerializer
    permission_classes = [WorkflowRulePermission]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'description', 'event_type', 'action_type']
    ordering_fields = ['priority', 'name', 'created_at', 'updated_at']
    ordering = ['priority', 'name']

    def get_queryset(self):
        queryset = super().get_queryset()
        event_type = self.request.query_params.get('event_type')
        active = self.request.query_params.get('active')
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        if active in {'true', 'false'}:
            queryset = queryset.filter(active=active == 'true')
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class DomainEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DomainEvent.objects.all()
    serializer_class = DomainEventSerializer
    permission_classes = [WorkflowEventPermission]
    filter_backends = [OrderingFilter]
    ordering_fields = ['occurred_at', 'processed_at', 'attempts', 'status']
    ordering = ['-occurred_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        event_type = self.request.query_params.get('event_type')
        status_value = self.request.query_params.get('status')
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    @extend_schema(
        request=ProcessDomainEventsRequestSerializer,
        responses={200: ProcessDomainEventsResponseSerializer},
    )
    @action(detail=False, methods=['post'], url_path='process-pending')
    def process_pending(self, request):
        serializer = ProcessDomainEventsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = process_pending_domain_events(
            limit=serializer.validated_data['limit'],
            include_failed=serializer.validated_data['include_failed'],
            max_attempts=serializer.validated_data['max_attempts'],
        )
        return Response(result, status=status.HTTP_200_OK)


class RiskAssessmentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RiskAssessment.objects.select_related('patient', 'assessed_by').all()
    serializer_class = RiskAssessmentSerializer
    permission_classes = [HasCareflowRole]
    filter_backends = [OrderingFilter]
    ordering_fields = ['created_at', 'risk_score']
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        patient_id = self.request.query_params.get('patient')
        risk_level = self.request.query_params.get('risk_level')
        date_from_raw = self.request.query_params.get('date_from')
        date_to_raw = self.request.query_params.get('date_to')

        if patient_id and patient_id.isdigit():
            queryset = queryset.filter(patient_id=int(patient_id))
        if risk_level:
            queryset = queryset.filter(risk_level=risk_level)
        if date_from_raw:
            date_from, error = _parse_optional_date(date_from_raw, 'date_from')
            if error:
                return queryset.none()
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to_raw:
            date_to, error = _parse_optional_date(date_to_raw, 'date_to')
            if error:
                return queryset.none()
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset


class ClinicalAlertViewSet(viewsets.ModelViewSet):
    queryset = ClinicalAlert.objects.select_related('patient', 'assessment').all()
    serializer_class = ClinicalAlertSerializer
    permission_classes = [AlertPermission]
    http_method_names = ['get', 'patch', 'head', 'options']
    filter_backends = [OrderingFilter]
    ordering_fields = ['created_at', 'severity']
    ordering = ['resolved', '-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        resolved = self.request.query_params.get('resolved')
        severity = self.request.query_params.get('severity')
        if resolved in {'true', 'false'}:
            queryset = queryset.filter(resolved=resolved == 'true')
        if severity:
            queryset = queryset.filter(severity=severity)
        return queryset

    def perform_update(self, serializer):
        was_resolved = serializer.instance.resolved
        alert = serializer.save()
        if not was_resolved and alert.resolved and not alert.resolved_at:
            alert.resolved_at = timezone.now()
            alert.save(update_fields=['resolved_at'])
        elif was_resolved and not alert.resolved and alert.resolved_at:
            alert.resolved_at = None
            alert.save(update_fields=['resolved_at'])


class PredictHealthRiskView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=TriageAssessmentRequestSerializer,
        responses={200: RiskPredictionSerializer},
    )
    def post(self, request):
        serializer = TriageAssessmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scored = _score_health_risk(serializer.validated_data)
        return Response(scored)


class CurrentUserProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: CurrentUserProfileSerializer})
    def get(self, request):
        roles = list(request.user.groups.values_list('name', flat=True))
        return Response(
            {
                'id': request.user.id,
                'username': request.user.username,
                'is_superuser': request.user.is_superuser,
                'roles': roles,
            }
        )


class TriageAssessmentView(APIView):
    permission_classes = [ClinicianAdminOnly]

    @extend_schema(
        request=TriageAssessmentRequestSerializer,
        responses={201: TriageAssessmentResponseSerializer},
    )
    def post(self, request):
        serializer = TriageAssessmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        scored = _score_health_risk(validated)

        assessment = RiskAssessment.objects.create(
            patient=validated.get('patient'),
            assessed_by=request.user,
            age=validated['age'],
            bmi=validated['bmi'],
            blood_pressure=validated['blood_pressure'],
            cholesterol=validated['cholesterol'],
            smoker=validated['smoker'],
            exercise_minutes=validated['exercise_minutes'],
            chronic_conditions=validated['chronic_conditions'],
            risk_score=scored['risk_score'],
            risk_level=scored['risk_level'],
            recommended_action=scored['recommended_action'],
            key_drivers=scored['key_drivers'],
        )

        alert_id = None
        if assessment.patient and assessment.risk_level in [RiskAssessment.LEVEL_HIGH, RiskAssessment.LEVEL_CRITICAL]:
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

        return Response(
            {
                'assessment': RiskAssessmentSerializer(assessment).data,
                'alert_created': bool(alert_id),
                'alert_id': alert_id,
            },
            status=status.HTTP_201_CREATED,
        )


class CareAnalyticsView(APIView):
    permission_classes = [HasCareflowRole]

    @extend_schema(responses={200: AnalyticsOverviewSerializer})
    def get(self, request):
        now = timezone.now()
        start_date = now - timedelta(days=30)
        recent_assessments = RiskAssessment.objects.filter(created_at__gte=start_date)

        distribution = {'low': 0, 'medium': 0, 'high': 0, 'critical': 0}
        for item in recent_assessments.values('risk_level').annotate(total=Count('id')):
            key = item['risk_level'].lower()
            if key in distribution:
                distribution[key] = item['total']

        top_diagnoses = (
            Patient.objects.exclude(diagnosis__isnull=True)
            .exclude(diagnosis__exact='')
            .values('diagnosis')
            .annotate(total=Count('id'))
            .order_by('-total')[:5]
        )

        trend = (
            recent_assessments.annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(total=Count('id'))
            .order_by('day')
        )

        return Response(
            {
                'generated_at': now.isoformat(),
                'kpis': {
                    'patients_total': Patient.objects.count(),
                    'upcoming_appointments': Appointment.objects.filter(
                        status=Appointment.STATUS_SCHEDULED,
                        scheduled_at__gte=now,
                    ).count(),
                    'assessments_last_30_days': recent_assessments.count(),
                    'open_alerts': ClinicalAlert.objects.filter(resolved=False).count(),
                },
                'risk_distribution_last_30_days': distribution,
                'top_diagnoses': [
                    {'diagnosis': item['diagnosis'], 'count': item['total']}
                    for item in top_diagnoses
                ],
                'assessment_trend': [
                    {'date': item['day'].isoformat(), 'count': item['total']}
                    for item in trend
                ],
            }
        )


class ImpactAnalyticsView(APIView):
    permission_classes = [HasCareflowRole]

    @extend_schema(responses={200: ImpactOverviewSerializer})
    def get(self, request):
        now = timezone.now()
        start_30_days = now - timedelta(days=30)
        start_7_days = now - timedelta(days=7)

        recent_referrals = ResourceReferral.objects.filter(created_at__gte=start_30_days)
        referral_status = {
            item['status']: item['count']
            for item in recent_referrals.values('status').annotate(count=Count('id'))
        }

        category_breakdown = {
            item['resource__category']: item['count']
            for item in recent_referrals.values('resource__category').annotate(count=Count('id'))
        }

        urgent_checkins = PatientCheckIn.objects.filter(created_at__gte=start_7_days).filter(
            Q(symptom_severity__gte=8)
            | Q(oxygen_saturation__lt=92)
            | Q(systolic_bp__gte=180)
            | Q(heart_rate__gte=130)
            | (Q(mood_score__lte=2) & Q(medication_taken=False))
        )

        return Response(
            {
                'generated_at': now.isoformat(),
                'kpis': {
                    'active_community_resources': CommunityResource.objects.filter(active=True).count(),
                    'referrals_last_30_days': recent_referrals.count(),
                    'completed_referrals': recent_referrals.filter(status=ResourceReferral.STATUS_COMPLETED).count(),
                    'urgent_checkins_last_7_days': urgent_checkins.count(),
                },
                'referral_status_breakdown': referral_status,
                'resource_category_breakdown': category_breakdown,
            }
        )


class HospitalFlowAnalyticsView(APIView):
    permission_classes = [HasCareflowRole]

    @extend_schema(responses={200: HospitalFlowOverviewSerializer})
    def get(self, request):
        now = timezone.now()
        last_7_days = now - timedelta(days=7)

        active_admissions = Admission.objects.filter(status=Admission.STATUS_ADMITTED)
        total_beds = Bed.objects.exclude(status=Bed.STATUS_MAINTENANCE).count()
        occupied_beds = Bed.objects.filter(status=Bed.STATUS_OCCUPIED).count()
        available_beds = Bed.objects.filter(status=Bed.STATUS_AVAILABLE).count()
        occupancy_rate = round((occupied_beds / total_beds) * 100, 2) if total_beds else 0.0

        admissions_by_status = {
            row['status']: row['count']
            for row in Admission.objects.values('status').annotate(count=Count('id'))
        }
        labs_by_status = {
            row['status']: row['count']
            for row in LabOrder.objects.values('status').annotate(count=Count('id'))
        }

        return Response(
            {
                'generated_at': now.isoformat(),
                'kpis': {
                    'active_admissions': active_admissions.count(),
                    'bed_occupancy_rate': occupancy_rate,
                    'available_beds': available_beds,
                    'active_medication_orders': MedicationOrder.objects.filter(status=MedicationOrder.STATUS_ACTIVE).count(),
                    'pending_lab_orders': LabOrder.objects.filter(
                        status__in=[LabOrder.STATUS_ORDERED, LabOrder.STATUS_IN_PROGRESS]
                    ).count(),
                    'discharges_last_7_days': Admission.objects.filter(
                        status=Admission.STATUS_DISCHARGED,
                        discharge_at__gte=last_7_days,
                    ).count(),
                },
                'admissions_by_status': admissions_by_status,
                'labs_by_status': labs_by_status,
            }
        )


class AssessmentExportCSVView(APIView):
    permission_classes = [HasCareflowRole]

    @extend_schema(responses={200: OpenApiResponse(description='CSV export of risk assessments')})
    def get(self, request):
        queryset = RiskAssessment.objects.select_related('patient', 'assessed_by').all()

        patient_id = request.query_params.get('patient')
        risk_level = request.query_params.get('risk_level')
        date_from_raw = request.query_params.get('date_from')
        date_to_raw = request.query_params.get('date_to')

        if patient_id and patient_id.isdigit():
            queryset = queryset.filter(patient_id=int(patient_id))
        if risk_level:
            queryset = queryset.filter(risk_level=risk_level)
        if date_from_raw:
            date_from, error = _parse_optional_date(date_from_raw, 'date_from')
            if error:
                return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to_raw:
            date_to, error = _parse_optional_date(date_to_raw, 'date_to')
            if error:
                return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(created_at__date__lte=date_to)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="risk_assessments.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                'id',
                'patient_id',
                'patient_name',
                'assessed_by',
                'risk_level',
                'risk_score',
                'recommended_action',
                'created_at',
            ]
        )

        for item in queryset.iterator():
            writer.writerow(
                [
                    item.id,
                    item.patient_id,
                    item.patient.name if item.patient else '',
                    item.assessed_by.username if item.assessed_by else '',
                    item.risk_level,
                    item.risk_score,
                    item.recommended_action,
                    item.created_at.isoformat(),
                ]
            )
        return response


def portfolio_home(request):
    latest_assessment = RiskAssessment.objects.select_related('patient').first()
    operational_beds = Bed.objects.exclude(status=Bed.STATUS_MAINTENANCE).count()
    occupied_beds = Bed.objects.filter(status=Bed.STATUS_OCCUPIED).count()
    context = {
        'patients_total': Patient.objects.count(),
        'assessments_total': RiskAssessment.objects.count(),
        'open_alerts': ClinicalAlert.objects.filter(resolved=False).count(),
        'community_resources': CommunityResource.objects.filter(active=True).count(),
        'referrals_total': ResourceReferral.objects.count(),
        'active_admissions': Admission.objects.filter(status=Admission.STATUS_ADMITTED).count(),
        'pending_labs': LabOrder.objects.filter(status__in=[LabOrder.STATUS_ORDERED, LabOrder.STATUS_IN_PROGRESS]).count(),
        'active_medications': MedicationOrder.objects.filter(status=MedicationOrder.STATUS_ACTIVE).count(),
        'bed_occupancy_rate': round((occupied_beds / operational_beds) * 100, 2) if operational_beds else 0.0,
        'urgent_checkins': PatientCheckIn.objects.filter(
            Q(symptom_severity__gte=8)
            | Q(oxygen_saturation__lt=92)
            | Q(systolic_bp__gte=180)
            | Q(heart_rate__gte=130)
            | (Q(mood_score__lte=2) & Q(medication_taken=False))
        ).count(),
        'latest_assessment': latest_assessment,
        'deploy_timestamp': timezone.now(),
    }
    return render(request, 'portfolio_home.html', context)


def health_check(_request):
    return JsonResponse({"status": "ok", "service": "careflow-api"})


def readiness_check(_request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return JsonResponse({'status': 'ready', 'database': 'ok'})
    except Exception as exc:
        return JsonResponse({'status': 'not_ready', 'database': 'unavailable', 'error': str(exc)}, status=503)
