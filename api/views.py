import csv
import logging
from datetime import timedelta

from django.core.cache import cache
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .audit import record_audit_event
from .throttling import ResilientScopedRateThrottle
from .filters import (
    AdmissionFilterSet,
    AppointmentFilterSet,
    BedFilterSet,
    ClinicalAlertFilterSet,
    CommunityResourceFilterSet,
    DomainEventFilterSet,
    LabOrderFilterSet,
    MedicationOrderFilterSet,
    PatientCheckInFilterSet,
    PatientFilterSet,
    ResourceReferralFilterSet,
    RiskAssessmentFilterSet,
    WorkflowRuleFilterSet,
)
from .models import (
    Admission,
    Appointment,
    AuditLog,
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
    MedicationOrderPermission,
    PatientCheckInPermission,
    WorkflowEventPermission,
    WorkflowRulePermission,
)
from .services import admissions as admission_services
from .services import lab_orders as lab_order_services
from .services import medications as medication_services
from .services.assessments import record_triage_assessment
from .services.care_plans import build_care_plan
from .services.alerts import sync_alert_resolution_timestamp
from .services.checkins import submit_checkin
from .services.recommendations import create_auto_referrals, resource_recommendation_bundle
from .services.triage import score_health_risk
from .services.workflow_engine import process_pending_domain_events
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
    LogoutRequestSerializer,
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

logger = logging.getLogger('careflow.app')


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """JWT login, with a dedicated tight throttle scope.

    The default blanket `anon` throttle (60/minute) is shared across every
    unauthenticated endpoint, which is too permissive for a credential-entry
    endpoint specifically — it is the classic brute-force/credential-stuffing
    target. `throttle_scope`/`ScopedRateThrottle` gives this endpoint its own
    independent budget (`DRF_THROTTLE_TOKEN`, see `careflow/settings.py`)
    without affecting the general anonymous rate used elsewhere.
    """

    throttle_classes = [ResilientScopedRateThrottle]
    throttle_scope = 'token_obtain'


class ThrottledTokenRefreshView(TokenRefreshView):
    """Token refresh, throttled the same way as token obtain (see above)."""

    throttle_classes = [ResilientScopedRateThrottle]
    throttle_scope = 'token_obtain'


