from django.db import models
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone


class Patient(models.Model):
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ]
    name = models.CharField(max_length=255)
    age = models.PositiveIntegerField()
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    blood_type = models.CharField(max_length=3, blank=True, null=True)
    diagnosis = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.age})"


class Appointment(models.Model):
    STATUS_SCHEDULED = 'scheduled'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_NO_SHOW = 'no_show'
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_NO_SHOW, 'No Show'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='appointments')
    clinician_name = models.CharField(max_length=255)
    reason = models.CharField(max_length=255, blank=True)
    scheduled_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    created_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['scheduled_at']

    def __str__(self):
        return f"{self.patient.name} with {self.clinician_name} at {self.scheduled_at.isoformat()}"


class RiskAssessment(models.Model):
    LEVEL_LOW = 'Low'
    LEVEL_MEDIUM = 'Medium'
    LEVEL_HIGH = 'High'
    LEVEL_CRITICAL = 'Critical'
    RISK_LEVEL_CHOICES = [
        (LEVEL_LOW, 'Low'),
        (LEVEL_MEDIUM, 'Medium'),
        (LEVEL_HIGH, 'High'),
        (LEVEL_CRITICAL, 'Critical'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name='risk_assessments')
    assessed_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    age = models.PositiveIntegerField()
    bmi = models.FloatField()
    blood_pressure = models.PositiveIntegerField()
    cholesterol = models.PositiveIntegerField()
    smoker = models.BooleanField(default=False)
    exercise_minutes = models.PositiveIntegerField(default=0)
    chronic_conditions = models.PositiveIntegerField(default=0)
    risk_score = models.FloatField()
    risk_level = models.CharField(max_length=10, choices=RISK_LEVEL_CHOICES)
    recommended_action = models.TextField()
    key_drivers = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['risk_level']),
        ]

    def __str__(self):
        patient_name = self.patient.name if self.patient else 'Unlinked patient'
        return f"{patient_name}: {self.risk_level} ({self.risk_score:.2f})"


class ClinicalAlert(models.Model):
    SEVERITY_MEDIUM = 'medium'
    SEVERITY_HIGH = 'high'
    SEVERITY_CRITICAL = 'critical'
    SEVERITY_CHOICES = [
        (SEVERITY_MEDIUM, 'Medium'),
        (SEVERITY_HIGH, 'High'),
        (SEVERITY_CRITICAL, 'Critical'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='alerts')
    assessment = models.ForeignKey(
        RiskAssessment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alerts',
    )
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['resolved', '-created_at']
        indexes = [
            models.Index(fields=['resolved', 'severity']),
        ]

    def __str__(self):
        return f"{self.get_severity_display()} alert for {self.patient.name}"


class PatientCheckInQuerySet(models.QuerySet):
    def urgent(self):
        """Check-ins whose vitals/symptoms cross a clinically-urgent threshold.

        This exact five-clause `Q()` filter was previously copy-pasted
        verbatim in three places (`PatientCheckInViewSet.get_queryset`,
        `ImpactAnalyticsView.get`, and `portfolio_home`) — a confirmed
        CODE-04 DRY violation. Centralizing it here means the definition of
        "urgent" lives in exactly one place, and the clinical thresholds
        themselves are named constants on `PatientCheckIn` (see CODE-06)
        rather than magic numbers repeated at every call site.
        """
        return self.filter(
            Q(symptom_severity__gte=PatientCheckIn.SEVERE_SYMPTOM_SEVERITY)
            | Q(oxygen_saturation__lt=PatientCheckIn.LOW_OXYGEN_SATURATION)
            | Q(systolic_bp__gte=PatientCheckIn.CRITICAL_SYSTOLIC_BP)
            | Q(heart_rate__gte=PatientCheckIn.HIGH_HEART_RATE)
            | (Q(mood_score__lte=PatientCheckIn.LOW_MOOD_SCORE) & Q(medication_taken=False))
        )


class PatientCheckIn(models.Model):
    # Named clinical thresholds (CODE-06) used both by `PatientCheckInQuerySet.urgent()`
    # above and by `api.services.alerts.checkin_alert_payload` to decide whether a
    # check-in should raise an automatic clinical alert. Keeping them here (as
    # constants on the model they describe) rather than inline in each
    # consumer means a clinical-threshold policy change is a one-line edit
    # applied everywhere consistently.
    SEVERE_SYMPTOM_SEVERITY = 8
    LOW_OXYGEN_SATURATION = 92
    CRITICAL_SYSTOLIC_BP = 180
    HIGH_HEART_RATE = 130
    LOW_MOOD_SCORE = 2

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='checkins')
    submitted_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    symptom_severity = models.PositiveSmallIntegerField(default=0)
    mood_score = models.PositiveSmallIntegerField(default=5)
    medication_taken = models.BooleanField(default=True)
    systolic_bp = models.PositiveIntegerField(null=True, blank=True)
    oxygen_saturation = models.PositiveSmallIntegerField(null=True, blank=True)
    heart_rate = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PatientCheckInQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['symptom_severity']),
        ]

    def __str__(self):
        return f"Check-in for {self.patient.name} at {self.created_at.isoformat()}"


