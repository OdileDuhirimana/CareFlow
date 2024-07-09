from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api.models import (
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
from api.roles import ROLE_ADMIN, ROLE_CLINICIAN, ROLE_OUTREACH


class Command(BaseCommand):
    help = 'Seed CareFlow with realistic demo users and social-impact healthcare data.'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='careflow-demo-2026', help='Password for demo users.')
        parser.add_argument('--reset', action='store_true', help='Delete existing demo records and recreate.')

    def _create_once(self, model, lookup, defaults):
        instance, _ = model.objects.get_or_create(**lookup, defaults=defaults)
        return instance

    @transaction.atomic
    def handle(self, *args, **options):
        password = options['password']
        reset = options['reset']

        call_command('setup_roles')

        User = get_user_model()

        if reset:
            demo_usernames = ['admin_demo', 'clinician_demo', 'outreach_demo']
            User.objects.filter(username__in=demo_usernames).delete()
            DomainEvent.objects.filter(source__in=[
                'triage.assess',
                'checkins.create',
                'admissions.perform_create',
                'admissions.discharge',
                'lab_orders.complete',
            ]).delete()
            WorkflowRule.objects.filter(name__in=[
                'High Risk Triage Follow-up',
                'Critical Check-in Escalation',
                'Senior Discharge Referral',
            ]).delete()
            LabOrder.objects.filter(patient__name__in=[
                'Amina Rahman', 'James Carter', 'Priya Nair', 'Samuel Okoro'
            ]).delete()
            MedicationOrder.objects.filter(patient__name__in=[
                'Amina Rahman', 'James Carter', 'Priya Nair', 'Samuel Okoro'
            ]).delete()
            Admission.objects.filter(patient__name__in=[
                'Amina Rahman', 'James Carter', 'Priya Nair', 'Samuel Okoro'
            ]).delete()
            ResourceReferral.objects.filter(patient__name__in=[
                'Amina Rahman', 'James Carter', 'Priya Nair', 'Samuel Okoro'
            ]).delete()
            Appointment.objects.filter(patient__name__in=[
                'Amina Rahman', 'James Carter', 'Priya Nair', 'Samuel Okoro'
            ]).delete()
            ClinicalAlert.objects.filter(patient__name__in=[
                'Amina Rahman', 'James Carter', 'Priya Nair', 'Samuel Okoro'
            ]).delete()
            RiskAssessment.objects.filter(patient__name__in=[
                'Amina Rahman', 'James Carter', 'Priya Nair', 'Samuel Okoro'
            ]).delete()
            PatientCheckIn.objects.filter(patient__name__in=[
                'Amina Rahman', 'James Carter', 'Priya Nair', 'Samuel Okoro'
            ]).delete()
            Patient.objects.filter(name__in=['Amina Rahman', 'James Carter', 'Priya Nair', 'Samuel Okoro']).delete()
            CommunityResource.objects.filter(name__in=[
                'City Chronic Care Hub',
                'Mind Matters Counseling',
                'CareRide Medical Transport',
                'Healthy Plate Food Support',
                'Medication Relief Fund',
                'Active Aging Wellness Club',
            ]).delete()
            Bed.objects.filter(ward__code__in=['ER-1', 'GEN-2', 'ICU-1']).delete()
            HospitalWard.objects.filter(code__in=['ER-1', 'GEN-2', 'ICU-1']).delete()

        admin_group = Group.objects.get(name=ROLE_ADMIN)
        clinician_group = Group.objects.get(name=ROLE_CLINICIAN)
        outreach_group = Group.objects.get(name=ROLE_OUTREACH)

        admin_user, _ = User.objects.get_or_create(
            username='admin_demo',
            defaults={'email': 'admin_demo@careflow.local', 'is_staff': True},
        )
        admin_user.set_password(password)
        admin_user.is_staff = True
        admin_user.save(update_fields=['password', 'is_staff'])
        admin_user.groups.set([admin_group])

        clinician_user, _ = User.objects.get_or_create(
            username='clinician_demo',
            defaults={'email': 'clinician_demo@careflow.local', 'is_staff': True},
        )
        clinician_user.set_password(password)
        clinician_user.is_staff = True
        clinician_user.save(update_fields=['password', 'is_staff'])
        clinician_user.groups.set([clinician_group])

        outreach_user, _ = User.objects.get_or_create(
            username='outreach_demo',
            defaults={'email': 'outreach_demo@careflow.local'},
        )
        outreach_user.set_password(password)
        outreach_user.save(update_fields=['password'])
        outreach_user.groups.set([outreach_group])

        resources = [
            {
                'name': 'City Chronic Care Hub',
                'category': CommunityResource.CATEGORY_CHRONIC_CARE,
                'location': 'Downtown Clinic Complex',
                'description': 'Nurse-led long-term disease coaching and adherence support.',
                'eligibility': 'Adults with chronic cardiovascular or metabolic disease.',
                'contact_phone': '+1-555-1001',
                'website': 'https://example.org/chronic-care',
            },
            {
                'name': 'Mind Matters Counseling',
                'category': CommunityResource.CATEGORY_MENTAL_HEALTH,
                'location': 'Northside Community Center',
                'description': 'Short-term counseling and crisis support sessions.',
                'eligibility': 'Open to all residents.',
                'contact_phone': '+1-555-1002',
                'website': 'https://example.org/mind-matters',
            },
            {
                'name': 'CareRide Medical Transport',
                'category': CommunityResource.CATEGORY_TRANSPORT,
                'location': 'Citywide',
                'description': 'Low-cost transport for appointments and diagnostics.',
                'eligibility': 'Patients with mobility or transport barriers.',
                'contact_phone': '+1-555-1003',
                'website': 'https://example.org/careride',
            },
            {
                'name': 'Healthy Plate Food Support',
                'category': CommunityResource.CATEGORY_FOOD_SUPPORT,
                'location': 'East District',
                'description': 'Nutrition packages for diabetic and hypertensive patients.',
                'eligibility': 'Low-income households with diet-related conditions.',
                'contact_phone': '+1-555-1004',
                'website': 'https://example.org/healthy-plate',
            },
            {
                'name': 'Medication Relief Fund',
                'category': CommunityResource.CATEGORY_FINANCIAL,
                'location': 'Central Health Office',
                'description': 'Partial subsidy for essential medications.',
                'eligibility': 'Uninsured or underinsured patients.',
                'contact_phone': '+1-555-1005',
                'website': 'https://example.org/med-relief',
            },
            {
                'name': 'Active Aging Wellness Club',
                'category': CommunityResource.CATEGORY_WELLNESS,
                'location': 'Westside Hall',
                'description': 'Senior fitness, education, and social sessions.',
                'eligibility': 'Adults above 60.',
                'contact_phone': '+1-555-1006',
                'website': 'https://example.org/active-aging',
            },
        ]

        resource_map = {}
        for payload in resources:
            resource = self._create_once(
                CommunityResource,
                lookup={'name': payload['name']},
                defaults={**payload, 'active': True},
            )
            resource_map[payload['name']] = resource

        wards = [
            {'name': 'Emergency Unit', 'code': 'ER-1', 'specialty': HospitalWard.SPECIALTY_EMERGENCY, 'floor': 1, 'capacity': 8},
            {'name': 'General Medicine', 'code': 'GEN-2', 'specialty': HospitalWard.SPECIALTY_GENERAL, 'floor': 2, 'capacity': 24},
            {'name': 'Intensive Care', 'code': 'ICU-1', 'specialty': HospitalWard.SPECIALTY_ICU, 'floor': 1, 'capacity': 6},
        ]

        ward_map = {}
        for payload in wards:
            ward = self._create_once(
                HospitalWard,
                lookup={'code': payload['code']},
                defaults={**payload, 'active': True},
            )
            ward_map[ward.code] = ward

        bed_assignments = [
            ('ER-1', ['E01', 'E02', 'E03']),
            ('GEN-2', ['G01', 'G02', 'G03', 'G04']),
            ('ICU-1', ['I01', 'I02']),
        ]
        bed_map = {}
        for ward_code, bed_numbers in bed_assignments:
            for bed_number in bed_numbers:
                bed = self._create_once(
                    Bed,
                    lookup={'ward': ward_map[ward_code], 'bed_number': bed_number},
                    defaults={'status': Bed.STATUS_AVAILABLE},
                )
                bed_map[f'{ward_code}-{bed_number}'] = bed

        patients = [
            {'name': 'Amina Rahman', 'age': 67, 'gender': 'female', 'blood_type': 'A+', 'diagnosis': 'Hypertension and diabetes'},
            {'name': 'James Carter', 'age': 58, 'gender': 'male', 'blood_type': 'O+', 'diagnosis': 'Chronic heart failure'},
            {'name': 'Priya Nair', 'age': 34, 'gender': 'female', 'blood_type': 'B+', 'diagnosis': 'Postpartum anxiety'},
            {'name': 'Samuel Okoro', 'age': 73, 'gender': 'male', 'blood_type': 'AB-', 'diagnosis': 'COPD with mobility challenges'},
        ]

        patient_map = {}
        for payload in patients:
            patient = self._create_once(
                Patient,
                lookup={'name': payload['name']},
                defaults={**payload, 'created_by': clinician_user},
            )
            patient_map[payload['name']] = patient

        now = timezone.now()

        assessments = [
            ('Amina Rahman', 67, 31.2, 166, 262, False, 45, 2, 0.78, RiskAssessment.LEVEL_CRITICAL, 'Urgent hypertension and diabetes stabilization plan.'),
            ('James Carter', 58, 29.3, 152, 241, True, 20, 2, 0.69, RiskAssessment.LEVEL_HIGH, 'Cardiology follow-up within 72 hours.'),
            ('Priya Nair', 34, 24.9, 122, 181, False, 90, 0, 0.33, RiskAssessment.LEVEL_LOW, 'Maintain preventive follow-up and mental health support.'),
            ('Samuel Okoro', 73, 27.5, 148, 210, False, 35, 3, 0.63, RiskAssessment.LEVEL_HIGH, 'Increase respiratory monitoring and home care checks.'),
        ]

        for entry in assessments:
            name, age, bmi, bp, chol, smoker, exercise, chronic, score, level, action = entry
            patient = patient_map[name]
            assessment = RiskAssessment.objects.filter(patient=patient, risk_level=level, risk_score=score).first()
            if not assessment:
                assessment = RiskAssessment.objects.create(
                    patient=patient,
                    assessed_by=clinician_user,
                    age=age,
                    bmi=bmi,
                    blood_pressure=bp,
                    cholesterol=chol,
                    smoker=smoker,
                    exercise_minutes=exercise,
                    chronic_conditions=chronic,
                    risk_score=score,
                    risk_level=level,
                    recommended_action=action,
                    key_drivers=[
                        {'factor': 'blood_pressure', 'impact': 0.21},
                        {'factor': 'chronic_conditions', 'impact': 0.16},
                        {'factor': 'age', 'impact': 0.14},
                    ],
                )

            if level in [RiskAssessment.LEVEL_HIGH, RiskAssessment.LEVEL_CRITICAL]:
                ClinicalAlert.objects.get_or_create(
                    patient=patient,
                    assessment=assessment,
                    title=f'{level} risk patient flagged',
                    defaults={
                        'severity': ClinicalAlert.SEVERITY_CRITICAL if level == RiskAssessment.LEVEL_CRITICAL else ClinicalAlert.SEVERITY_HIGH,
                        'message': action,
                    },
                )

        appointments = [
            ('Amina Rahman', 'Dr. Patel', 'Cardio-metabolic review', now + timedelta(days=1), Appointment.STATUS_SCHEDULED),
            ('James Carter', 'Dr. Stone', 'Heart failure management', now + timedelta(days=2), Appointment.STATUS_SCHEDULED),
            ('Priya Nair', 'Dr. Mensah', 'Mental wellness follow-up', now - timedelta(days=4), Appointment.STATUS_COMPLETED),
            ('Samuel Okoro', 'Dr. Lee', 'Respiratory evaluation', now + timedelta(days=3), Appointment.STATUS_SCHEDULED),
        ]

        for name, clinician_name, reason, scheduled_at, status in appointments:
            patient = patient_map[name]
            Appointment.objects.get_or_create(
                patient=patient,
                clinician_name=clinician_name,
                scheduled_at=scheduled_at,
                defaults={
                    'reason': reason,
                    'status': status,
                    'created_by': clinician_user,
                },
            )

        admissions = [
            ('Amina Rahman', 'GEN-2-G01', 'Hypertensive crisis monitoring', 'Elevated blood pressure and uncontrolled glucose.'),
            ('James Carter', 'ICU-1-I01', 'Acute heart failure stabilization', 'Decompensated heart failure requiring close monitoring.'),
            ('Samuel Okoro', 'GEN-2-G02', 'COPD exacerbation treatment', 'Respiratory support and medication adjustment needed.'),
        ]

        admission_map = {}
        for patient_name, bed_code, reason, diagnosis in admissions:
            patient = patient_map[patient_name]
            bed = bed_map[bed_code]
            admission = Admission.objects.filter(patient=patient, status=Admission.STATUS_ADMITTED).first()
            if not admission:
                admission = Admission.objects.create(
                    patient=patient,
                    bed=bed,
                    admitted_by=clinician_user,
                    reason=reason,
                    diagnosis_on_admission=diagnosis,
                    status=Admission.STATUS_ADMITTED,
                    expected_discharge_date=(now + timedelta(days=5)).date(),
                )
            bed.status = Bed.STATUS_OCCUPIED
            bed.current_patient = patient
            bed.save(update_fields=['status', 'current_patient', 'updated_at'])
            admission_map[patient_name] = admission

        med_orders = [
            ('Amina Rahman', 'Losartan', '50mg', 'Once daily', MedicationOrder.ROUTE_ORAL),
            ('James Carter', 'Furosemide', '40mg', 'Twice daily', MedicationOrder.ROUTE_IV),
            ('Samuel Okoro', 'Salbutamol', '2 puffs', 'Every 6 hours', MedicationOrder.ROUTE_INHALED),
        ]
        for patient_name, medication, dosage, frequency, route in med_orders:
            patient = patient_map[patient_name]
            MedicationOrder.objects.get_or_create(
                patient=patient,
                medication_name=medication,
                status=MedicationOrder.STATUS_ACTIVE,
                defaults={
                    'admission': admission_map.get(patient_name),
                    'prescribed_by': clinician_user,
                    'dosage': dosage,
                    'frequency': frequency,
                    'route': route,
                    'instructions': 'Monitor vitals and tolerance.',
                },
            )

        lab_orders = [
            ('Amina Rahman', 'HbA1c', LabOrder.PRIORITY_URGENT, LabOrder.STATUS_IN_PROGRESS),
            ('James Carter', 'BNP', LabOrder.PRIORITY_STAT, LabOrder.STATUS_ORDERED),
            ('Samuel Okoro', 'Arterial Blood Gas', LabOrder.PRIORITY_URGENT, LabOrder.STATUS_ORDERED),
        ]
        for patient_name, test_name, priority, status_value in lab_orders:
            patient = patient_map[patient_name]
            lab = LabOrder.objects.filter(patient=patient, test_name=test_name).first()
            if not lab:
                lab = LabOrder.objects.create(
                    patient=patient,
                    admission=admission_map.get(patient_name),
                    ordered_by=clinician_user,
                    test_name=test_name,
                    priority=priority,
                    status=status_value,
                )
            if status_value == LabOrder.STATUS_IN_PROGRESS and not lab.sample_collected_at:
                lab.sample_collected_at = now - timedelta(hours=4)
                lab.save(update_fields=['sample_collected_at'])

        checkins = [
            ('Amina Rahman', 9, 4, False, 182, 91, 126, 'Severe headache and dizziness since morning.'),
            ('James Carter', 7, 5, True, 154, 94, 101, 'Mild fatigue after stair climbing.'),
            ('Priya Nair', 4, 2, False, 118, 98, 84, 'Sleep disruption and low mood this week.'),
            ('Samuel Okoro', 8, 5, True, 164, 90, 132, 'Breathlessness increased during evening.'),
        ]

        for name, symptom, mood, med_taken, sbp, oxy, hr, notes in checkins:
            patient = patient_map[name]
            checkin = PatientCheckIn.objects.filter(patient=patient, notes=notes).first()
            if not checkin:
                checkin = PatientCheckIn.objects.create(
                    patient=patient,
                    submitted_by=outreach_user,
                    symptom_severity=symptom,
                    mood_score=mood,
                    medication_taken=med_taken,
                    systolic_bp=sbp,
                    oxygen_saturation=oxy,
                    heart_rate=hr,
                    notes=notes,
                )

            if symptom >= 8 or (oxy is not None and oxy < 92) or (sbp is not None and sbp >= 180) or (hr is not None and hr >= 130):
                ClinicalAlert.objects.get_or_create(
                    patient=patient,
                    title='Urgent remote monitoring check-in',
                    defaults={
                        'severity': ClinicalAlert.SEVERITY_HIGH,
                        'message': f'Patient reported urgent check-in signals: {notes}',
                    },
                )

        referrals = [
            ('Amina Rahman', 'City Chronic Care Hub', 'Needs intensive disease-management coaching.', ResourceReferral.STATUS_ENROLLED),
            ('Amina Rahman', 'Medication Relief Fund', 'Medication affordability support.', ResourceReferral.STATUS_CONTACTED),
            ('James Carter', 'CareRide Medical Transport', 'Transport barrier for weekly specialist care.', ResourceReferral.STATUS_CONTACTED),
            ('Priya Nair', 'Mind Matters Counseling', 'Postpartum anxiety support.', ResourceReferral.STATUS_ENROLLED),
            ('Samuel Okoro', 'Active Aging Wellness Club', 'Reduce isolation and support guided activity.', ResourceReferral.STATUS_RECOMMENDED),
        ]

        for patient_name, resource_name, reason, status in referrals:
            ResourceReferral.objects.get_or_create(
                patient=patient_map[patient_name],
                resource=resource_map[resource_name],
                defaults={
                    'referred_by': outreach_user,
                    'reason': reason,
                    'status': status,
                    'follow_up_date': (now + timedelta(days=7)).date(),
                },
            )

        workflow_rules = [
            {
                'name': 'High Risk Triage Follow-up',
                'description': 'Automatically schedules a rapid follow-up for high and critical triage outcomes.',
                'event_type': 'triage.assessed',
                'condition': {
                    'all': [
                        {'field': 'patient_id', 'op': 'exists', 'value': True},
                        {'field': 'risk_level', 'op': 'in', 'value': [RiskAssessment.LEVEL_HIGH, RiskAssessment.LEVEL_CRITICAL]},
                    ]
                },
                'action_type': WorkflowRule.ACTION_CREATE_APPOINTMENT,
                'action_config': {
                    'clinician_name': 'Rapid Response Team',
                    'scheduled_in_hours': 24,
                    'reason': 'Automated follow-up for {risk_level} risk score {risk_score}.',
                },
                'priority': 10,
                'active': True,
            },
            {
                'name': 'Critical Check-in Escalation',
                'description': 'Creates critical alerts when remote check-in signals severe deterioration.',
                'event_type': 'checkin.submitted',
                'condition': {
                    'any': [
                        {'field': 'symptom_severity', 'op': 'gte', 'value': 9},
                        {'field': 'oxygen_saturation', 'op': 'lt', 'value': 90},
                    ]
                },
                'action_type': WorkflowRule.ACTION_CREATE_ALERT,
                'action_config': {
                    'severity': ClinicalAlert.SEVERITY_CRITICAL,
                    'title': 'Critical remote check-in workflow escalation',
                    'message': 'Auto escalation for patient {patient_id} due to severe remote monitoring signals.',
                },
                'priority': 20,
                'active': True,
            },
            {
                'name': 'Senior Discharge Referral',
                'description': 'Creates a community wellness referral for discharged senior patients.',
                'event_type': 'admission.discharged',
                'condition': {
                    'all': [
                        {'field': 'patient_age', 'op': 'gte', 'value': 65},
                        {'field': 'patient_id', 'op': 'exists', 'value': True},
                    ]
                },
                'action_type': WorkflowRule.ACTION_CREATE_REFERRAL,
                'action_config': {
                    'resource_category': CommunityResource.CATEGORY_WELLNESS,
                    'reason': 'Automated post-discharge support referral for senior patient.',
                    'status': ResourceReferral.STATUS_RECOMMENDED,
                },
                'priority': 30,
                'active': True,
            },
        ]

        for payload in workflow_rules:
            WorkflowRule.objects.get_or_create(
                name=payload['name'],
                defaults={**payload, 'created_by': admin_user},
            )

        self.stdout.write(self.style.SUCCESS('Demo data seeded successfully.'))
        self.stdout.write('Demo users: admin_demo, clinician_demo, outreach_demo')
        self.stdout.write(f'Demo password: {password}')
        self.stdout.write(
            f'Patients: {Patient.objects.count()} | Admissions: {Admission.objects.count()} | '
            f'Assessments: {RiskAssessment.objects.count()} | Referrals: {ResourceReferral.objects.count()} | '
            f'Workflow rules: {WorkflowRule.objects.count()}'
        )