class PatientViewSet(viewsets.ModelViewSet):
    queryset = Patient.objects.all().order_by('-created_at')
    serializer_class = PatientSerializer
    permission_classes = [ClinicalWritePermission]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = PatientFilterSet
    search_fields = ['name', 'diagnosis', 'blood_type']
    ordering_fields = ['name', 'age', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        record_audit_event(
            request,
            action=AuditLog.ACTION_VIEW,
            resource_type='Patient',
            resource_id=kwargs.get('pk'),
        )
        return response

    def perform_create(self, serializer):
        patient = serializer.save(created_by=self.request.user)
        record_audit_event(
            self.request, action=AuditLog.ACTION_CREATE, resource_type='Patient', resource_id=patient.id
        )

    def perform_update(self, serializer):
        patient = serializer.save()
        record_audit_event(
            self.request, action=AuditLog.ACTION_UPDATE, resource_type='Patient', resource_id=patient.id
        )

    def perform_destroy(self, instance):
        patient_id = instance.id
        instance.delete()
        record_audit_event(
            self.request, action=AuditLog.ACTION_DELETE, resource_type='Patient', resource_id=patient_id
        )

    @action(detail=True, methods=['get'], url_path='care-plan')
    def care_plan(self, request, pk=None):
        patient = self.get_object()
        plan = build_care_plan(patient)
        return Response(
            {
                'patient': PatientSerializer(patient).data,
                'latest_assessment': RiskAssessmentSerializer(plan['latest_assessment']).data
                if plan['latest_assessment']
                else None,
                'upcoming_appointments': AppointmentSerializer(plan['upcoming_appointments'], many=True).data,
                'next_actions': plan['next_actions'],
            }
        )

    @extend_schema(responses={200: CommunityRecommendationResponseSerializer})
    @action(detail=True, methods=['get'], url_path='community-recommendations')
    def community_recommendations(self, request, pk=None):
        patient = self.get_object()
        bundle = resource_recommendation_bundle(patient)
        auto_refer = request.query_params.get('auto_refer') == 'true'
        created_referrals = (
            create_auto_referrals(patient, bundle, request.user) if auto_refer else []
        )

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
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = AppointmentFilterSet
    ordering_fields = ['scheduled_at', 'created_at']
    ordering = ['scheduled_at']

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
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = BedFilterSet
    ordering_fields = ['ward__code', 'bed_number', 'status']
    ordering = ['ward__code', 'bed_number']


class AdmissionViewSet(viewsets.ModelViewSet):
    queryset = Admission.objects.select_related('patient', 'bed__ward', 'admitted_by').all()
    serializer_class = AdmissionSerializer
    permission_classes = [ClinicalWritePermission]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = AdmissionFilterSet
    ordering_fields = ['admitted_at', 'status', 'expected_discharge_date']
    ordering = ['-admitted_at']

    def perform_create(self, serializer):
        admission = admission_services.admit_patient(serializer, admitted_by=self.request.user)
        record_audit_event(
            self.request, action=AuditLog.ACTION_CREATE, resource_type='Admission', resource_id=admission.id
        )

    def perform_update(self, serializer):
        admission_services.validate_admission_update(serializer.instance, serializer.validated_data)
        admission = serializer.save()
        record_audit_event(
            self.request, action=AuditLog.ACTION_UPDATE, resource_type='Admission', resource_id=admission.id
        )

    @transaction.atomic
    def perform_destroy(self, instance):
        admission_id = instance.id
        admission_services.release_admission_bed_if_active(instance)
        instance.delete()
        record_audit_event(
            self.request, action=AuditLog.ACTION_DELETE, resource_type='Admission', resource_id=admission_id
        )

    @action(detail=True, methods=['post'], url_path='transfer')
    def transfer(self, request, pk=None):
        admission = self.get_object()
        serializer = AdmissionTransferRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        admission = admission_services.transfer_admission(
            admission,
            serializer.validated_data['bed'],
            serializer.validated_data.get('reason', ''),
        )
        record_audit_event(
            self.request,
            action=AuditLog.ACTION_UPDATE,
            resource_type='Admission',
            resource_id=admission.id,
            detail='transfer',
        )
        return Response(AdmissionSerializer(admission).data)

    @extend_schema(request=AdmissionDischargeRequestSerializer, responses={200: AdmissionSerializer})
    @action(detail=True, methods=['post'], url_path='discharge')
    def discharge(self, request, pk=None):
        admission = self.get_object()
        serializer = AdmissionDischargeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        admission = admission_services.discharge_admission(
            admission, serializer.validated_data.get('discharge_summary', '')
        )
        record_audit_event(
            self.request,
            action=AuditLog.ACTION_UPDATE,
            resource_type='Admission',
            resource_id=admission.id,
            detail='discharge',
        )
        return Response(AdmissionSerializer(admission).data)


class MedicationOrderViewSet(viewsets.ModelViewSet):
    queryset = MedicationOrder.objects.select_related('patient', 'admission', 'prescribed_by').all()
    serializer_class = MedicationOrderSerializer
    permission_classes = [MedicationOrderPermission]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = MedicationOrderFilterSet
    ordering_fields = ['created_at', 'status', 'start_at']
    ordering = ['-created_at']

    def perform_create(self, serializer):
        order = serializer.save(prescribed_by=self.request.user)
        record_audit_event(
            self.request, action=AuditLog.ACTION_CREATE, resource_type='MedicationOrder', resource_id=order.id
        )

    def perform_update(self, serializer):
        order = serializer.save()
        record_audit_event(
            self.request, action=AuditLog.ACTION_UPDATE, resource_type='MedicationOrder', resource_id=order.id
        )

    def perform_destroy(self, instance):
        order_id = instance.id
        instance.delete()
        record_audit_event(
            self.request, action=AuditLog.ACTION_DELETE, resource_type='MedicationOrder', resource_id=order_id
        )

    @extend_schema(request=MedicationStatusUpdateSerializer, responses={200: MedicationOrderSerializer})
    @action(detail=True, methods=['post'], url_path='mark-status')
    def mark_status(self, request, pk=None):
        order = self.get_object()
        serializer = MedicationStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = medication_services.mark_medication_order_status(
            order,
            serializer.validated_data['status'],
            serializer.validated_data.get('notes', ''),
        )
        record_audit_event(
            self.request,
            action=AuditLog.ACTION_UPDATE,
            resource_type='MedicationOrder',
            resource_id=order.id,
            detail='status change via mark-status',
        )
        return Response(MedicationOrderSerializer(order).data)


class LabOrderViewSet(viewsets.ModelViewSet):
    queryset = LabOrder.objects.select_related('patient', 'admission', 'ordered_by').all()
    serializer_class = LabOrderSerializer
    permission_classes = [ClinicalWritePermission]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = LabOrderFilterSet
    ordering_fields = ['ordered_at', 'status', 'priority']
    ordering = ['-ordered_at']

    def perform_create(self, serializer):
        serializer.save(ordered_by=self.request.user)

    @action(detail=True, methods=['post'], url_path='start')
    def start(self, request, pk=None):
        order = self.get_object()
        order = lab_order_services.start_lab_order(order)
        return Response(LabOrderSerializer(order).data)

    @extend_schema(request=LabOrderCompleteSerializer, responses={200: LabOrderSerializer})
    @action(detail=True, methods=['post'], url_path='complete')
    def complete(self, request, pk=None):
        order = self.get_object()
        serializer = LabOrderCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = lab_order_services.complete_lab_order(
            order,
            serializer.validated_data.get('result_value', ''),
            serializer.validated_data.get('result_summary', ''),
        )
        return Response(LabOrderSerializer(order).data)


class PatientCheckInViewSet(viewsets.ModelViewSet):
    queryset = PatientCheckIn.objects.select_related('patient', 'submitted_by').all()
    serializer_class = PatientCheckInSerializer
    permission_classes = [PatientCheckInPermission]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = PatientCheckInFilterSet
    ordering_fields = ['created_at', 'symptom_severity', 'mood_score']
    ordering = ['-created_at']

    @extend_schema(request=PatientCheckInSerializer, responses={201: CheckInResponseSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = submit_checkin(serializer, submitted_by=request.user)

        return Response(
            {
                'checkin': PatientCheckInSerializer(result['checkin']).data,
                'alert_created': result['alert_created'],
                'alert_id': result['alert_id'],
            },
            status=status.HTTP_201_CREATED,
        )


class CommunityResourceViewSet(viewsets.ModelViewSet):
    queryset = CommunityResource.objects.all()
    serializer_class = CommunityResourceSerializer
    permission_classes = [CommunityCatalogPermission]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = CommunityResourceFilterSet
    search_fields = ['name', 'description', 'eligibility', 'location']
    ordering_fields = ['name', 'category', 'created_at']
    ordering = ['category', 'name']


class ResourceReferralViewSet(viewsets.ModelViewSet):
    queryset = ResourceReferral.objects.select_related('patient', 'resource', 'referred_by').all()
    serializer_class = ResourceReferralSerializer
    permission_classes = [CommunityWorkflowPermission]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ResourceReferralFilterSet
    ordering_fields = ['created_at', 'status', 'follow_up_date']
    ordering = ['-created_at']

    def perform_create(self, serializer):
        serializer.save(referred_by=self.request.user)


class WorkflowRuleViewSet(viewsets.ModelViewSet):
    queryset = WorkflowRule.objects.select_related('created_by').all()
    serializer_class = WorkflowRuleSerializer
    permission_classes = [WorkflowRulePermission]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = WorkflowRuleFilterSet
    search_fields = ['name', 'description', 'event_type', 'action_type']
    ordering_fields = ['priority', 'name', 'created_at', 'updated_at']
    ordering = ['priority', 'name']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class DomainEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DomainEvent.objects.all()
    serializer_class = DomainEventSerializer
    permission_classes = [WorkflowEventPermission]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = DomainEventFilterSet
    ordering_fields = ['occurred_at', 'processed_at', 'attempts', 'status']
    ordering = ['-occurred_at']

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
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = RiskAssessmentFilterSet
    ordering_fields = ['created_at', 'risk_score']
    ordering = ['-created_at']


class ClinicalAlertViewSet(viewsets.ModelViewSet):
    queryset = ClinicalAlert.objects.select_related('patient', 'assessment').all()
    serializer_class = ClinicalAlertSerializer
    permission_classes = [AlertPermission]
    http_method_names = ['get', 'patch', 'head', 'options']
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ClinicalAlertFilterSet
    ordering_fields = ['created_at', 'severity']
    ordering = ['resolved', '-created_at']

    def perform_update(self, serializer):
        was_resolved = serializer.instance.resolved
        alert = serializer.save()
        sync_alert_resolution_timestamp(alert, was_resolved)


class PredictHealthRiskView(APIView):
    """Public demo scoring endpoint.

    Deliberately `AllowAny` (documented in README) so visitors can try the
    triage model without an account. Because it is unauthenticated and
    compute-bearing, it is a classic scraping/abuse target, so it carries
    its own tighter scoped throttle rather than relying solely on the
    blanket anonymous rate (see `DRF_THROTTLE_PREDICT` / `PREDICT_HEALTH_RISK`
    scope in `careflow/settings.py`).
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [ResilientScopedRateThrottle]
    throttle_scope = 'predict_health_risk'

    @extend_schema(
        request=TriageAssessmentRequestSerializer,
        responses={200: RiskPredictionSerializer},
    )
    def post(self, request):
        serializer = TriageAssessmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scored = score_health_risk(serializer.validated_data)
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


class LogoutView(APIView):
    """Revoke a refresh token, closing the gap where JWTs could only expire.

    Without this endpoint, a stolen or leaked refresh token remains valid
    until its natural expiry (1 day, `SIMPLE_JWT['REFRESH_TOKEN_LIFETIME']`)
    with no way to force it invalid sooner — a real security gap for a
    healthcare-adjacent API. This blacklists the *refresh* token via
    `rest_framework_simplejwt.token_blacklist`; the short-lived access token
    (30 minutes) is left to expire naturally, which is the standard
    SimpleJWT blacklist pattern (blacklisting every access token would
    require checking the blacklist on every single authenticated request).
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=LogoutRequestSerializer,
        responses={205: OpenApiResponse(description='Refresh token blacklisted.')},
    )
    def post(self, request):
        serializer = LogoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data['refresh'])
            token.blacklist()
        except TokenError as exc:
            raise ValidationError({'refresh': f'Invalid or already-invalidated token: {exc}'})

        logger.info('user_logout', extra={'user': request.user.username})
        return Response(status=status.HTTP_205_RESET_CONTENT)


class TriageAssessmentView(APIView):
    permission_classes = [ClinicianAdminOnly]

    @extend_schema(
        request=TriageAssessmentRequestSerializer,
        responses={201: TriageAssessmentResponseSerializer},
    )
    def post(self, request):
        serializer = TriageAssessmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = record_triage_assessment(serializer.validated_data, assessed_by=request.user)

        return Response(
            {
                'assessment': RiskAssessmentSerializer(result['assessment']).data,
                'alert_created': result['alert_created'],
                'alert_id': result['alert_id'],
            },
            status=status.HTTP_201_CREATED,
        )


class CareAnalyticsView(APIView):
    permission_classes = [HasCareflowRole]

    #: Short-TTL cache key for this endpoint's aggregate payload. See
    #: `careflow/settings.py::ANALYTICS_CACHE_TTL_SECONDS` for the
    #: rationale (PERF-04: these three analytics endpoints previously
    #: recomputed every aggregate query from scratch on every request).
    CACHE_KEY = 'careflow:analytics:overview'

    @extend_schema(responses={200: AnalyticsOverviewSerializer})
    def get(self, request):
        cached_payload = cache.get(self.CACHE_KEY)
        if cached_payload is not None:
            return Response(cached_payload)

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

        payload = {
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
        cache.set(self.CACHE_KEY, payload, settings.ANALYTICS_CACHE_TTL_SECONDS)
        return Response(payload)


class ImpactAnalyticsView(APIView):
    permission_classes = [HasCareflowRole]

    CACHE_KEY = 'careflow:analytics:impact'

    @extend_schema(responses={200: ImpactOverviewSerializer})
    def get(self, request):
        cached_payload = cache.get(self.CACHE_KEY)
        if cached_payload is not None:
            return Response(cached_payload)

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

        urgent_checkins = PatientCheckIn.objects.filter(created_at__gte=start_7_days).urgent()

        payload = {
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
        cache.set(self.CACHE_KEY, payload, settings.ANALYTICS_CACHE_TTL_SECONDS)
        return Response(payload)


class HospitalFlowAnalyticsView(APIView):
    permission_classes = [HasCareflowRole]

    CACHE_KEY = 'careflow:analytics:hospital-flow'

    @extend_schema(responses={200: HospitalFlowOverviewSerializer})
    def get(self, request):
        cached_payload = cache.get(self.CACHE_KEY)
        if cached_payload is not None:
            return Response(cached_payload)

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

        payload = {
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
        cache.set(self.CACHE_KEY, payload, settings.ANALYTICS_CACHE_TTL_SECONDS)
        return Response(payload)


class AssessmentExportCSVView(APIView):
    permission_classes = [HasCareflowRole]

    @extend_schema(responses={200: OpenApiResponse(description='CSV export of risk assessments')})
    def get(self, request):
        base_queryset = RiskAssessment.objects.select_related('patient', 'assessed_by').all()
        # Reuses the exact same `RiskAssessmentFilterSet` as
        # `RiskAssessmentViewSet` (see api/filters.py module docstring) so
        # "what filters are supported" and "how invalid values are
        # rejected" cannot drift between the list endpoint and this export.
        filterset = RiskAssessmentFilterSet(request.query_params, queryset=base_queryset, request=request)
        if not filterset.is_valid():
            return Response({'detail': 'Invalid filter parameters.', 'errors': filterset.errors}, status=status.HTTP_400_BAD_REQUEST)
        queryset = filterset.qs

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

        # Single pass over `.iterator()`: the row count is accumulated from
        # the same loop that streams rows, rather than a separate
        # `.count()` call before iterating — that previously issued two
        # queries against what can be a large table. `.iterator()` still
        # avoids materializing the full result set in memory.
        exported_count = 0
        for item in queryset.iterator():
            exported_count += 1
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

        # PHI-adjacent bulk export — this is exactly the access pattern that
        # a healthcare-domain audit trail must capture: who exported what,
        # how many records, and under which filters.
        filter_summary = ', '.join(
            f'{key}={value}' for key, value in request.query_params.items() if value
        ) or 'no filters'
        record_audit_event(
            request,
            action=AuditLog.ACTION_EXPORT,
            resource_type='RiskAssessment',
            detail=f'Exported {exported_count} row(s) ({filter_summary})',
        )
        logger.info(
            'risk_assessment_export',
            extra={'exported_count': exported_count, 'user': request.user.username},
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
        'urgent_checkins': PatientCheckIn.objects.urgent().count(),
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