class CommunityResource(models.Model):
    CATEGORY_MENTAL_HEALTH = 'mental_health'
    CATEGORY_FOOD_SUPPORT = 'food_support'
    CATEGORY_TRANSPORT = 'transport'
    CATEGORY_FINANCIAL = 'financial'
    CATEGORY_HOUSING = 'housing'
    CATEGORY_CHRONIC_CARE = 'chronic_care'
    CATEGORY_WELLNESS = 'wellness'
    CATEGORY_CHOICES = [
        (CATEGORY_MENTAL_HEALTH, 'Mental Health'),
        (CATEGORY_FOOD_SUPPORT, 'Food Support'),
        (CATEGORY_TRANSPORT, 'Transport'),
        (CATEGORY_FINANCIAL, 'Financial Aid'),
        (CATEGORY_HOUSING, 'Housing'),
        (CATEGORY_CHRONIC_CARE, 'Chronic Care'),
        (CATEGORY_WELLNESS, 'Wellness'),
    ]

    name = models.CharField(max_length=255)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    location = models.CharField(max_length=255, blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    eligibility = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'name']
        indexes = [
            models.Index(fields=['category', 'active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class ResourceReferral(models.Model):
    STATUS_RECOMMENDED = 'recommended'
    STATUS_CONTACTED = 'contacted'
    STATUS_ENROLLED = 'enrolled'
    STATUS_COMPLETED = 'completed'
    STATUS_DECLINED = 'declined'
    STATUS_CHOICES = [
        (STATUS_RECOMMENDED, 'Recommended'),
        (STATUS_CONTACTED, 'Contacted'),
        (STATUS_ENROLLED, 'Enrolled'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_DECLINED, 'Declined'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='referrals')
    resource = models.ForeignKey(CommunityResource, on_delete=models.CASCADE, related_name='referrals')
    referred_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RECOMMENDED)
    follow_up_date = models.DateField(null=True, blank=True)
    impact_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.patient.name} -> {self.resource.name} ({self.status})"


class HospitalWard(models.Model):
    SPECIALTY_GENERAL = 'general'
    SPECIALTY_EMERGENCY = 'emergency'
    SPECIALTY_ICU = 'icu'
    SPECIALTY_MATERNITY = 'maternity'
    SPECIALTY_PEDIATRICS = 'pediatrics'
    SPECIALTY_SURGERY = 'surgery'
    SPECIALTY_CHOICES = [
        (SPECIALTY_GENERAL, 'General'),
        (SPECIALTY_EMERGENCY, 'Emergency'),
        (SPECIALTY_ICU, 'ICU'),
        (SPECIALTY_MATERNITY, 'Maternity'),
        (SPECIALTY_PEDIATRICS, 'Pediatrics'),
        (SPECIALTY_SURGERY, 'Surgery'),
    ]

    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=30, unique=True)
    specialty = models.CharField(max_length=20, choices=SPECIALTY_CHOICES, default=SPECIALTY_GENERAL)
    floor = models.PositiveSmallIntegerField(default=1)
    capacity = models.PositiveIntegerField(default=20)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class Bed(models.Model):
    STATUS_AVAILABLE = 'available'
    STATUS_OCCUPIED = 'occupied'
    STATUS_CLEANING = 'cleaning'
    STATUS_MAINTENANCE = 'maintenance'
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, 'Available'),
        (STATUS_OCCUPIED, 'Occupied'),
        (STATUS_CLEANING, 'Cleaning'),
        (STATUS_MAINTENANCE, 'Maintenance'),
    ]

    ward = models.ForeignKey(HospitalWard, on_delete=models.CASCADE, related_name='beds')
    bed_number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
    current_patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='current_bed_assignments',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['ward__code', 'bed_number']
        constraints = [
            models.UniqueConstraint(fields=['ward', 'bed_number'], name='unique_bed_per_ward'),
        ]
        indexes = [
            models.Index(fields=['status', 'ward']),
        ]

    def __str__(self):
        return f"{self.ward.code}-{self.bed_number} ({self.status})"


