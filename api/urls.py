from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AdmissionViewSet,
    AppointmentViewSet,
    AssessmentExportCSVView,
    BedViewSet,
    CareAnalyticsView,
    ClinicalAlertViewSet,
    CommunityResourceViewSet,
    CurrentUserProfileView,
    DomainEventViewSet,
    HospitalFlowAnalyticsView,
    HospitalWardViewSet,
    ImpactAnalyticsView,
    LabOrderViewSet,
    MedicationOrderViewSet,
    PatientViewSet,
    PatientCheckInViewSet,
    PredictHealthRiskView,
    ResourceReferralViewSet,
    RiskAssessmentViewSet,
    TriageAssessmentView,
    WorkflowRuleViewSet,
)

router = DefaultRouter()
router.register(r'patients', PatientViewSet, basename='patient')
router.register(r'appointments', AppointmentViewSet, basename='appointment')
router.register(r'wards', HospitalWardViewSet, basename='ward')
router.register(r'beds', BedViewSet, basename='bed')
router.register(r'admissions', AdmissionViewSet, basename='admission')
router.register(r'medication-orders', MedicationOrderViewSet, basename='medication-order')
router.register(r'lab-orders', LabOrderViewSet, basename='lab-order')
router.register(r'assessments', RiskAssessmentViewSet, basename='assessment')
router.register(r'alerts', ClinicalAlertViewSet, basename='alert')
router.register(r'checkins', PatientCheckInViewSet, basename='checkin')
router.register(r'community-resources', CommunityResourceViewSet, basename='community-resource')
router.register(r'referrals', ResourceReferralViewSet, basename='referral')
router.register(r'workflow-rules', WorkflowRuleViewSet, basename='workflow-rule')
router.register(r'domain-events', DomainEventViewSet, basename='domain-event')

urlpatterns = [
    path('', include(router.urls)),
    path('auth/me/', CurrentUserProfileView.as_view(), name='auth-me'),
    path('predict/health-risk/', PredictHealthRiskView.as_view(), name='predict-health-risk'),
    path('triage/assess/', TriageAssessmentView.as_view(), name='triage-assess'),
    path('analytics/overview/', CareAnalyticsView.as_view(), name='analytics-overview'),
    path('analytics/impact/', ImpactAnalyticsView.as_view(), name='analytics-impact'),
    path('analytics/hospital-flow/', HospitalFlowAnalyticsView.as_view(), name='analytics-hospital-flow'),
    path('analytics/assessments/export.csv', AssessmentExportCSVView.as_view(), name='assessments-export'),
]
