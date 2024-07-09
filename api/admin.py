from django.contrib import admin
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

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'age', 'gender', 'blood_type', 'created_at')
    search_fields = ('name', 'diagnosis')
    list_filter = ('gender', 'blood_type', 'created_at')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'clinician_name', 'scheduled_at', 'status')
    search_fields = ('patient__name', 'clinician_name', 'reason')
    list_filter = ('status', 'scheduled_at')


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'risk_level', 'risk_score', 'created_at')
    search_fields = ('patient__name',)
    list_filter = ('risk_level', 'smoker', 'created_at')


@admin.register(ClinicalAlert)
class ClinicalAlertAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'severity', 'resolved', 'created_at')
    search_fields = ('patient__name', 'title', 'message')
    list_filter = ('severity', 'resolved', 'created_at')


@admin.register(PatientCheckIn)
class PatientCheckInAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'symptom_severity', 'mood_score', 'medication_taken', 'created_at')
    search_fields = ('patient__name', 'notes')
    list_filter = ('medication_taken', 'created_at')


@admin.register(CommunityResource)
class CommunityResourceAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'location', 'active')
    search_fields = ('name', 'description', 'location', 'eligibility')
    list_filter = ('category', 'active')


@admin.register(ResourceReferral)
class ResourceReferralAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'resource', 'status', 'follow_up_date', 'created_at')
    search_fields = ('patient__name', 'resource__name', 'reason', 'impact_notes')
    list_filter = ('status', 'follow_up_date', 'created_at')


@admin.register(HospitalWard)
class HospitalWardAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'specialty', 'floor', 'capacity', 'active')
    search_fields = ('code', 'name')
    list_filter = ('specialty', 'active', 'floor')


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ('id', 'ward', 'bed_number', 'status', 'current_patient', 'updated_at')
    search_fields = ('ward__code', 'bed_number', 'current_patient__name')
    list_filter = ('status', 'ward')


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'status', 'bed', 'admitted_at', 'discharge_at')
    search_fields = ('patient__name', 'reason', 'diagnosis_on_admission')
    list_filter = ('status', 'admitted_at')


@admin.register(MedicationOrder)
class MedicationOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'medication_name', 'status', 'start_at', 'end_at')
    search_fields = ('patient__name', 'medication_name', 'dosage')
    list_filter = ('status', 'route', 'start_at')


@admin.register(LabOrder)
class LabOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'patient', 'test_name', 'priority', 'status', 'ordered_at', 'completed_at')
    search_fields = ('patient__name', 'test_name', 'result_value')
    list_filter = ('priority', 'status', 'ordered_at')


@admin.register(WorkflowRule)
class WorkflowRuleAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'event_type', 'action_type', 'priority', 'active', 'created_at')
    search_fields = ('name', 'description', 'event_type', 'action_type')
    list_filter = ('event_type', 'action_type', 'active')


@admin.register(DomainEvent)
class DomainEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'event_type', 'source', 'status', 'attempts', 'occurred_at', 'processed_at')
    search_fields = ('event_type', 'source', 'error_message')
    list_filter = ('status', 'event_type', 'occurred_at')