class Admission(models.Model):
    STATUS_ADMITTED = 'admitted'
    STATUS_DISCHARGED = 'discharged'
    STATUS_TRANSFERRED = 'transferred'
    STATUS_CHOICES = [
        (STATUS_ADMITTED, 'Admitted'),
        (STATUS_DISCHARGED, 'Discharged'),
        (STATUS_TRANSFERRED, 'Transferred'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='admissions')
    bed = models.ForeignKey(Bed, on_delete=models.SET_NULL, null=True, blank=True, related_name='admissions')
    admitted_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    reason = models.CharField(max_length=255)
    diagnosis_on_admission = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ADMITTED)
    admitted_at = models.DateTimeField(auto_now_add=True)
    expected_discharge_date = models.DateField(null=True, blank=True)
    discharge_at = models.DateTimeField(null=True, blank=True)
    discharge_summary = models.TextField(blank=True)

    class Meta:
        ordering = ['-admitted_at']
        indexes = [
            models.Index(fields=['status', 'admitted_at']),
        ]

    def __str__(self):
        return f"Admission {self.id} - {self.patient.name} ({self.status})"


class MedicationOrder(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_COMPLETED = 'completed'
    STATUS_STOPPED = 'stopped'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_STOPPED, 'Stopped'),
    ]

    ROUTE_ORAL = 'oral'
    ROUTE_IV = 'iv'
    ROUTE_IM = 'im'
    ROUTE_INHALED = 'inhaled'
    ROUTE_SUBCUTANEOUS = 'subcutaneous'
    ROUTE_CHOICES = [
        (ROUTE_ORAL, 'Oral'),
        (ROUTE_IV, 'IV'),
        (ROUTE_IM, 'IM'),
        (ROUTE_INHALED, 'Inhaled'),
        (ROUTE_SUBCUTANEOUS, 'Subcutaneous'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='medication_orders')
    admission = models.ForeignKey(Admission, on_delete=models.SET_NULL, null=True, blank=True, related_name='medication_orders')
    prescribed_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    medication_name = models.CharField(max_length=255)
    dosage = models.CharField(max_length=120)
    frequency = models.CharField(max_length=120)
    route = models.CharField(max_length=20, choices=ROUTE_CHOICES, default=ROUTE_ORAL)
    instructions = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    start_at = models.DateTimeField(default=timezone.now)
    end_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'start_at']),
        ]

    def __str__(self):
        return f"{self.medication_name} for {self.patient.name}"


