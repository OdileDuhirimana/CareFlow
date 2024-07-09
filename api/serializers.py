from rest_framework import serializers
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


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = ['id', 'name', 'age', 'gender', 'blood_type', 'diagnosis', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class AppointmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)

    class Meta:
        model = Appointment
        fields = [
            'id',
            'patient',
            'patient_name',
            'clinician_name',
            'reason',
            'scheduled_at',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at', 'patient_name']


class RiskAssessmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)
    assessed_by_username = serializers.CharField(source='assessed_by.username', read_only=True)

    class Meta:
        model = RiskAssessment
        fields = [
            'id',
            'patient',
            'patient_name',
            'assessed_by_username',
            'age',
            'bmi',
            'blood_pressure',
            'cholesterol',
            'smoker',
            'exercise_minutes',
            'chronic_conditions',
            'risk_score',
            'risk_level',
            'recommended_action',
            'key_drivers',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'patient_name',
            'assessed_by_username',
            'risk_score',
            'risk_level',
            'recommended_action',
            'key_drivers',
            'created_at',
        ]


class TriageAssessmentRequestSerializer(serializers.Serializer):
    patient_id = serializers.PrimaryKeyRelatedField(
        source='patient',
        queryset=Patient.objects.all(),
        required=False,
        allow_null=True,
    )
    age = serializers.IntegerField(min_value=0, max_value=120)
    bmi = serializers.FloatField(min_value=10, max_value=80)
    blood_pressure = serializers.IntegerField(min_value=70, max_value=260)
    cholesterol = serializers.IntegerField(min_value=100, max_value=500)
    smoker = serializers.BooleanField(default=False)
    exercise_minutes = serializers.IntegerField(min_value=0, max_value=2000, default=0)
    chronic_conditions = serializers.IntegerField(min_value=0, max_value=15, default=0)


class ClinicalAlertSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)

    class Meta:
        model = ClinicalAlert
        fields = [
            'id',
            'patient',
            'patient_name',
            'assessment',
            'severity',
            'title',
            'message',
            'resolved',
            'resolved_at',
            'created_at',
        ]
        read_only_fields = ['id', 'patient_name', 'created_at']


class RiskDriverSerializer(serializers.Serializer):
    factor = serializers.CharField()
    impact = serializers.FloatField()


class RiskPredictionSerializer(serializers.Serializer):
    risk_score = serializers.FloatField()
    risk_level = serializers.CharField()
    recommended_action = serializers.CharField()
    key_drivers = RiskDriverSerializer(many=True)


class TriageAssessmentResponseSerializer(serializers.Serializer):
    assessment = RiskAssessmentSerializer()
    alert_created = serializers.BooleanField()
    alert_id = serializers.IntegerField(allow_null=True)


class AnalyticsKpiSerializer(serializers.Serializer):
    patients_total = serializers.IntegerField()
    upcoming_appointments = serializers.IntegerField()
    assessments_last_30_days = serializers.IntegerField()
    open_alerts = serializers.IntegerField()


class DiagnosisBreakdownSerializer(serializers.Serializer):
    diagnosis = serializers.CharField()
    count = serializers.IntegerField()


class AssessmentTrendPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    count = serializers.IntegerField()


class AnalyticsOverviewSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    kpis = AnalyticsKpiSerializer()
    risk_distribution_last_30_days = serializers.DictField(child=serializers.IntegerField())
    top_diagnoses = DiagnosisBreakdownSerializer(many=True)
    assessment_trend = AssessmentTrendPointSerializer(many=True)


class PatientCheckInSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)
    submitted_by_username = serializers.CharField(source='submitted_by.username', read_only=True)

    class Meta:
        model = PatientCheckIn
        fields = [
            'id',
            'patient',
            'patient_name',
            'submitted_by_username',
            'symptom_severity',
            'mood_score',
            'medication_taken',
            'systolic_bp',
            'oxygen_saturation',
            'heart_rate',
            'notes',
            'created_at',
        ]
        read_only_fields = ['id', 'patient_name', 'submitted_by_username', 'created_at']


class CommunityResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommunityResource
        fields = [
            'id',
            'name',
            'category',
            'location',
            'contact_phone',
            'website',
            'description',
            'eligibility',
            'active',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class ResourceReferralSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)
    resource_name = serializers.CharField(source='resource.name', read_only=True)
    referred_by_username = serializers.CharField(source='referred_by.username', read_only=True)

    class Meta:
        model = ResourceReferral
        fields = [
            'id',
            'patient',
            'patient_name',
            'resource',
            'resource_name',
            'referred_by_username',
            'reason',
            'status',
            'follow_up_date',
            'impact_notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'patient_name', 'resource_name', 'referred_by_username', 'created_at', 'updated_at']


class CheckInResponseSerializer(serializers.Serializer):
    checkin = PatientCheckInSerializer()
    alert_created = serializers.BooleanField()
    alert_id = serializers.IntegerField(allow_null=True)


class ResourceRecommendationSerializer(serializers.Serializer):
    category = serializers.CharField()
    reason = serializers.CharField()
    resources = CommunityResourceSerializer(many=True)


class ImpactKpiSerializer(serializers.Serializer):
    active_community_resources = serializers.IntegerField()
    referrals_last_30_days = serializers.IntegerField()
    completed_referrals = serializers.IntegerField()
    urgent_checkins_last_7_days = serializers.IntegerField()


class ImpactOverviewSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    kpis = ImpactKpiSerializer()
    referral_status_breakdown = serializers.DictField(child=serializers.IntegerField())
    resource_category_breakdown = serializers.DictField(child=serializers.IntegerField())


class CommunityRecommendationResponseSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField()
    recommendations = ResourceRecommendationSerializer(many=True)
    auto_referrals_created = serializers.ListField(child=serializers.IntegerField())


class CurrentUserProfileSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    is_superuser = serializers.BooleanField()
    roles = serializers.ListField(child=serializers.CharField())


class WorkflowRuleSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = WorkflowRule
        fields = [
            'id',
            'name',
            'description',
            'event_type',
            'condition',
            'action_type',
            'action_config',
            'priority',
            'active',
            'created_by_username',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_by_username', 'created_at', 'updated_at']


class DomainEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DomainEvent
        fields = [
            'id',
            'event_type',
            'source',
            'payload',
            'status',
            'attempts',
            'error_message',
            'occurred_at',
            'processed_at',
        ]
        read_only_fields = fields


class ProcessDomainEventsRequestSerializer(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=200, default=25, required=False)
    include_failed = serializers.BooleanField(default=False, required=False)
    max_attempts = serializers.IntegerField(min_value=1, max_value=20, default=3, required=False)


class ProcessDomainEventsResponseSerializer(serializers.Serializer):
    processed_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    results = serializers.ListField(child=serializers.DictField())


class HospitalWardSerializer(serializers.ModelSerializer):
    occupied_beds = serializers.IntegerField(read_only=True)

    class Meta:
        model = HospitalWard
        fields = [
            'id',
            'name',
            'code',
            'specialty',
            'floor',
            'capacity',
            'active',
            'occupied_beds',
            'created_at',
        ]
        read_only_fields = ['id', 'occupied_beds', 'created_at']


class BedSerializer(serializers.ModelSerializer):
    ward_code = serializers.CharField(source='ward.code', read_only=True)
    current_patient_name = serializers.CharField(source='current_patient.name', read_only=True)

    class Meta:
        model = Bed
        fields = [
            'id',
            'ward',
            'ward_code',
            'bed_number',
            'status',
            'current_patient',
            'current_patient_name',
            'updated_at',
        ]
        read_only_fields = ['id', 'ward_code', 'current_patient_name', 'updated_at']


class AdmissionSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)
    bed_label = serializers.SerializerMethodField()
    admitted_by_username = serializers.CharField(source='admitted_by.username', read_only=True)

    class Meta:
        model = Admission
        fields = [
            'id',
            'patient',
            'patient_name',
            'bed',
            'bed_label',
            'admitted_by_username',
            'reason',
            'diagnosis_on_admission',
            'status',
            'admitted_at',
            'expected_discharge_date',
            'discharge_at',
            'discharge_summary',
        ]
        read_only_fields = ['id', 'patient_name', 'bed_label', 'admitted_by_username', 'admitted_at', 'discharge_at']

    def get_bed_label(self, obj) -> str:
        if not obj.bed_id:
            return ''
        return f'{obj.bed.ward.code}-{obj.bed.bed_number}'


class AdmissionTransferRequestSerializer(serializers.Serializer):
    bed = serializers.PrimaryKeyRelatedField(queryset=Bed.objects.all())
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AdmissionDischargeRequestSerializer(serializers.Serializer):
    discharge_summary = serializers.CharField(required=False, allow_blank=True)


class MedicationOrderSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)
    prescribed_by_username = serializers.CharField(source='prescribed_by.username', read_only=True)

    class Meta:
        model = MedicationOrder
        fields = [
            'id',
            'patient',
            'patient_name',
            'admission',
            'prescribed_by_username',
            'medication_name',
            'dosage',
            'frequency',
            'route',
            'instructions',
            'status',
            'start_at',
            'end_at',
            'created_at',
        ]
        read_only_fields = ['id', 'patient_name', 'prescribed_by_username', 'created_at']


class MedicationStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=MedicationOrder.STATUS_CHOICES)
    notes = serializers.CharField(required=False, allow_blank=True)


class LabOrderSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.name', read_only=True)
    ordered_by_username = serializers.CharField(source='ordered_by.username', read_only=True)

    class Meta:
        model = LabOrder
        fields = [
            'id',
            'patient',
            'patient_name',
            'admission',
            'ordered_by_username',
            'test_name',
            'priority',
            'status',
            'sample_collected_at',
            'result_value',
            'result_summary',
            'ordered_at',
            'completed_at',
        ]
        read_only_fields = ['id', 'patient_name', 'ordered_by_username', 'ordered_at', 'completed_at']


class LabOrderCompleteSerializer(serializers.Serializer):
    result_value = serializers.CharField(required=False, allow_blank=True, max_length=255)
    result_summary = serializers.CharField(required=False, allow_blank=True)


class HospitalFlowKpiSerializer(serializers.Serializer):
    active_admissions = serializers.IntegerField()
    bed_occupancy_rate = serializers.FloatField()
    available_beds = serializers.IntegerField()
    active_medication_orders = serializers.IntegerField()
    pending_lab_orders = serializers.IntegerField()
    discharges_last_7_days = serializers.IntegerField()


class HospitalFlowOverviewSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField()
    kpis = HospitalFlowKpiSerializer()
    admissions_by_status = serializers.DictField(child=serializers.IntegerField())
    labs_by_status = serializers.DictField(child=serializers.IntegerField())