class LabOrder(models.Model):
    PRIORITY_ROUTINE = 'routine'
    PRIORITY_URGENT = 'urgent'
    PRIORITY_STAT = 'stat'
    PRIORITY_CHOICES = [
        (PRIORITY_ROUTINE, 'Routine'),
        (PRIORITY_URGENT, 'Urgent'),
        (PRIORITY_STAT, 'STAT'),
    ]

    STATUS_ORDERED = 'ordered'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_ORDERED, 'Ordered'),
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='lab_orders')
    admission = models.ForeignKey(Admission, on_delete=models.SET_NULL, null=True, blank=True, related_name='lab_orders')
    ordered_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    test_name = models.CharField(max_length=255)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default=PRIORITY_ROUTINE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ORDERED)
    sample_collected_at = models.DateTimeField(null=True, blank=True)
    result_value = models.CharField(max_length=255, blank=True)
    result_summary = models.TextField(blank=True)
    ordered_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-ordered_at']
        indexes = [
            models.Index(fields=['status', 'priority', 'ordered_at']),
        ]

    def __str__(self):
        return f"{self.test_name} for {self.patient.name} ({self.status})"


class DomainEvent(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSED = 'processed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSED, 'Processed'),
        (STATUS_FAILED, 'Failed'),
    ]

    event_type = models.CharField(max_length=120)
    source = models.CharField(max_length=120, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['status', 'occurred_at']),
            models.Index(fields=['event_type', 'status']),
        ]

    def __str__(self):
        return f"{self.event_type} ({self.status})"


class WorkflowRule(models.Model):
    ACTION_CREATE_ALERT = 'create_alert'
    ACTION_CREATE_APPOINTMENT = 'create_appointment'
    ACTION_CREATE_REFERRAL = 'create_referral'
    ACTION_CHOICES = [
        (ACTION_CREATE_ALERT, 'Create Alert'),
        (ACTION_CREATE_APPOINTMENT, 'Create Appointment'),
        (ACTION_CREATE_REFERRAL, 'Create Referral'),
    ]

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    event_type = models.CharField(max_length=120)
    condition = models.JSONField(default=dict, blank=True)
    action_type = models.CharField(max_length=40, choices=ACTION_CHOICES)
    action_config = models.JSONField(default=dict, blank=True)
    priority = models.PositiveIntegerField(default=100)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'name']
        indexes = [
            models.Index(fields=['active', 'event_type', 'priority']),
        ]

    def __str__(self):
        return f"{self.name} [{self.event_type}]"


class AuditLog(models.Model):
    """Immutable record of who accessed or changed PHI-adjacent data, and when.

    Why this exists: CareFlow stores patient-identifying and clinical data
    (Patient, RiskAssessment, MedicationOrder, LabOrder). A healthcare-domain
    application with zero record of "who viewed/exported/modified this
    patient's data" cannot support any real compliance or incident-response
    workflow. This model is intentionally minimal (no generic-relation
    framework, no admin-configurable rule engine) — it is written to
    explicitly, at the specific call sites that touch sensitive data
    (see `api/audit.py`), rather than wired blindly into every model via
    signals, so that log entries stay meaningful and low-noise.

    Rows are never updated or deleted by application code — this table is
    an append-only trail. There is intentionally no FK `on_delete=CASCADE`
    from `actor` to avoid audit history disappearing if a user account is
    later removed; `SET_NULL` preserves the historical record.
    """

    ACTION_VIEW = 'view'
    ACTION_CREATE = 'create'
    ACTION_UPDATE = 'update'
    ACTION_DELETE = 'delete'
    ACTION_EXPORT = 'export'
    ACTION_CHOICES = [
        (ACTION_VIEW, 'View'),
        (ACTION_CREATE, 'Create'),
        (ACTION_UPDATE, 'Update'),
        (ACTION_DELETE, 'Delete'),
        (ACTION_EXPORT, 'Export'),
    ]

    actor = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    resource_type = models.CharField(max_length=100, help_text='Model/resource name, e.g. "Patient".')
    resource_id = models.CharField(max_length=64, blank=True, help_text='Primary key of the affected record, if any.')
    detail = models.CharField(max_length=255, blank=True, help_text='Short human-readable context, e.g. filter params.')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['resource_type', 'resource_id']),
            models.Index(fields=['actor', 'created_at']),
            models.Index(fields=['action', 'created_at']),
        ]

    def __str__(self):
        actor_label = self.actor.username if self.actor else 'anonymous'
        return f"{actor_label} {self.action} {self.resource_type}:{self.resource_id or '-'} @ {self.created_at.isoformat()}"
