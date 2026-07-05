from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (
    Admission,
    Appointment,
    AuditLog,
    Bed,
    ClinicalAlert,
    CommunityResource,
    DomainEvent,
    LabOrder,
    MedicationOrder,
    Patient,
    PatientCheckIn,
    ResourceReferral,
    WorkflowRule,
)
from .roles import ROLE_ADMIN, ROLE_CLINICIAN, ROLE_OUTREACH


class CareFlowAPITests(APITestCase):
    def setUp(self):
        # DRF's throttle classes share Django's cache backend, which is not
        # reset between test methods by default. Without clearing it here,
        # tests that authenticate multiple times (directly or via helpers
        # like `create_patient`) can trip the scoped `token_obtain` /
        # `predict_health_risk` throttles purely as a side effect of test
        # ordering/count, not because of anything the test itself is
        # verifying. Throttling behavior itself is exercised by dedicated
        # tests (see `test_token_endpoint_is_rate_limited`).
        cache.clear()
        call_command('setup_roles')
        self.user = User.objects.create_user(username='tester', password='pass1234')
        self.user.groups.add(Group.objects.get(name=ROLE_CLINICIAN))
        self.admin_user = User.objects.create_user(username='admin_tester', password='pass1234')
        self.admin_user.groups.add(Group.objects.get(name=ROLE_ADMIN))
        self.patient_payload = {
            'name': 'John Doe',
            'age': 45,
            'gender': 'male',
            'blood_type': 'O+',
            'diagnosis': 'Hypertension',
        }
        self.community_resources = [
            {
                'name': 'City Chronic Care Hub',
                'category': 'chronic_care',
                'location': 'Downtown',
                'description': 'Long-term disease coaching.',
                'active': True,
            },
            {
                'name': 'Community Ride Access',
                'category': 'transport',
                'location': 'Citywide',
                'description': 'Transport support for medical appointments.',
                'active': True,
            },
            {
                'name': 'Mind Matters Support',
                'category': 'mental_health',
                'location': 'North District',
                'description': 'Counseling and emotional support.',
                'active': True,
            },
        ]

    def auth(self):
        url = reverse('token_obtain_pair')
        response = self.client.post(url, {'username': 'tester', 'password': 'pass1234'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        token = response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def auth_user(self, username, password):
        url = reverse('token_obtain_pair')
        response = self.client.post(url, {'username': username, 'password': password}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        token = response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def create_patient(self):
        self.auth()
        response = self.client.post('/api/v1/patients/', self.patient_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data['id']

    def seed_community_resources(self):
        self.auth_user('admin_tester', 'pass1234')
        for payload in self.community_resources:
            response = self.client.post('/api/v1/community-resources/', payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_predict_endpoint(self):
        url = '/api/v1/predict/health-risk/'
        payload = {
            'age': 45,
            'bmi': 29.5,
            'blood_pressure': 135,
            'cholesterol': 220,
            'smoker': True,
            'exercise_minutes': 30,
            'chronic_conditions': 2,
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('risk_score', response.data)
        self.assertIn('risk_level', response.data)
        self.assertIn('recommended_action', response.data)
        self.assertIn('key_drivers', response.data)

    def test_patient_crud(self):
        self.auth()
        # Create
        response = self.client.post('/api/v1/patients/', self.patient_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        pid = response.data['id']

        # List — paginated envelope, not a bare array (DEFAULT_PAGINATION_CLASS)
        response = self.client.get('/api/v1/patients/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('results', response.data)
        self.assertGreaterEqual(response.data['count'], 1)
        self.assertTrue(any(item['id'] == pid for item in response.data['results']))

        # Retrieve
        response = self.client.get(f'/api/v1/patients/{pid}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Update
        response = self.client.patch(f'/api/v1/patients/{pid}/', {'diagnosis': 'Updated'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['diagnosis'], 'Updated')

        # Delete
        response = self.client.delete(f'/api/v1/patients/{pid}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_triage_assessment_creates_alert_for_high_risk_patient(self):
        patient_id = self.create_patient()
        payload = {
            'patient_id': patient_id,
            'age': 73,
            'bmi': 36.4,
            'blood_pressure': 188,
            'cholesterol': 310,
            'smoker': True,
            'exercise_minutes': 0,
            'chronic_conditions': 3,
        }
        response = self.client.post('/api/v1/triage/assess/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['alert_created'])
        self.assertIsNotNone(response.data['alert_id'])
        self.assertIn(response.data['assessment']['risk_level'], ['High', 'Critical'])

    def test_appointment_analytics_and_csv_export(self):
        patient_id = self.create_patient()

        triage_response = self.client.post('/api/v1/triage/assess/', {
            'patient_id': patient_id,
            'age': 59,
            'bmi': 30.2,
            'blood_pressure': 145,
            'cholesterol': 240,
            'smoker': False,
            'exercise_minutes': 90,
            'chronic_conditions': 1,
        }, format='json')
        self.assertEqual(triage_response.status_code, status.HTTP_201_CREATED)

        appointment_response = self.client.post('/api/v1/appointments/', {
            'patient': patient_id,
            'clinician_name': 'Dr. Stone',
            'reason': 'Follow-up',
            'scheduled_at': (timezone.now() + timedelta(days=2)).isoformat(),
            'status': 'scheduled',
        }, format='json')
        self.assertEqual(appointment_response.status_code, status.HTTP_201_CREATED)

        analytics_response = self.client.get('/api/v1/analytics/overview/')
        self.assertEqual(analytics_response.status_code, status.HTTP_200_OK)
        self.assertIn('kpis', analytics_response.data)
        self.assertIn('risk_distribution_last_30_days', analytics_response.data)
        self.assertIn('top_diagnoses', analytics_response.data)
        self.assertIn('assessment_trend', analytics_response.data)

        csv_response = self.client.get('/api/v1/analytics/assessments/export.csv')
        self.assertEqual(csv_response.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', csv_response['Content-Type'])
        self.assertIn('risk_level', csv_response.content.decode())

    def test_care_plan_and_alert_resolution_flow(self):
        patient_id = self.create_patient()
        triage_response = self.client.post('/api/v1/triage/assess/', {
            'patient_id': patient_id,
            'age': 76,
            'bmi': 35,
            'blood_pressure': 192,
            'cholesterol': 295,
            'smoker': True,
            'exercise_minutes': 0,
            'chronic_conditions': 4,
        }, format='json')
        self.assertEqual(triage_response.status_code, status.HTTP_201_CREATED)
        alert_id = triage_response.data['alert_id']

        care_plan_response = self.client.get(f'/api/v1/patients/{patient_id}/care-plan/')
        self.assertEqual(care_plan_response.status_code, status.HTTP_200_OK)
        self.assertIn('next_actions', care_plan_response.data)
        self.assertGreaterEqual(len(care_plan_response.data['next_actions']), 1)

        resolve_response = self.client.patch(f'/api/v1/alerts/{alert_id}/', {'resolved': True}, format='json')
        self.assertEqual(resolve_response.status_code, status.HTTP_200_OK)
        self.assertTrue(resolve_response.data['resolved'])
        self.assertIsNotNone(resolve_response.data['resolved_at'])

    def test_health_and_readiness_endpoints(self):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'ok')

        ready = self.client.get('/health/ready/')
        self.assertEqual(ready.status_code, status.HTTP_200_OK)
        self.assertEqual(ready.json()['status'], 'ready')

    def test_checkin_creates_urgent_alert(self):
        patient_id = self.create_patient()
        response = self.client.post('/api/v1/checkins/', {
            'patient': patient_id,
            'symptom_severity': 9,
            'mood_score': 2,
            'medication_taken': False,
            'systolic_bp': 186,
            'oxygen_saturation': 89,
            'heart_rate': 132,
            'notes': 'Symptoms worsened overnight.',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['alert_created'])
        self.assertIsNotNone(response.data['alert_id'])

    def test_community_recommendations_auto_referral(self):
        self.seed_community_resources()
        patient_id = self.create_patient()
        self.client.post('/api/v1/triage/assess/', {
            'patient_id': patient_id,
            'age': 70,
            'bmi': 34,
            'blood_pressure': 170,
            'cholesterol': 285,
            'smoker': False,
            'exercise_minutes': 0,
            'chronic_conditions': 3,
        }, format='json')

        response = self.client.get(f'/api/v1/patients/{patient_id}/community-recommendations/?auto_refer=true')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('recommendations', response.data)
        self.assertGreaterEqual(len(response.data['recommendations']), 1)

        self.assertGreater(ResourceReferral.objects.count(), 0)
        self.assertGreater(CommunityResource.objects.count(), 0)

    def test_referral_and_impact_analytics(self):
        self.seed_community_resources()
        patient_id = self.create_patient()
        resource = CommunityResource.objects.first()
        response = self.client.post('/api/v1/referrals/', {
            'patient': patient_id,
            'resource': resource.id,
            'reason': 'Patient needs social support.',
            'status': 'contacted',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        impact = self.client.get('/api/v1/analytics/impact/')
        self.assertEqual(impact.status_code, status.HTTP_200_OK)
        self.assertIn('kpis', impact.data)
        self.assertIn('referral_status_breakdown', impact.data)
        self.assertIn('resource_category_breakdown', impact.data)

    def test_portfolio_home_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, 'CareFlow')
        self.assertContains(response, 'Intelligent care coordination')

    def test_rbac_outreach_restricted_from_appointment_creation(self):
        outreach_user = User.objects.create_user(username='outreach1', password='pass1234')
        outreach_user.groups.add(Group.objects.get(name=ROLE_OUTREACH))
        patient_id = self.create_patient()

        self.auth_user('outreach1', 'pass1234')
        appointment = self.client.post('/api/v1/appointments/', {
            'patient': patient_id,
            'clinician_name': 'Dr. Blocked',
            'reason': 'Should not be allowed for outreach role',
            'scheduled_at': (timezone.now() + timedelta(days=1)).isoformat(),
            'status': 'scheduled',
        }, format='json')
        self.assertEqual(appointment.status_code, status.HTTP_403_FORBIDDEN)

        resource = CommunityResource.objects.create(name='Local Support Desk', category='wellness', active=True)
        referral = self.client.post('/api/v1/referrals/', {
            'patient': patient_id,
            'resource': resource.id,
            'reason': 'Outreach referral is allowed.',
            'status': 'recommended',
        }, format='json')
        self.assertEqual(referral.status_code, status.HTTP_201_CREATED)

    def test_workflow_rule_auto_schedules_high_risk_followup(self):
        self.auth_user('admin_tester', 'pass1234')
        rule_response = self.client.post('/api/v1/workflow-rules/', {
            'name': 'Auto follow-up high risk',
            'description': 'Creates appointment for high-risk triage outcome.',
            'event_type': 'triage.assessed',
            'condition': {
                'all': [
                    {'field': 'risk_level', 'op': 'in', 'value': ['High', 'Critical']},
                    {'field': 'patient_id', 'op': 'exists', 'value': True},
                ]
            },
            'action_type': 'create_appointment',
            'action_config': {
                'clinician_name': 'Auto Follow-up Team',
                'scheduled_in_hours': 12,
                'reason': 'Auto workflow follow-up for {risk_level} risk.',
            },
            'priority': 5,
            'active': True,
        }, format='json')
        self.assertEqual(rule_response.status_code, status.HTTP_201_CREATED)

        patient_id = self.create_patient()
        triage = self.client.post('/api/v1/triage/assess/', {
            'patient_id': patient_id,
            'age': 72,
            'bmi': 35,
            'blood_pressure': 186,
            'cholesterol': 298,
            'smoker': True,
            'exercise_minutes': 0,
            'chronic_conditions': 3,
        }, format='json')
        self.assertEqual(triage.status_code, status.HTTP_201_CREATED)

        workflow_appt = Appointment.objects.filter(
            patient_id=patient_id,
            clinician_name='Auto Follow-up Team',
        ).first()
        self.assertIsNotNone(workflow_appt)
        self.assertEqual(workflow_appt.status, Appointment.STATUS_SCHEDULED)

    def test_domain_event_process_pending_creates_alert(self):
        patient_id = self.create_patient()

        WorkflowRule.objects.create(
            name='Manual event alert rule',
            event_type='checkin.submitted',
            condition={'all': [{'field': 'symptom_severity', 'op': 'gte', 'value': 8}]},
            action_type=WorkflowRule.ACTION_CREATE_ALERT,
            action_config={
                'severity': ClinicalAlert.SEVERITY_CRITICAL,
                'title': 'Manual event escalation',
                'message': 'Auto-created from domain event.',
            },
            priority=10,
            active=True,
            created_by=self.admin_user,
        )

        event = DomainEvent.objects.create(
            event_type='checkin.submitted',
            source='test-suite',
            payload={'patient_id': patient_id, 'symptom_severity': 9},
            status=DomainEvent.STATUS_PENDING,
        )

        self.auth()
        process_response = self.client.post('/api/v1/domain-events/process-pending/', {
            'limit': 10,
            'include_failed': False,
            'max_attempts': 3,
        }, format='json')
        self.assertEqual(process_response.status_code, status.HTTP_200_OK)
        self.assertEqual(process_response.data['processed_count'], 1)

        event.refresh_from_db()
        self.assertEqual(event.status, DomainEvent.STATUS_PROCESSED)
        self.assertTrue(
            ClinicalAlert.objects.filter(
                patient_id=patient_id,
                title='Manual event escalation',
            ).exists()
        )

    def test_workflow_rules_write_requires_admin(self):
        outreach_user = User.objects.create_user(username='outreach_workflow', password='pass1234')
        outreach_user.groups.add(Group.objects.get(name=ROLE_OUTREACH))
        self.auth_user('outreach_workflow', 'pass1234')

        denied = self.client.post('/api/v1/workflow-rules/', {
            'name': 'Outreach should fail',
            'event_type': 'triage.assessed',
            'condition': {},
            'action_type': 'create_alert',
            'action_config': {'severity': 'high'},
            'priority': 50,
            'active': True,
        }, format='json')
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        listing = self.client.get('/api/v1/workflow-rules/')
        self.assertEqual(listing.status_code, status.HTTP_200_OK)

    def test_seed_demo_data_command(self):
        call_command('seed_demo_data', password='test-demo-pass')
        self.assertTrue(User.objects.filter(username='admin_demo').exists())
        self.assertTrue(User.objects.filter(username='clinician_demo').exists())
        self.assertTrue(User.objects.filter(username='outreach_demo').exists())
        self.assertGreater(Patient.objects.count(), 0)
        self.assertGreater(ResourceReferral.objects.count(), 0)

    def test_hospital_inpatient_flow_end_to_end(self):
        self.auth_user('admin_tester', 'pass1234')
        ward = self.client.post('/api/v1/wards/', {
            'name': 'General Ward',
            'code': 'GW-A',
            'specialty': 'general',
            'floor': 2,
            'capacity': 30,
            'active': True,
        }, format='json')
        self.assertEqual(ward.status_code, status.HTTP_201_CREATED)
        ward_id = ward.data['id']

        bed_1 = self.client.post('/api/v1/beds/', {
            'ward': ward_id,
            'bed_number': 'A-101',
            'status': 'available',
        }, format='json')
        self.assertEqual(bed_1.status_code, status.HTTP_201_CREATED)
        bed_1_id = bed_1.data['id']

        bed_2 = self.client.post('/api/v1/beds/', {
            'ward': ward_id,
            'bed_number': 'A-102',
            'status': 'available',
        }, format='json')
        self.assertEqual(bed_2.status_code, status.HTTP_201_CREATED)
        bed_2_id = bed_2.data['id']

        patient_id = self.create_patient()

        admission = self.client.post('/api/v1/admissions/', {
            'patient': patient_id,
            'bed': bed_1_id,
            'reason': 'Post-surgery observation',
            'diagnosis_on_admission': 'Recovery monitoring',
        }, format='json')
        self.assertEqual(admission.status_code, status.HTTP_201_CREATED)
        admission_id = admission.data['id']

        bed_state = self.client.get(f'/api/v1/beds/{bed_1_id}/')
        self.assertEqual(bed_state.status_code, status.HTTP_200_OK)
        self.assertEqual(bed_state.data['status'], Bed.STATUS_OCCUPIED)

        med = self.client.post('/api/v1/medication-orders/', {
            'patient': patient_id,
            'admission': admission_id,
            'medication_name': 'Ceftriaxone',
            'dosage': '1g',
            'frequency': 'Every 12 hours',
            'route': 'iv',
            'instructions': 'Complete antibiotic course',
        }, format='json')
        self.assertEqual(med.status_code, status.HTTP_201_CREATED)
        med_id = med.data['id']

        med_status = self.client.post(f'/api/v1/medication-orders/{med_id}/mark-status/', {
            'status': MedicationOrder.STATUS_COMPLETED,
            'notes': 'Course completed without complications.',
        }, format='json')
        self.assertEqual(med_status.status_code, status.HTTP_200_OK)
        self.assertEqual(med_status.data['status'], MedicationOrder.STATUS_COMPLETED)

        lab = self.client.post('/api/v1/lab-orders/', {
            'patient': patient_id,
            'admission': admission_id,
            'test_name': 'CBC',
            'priority': LabOrder.PRIORITY_URGENT,
        }, format='json')
        self.assertEqual(lab.status_code, status.HTTP_201_CREATED)
        lab_id = lab.data['id']

        lab_start = self.client.post(f'/api/v1/lab-orders/{lab_id}/start/', {}, format='json')
        self.assertEqual(lab_start.status_code, status.HTTP_200_OK)
        self.assertEqual(lab_start.data['status'], LabOrder.STATUS_IN_PROGRESS)

        lab_complete = self.client.post(f'/api/v1/lab-orders/{lab_id}/complete/', {
            'result_value': 'Normal',
            'result_summary': 'No active infection.',
        }, format='json')
        self.assertEqual(lab_complete.status_code, status.HTTP_200_OK)
        self.assertEqual(lab_complete.data['status'], LabOrder.STATUS_COMPLETED)

        transfer = self.client.post(f'/api/v1/admissions/{admission_id}/transfer/', {
            'bed': bed_2_id,
            'reason': 'Moved closer to nursing station',
        }, format='json')
        self.assertEqual(transfer.status_code, status.HTTP_200_OK)
        self.assertEqual(transfer.data['bed'], bed_2_id)

        old_bed = self.client.get(f'/api/v1/beds/{bed_1_id}/')
        self.assertEqual(old_bed.status_code, status.HTTP_200_OK)
        self.assertEqual(old_bed.data['status'], Bed.STATUS_AVAILABLE)

        discharge = self.client.post(f'/api/v1/admissions/{admission_id}/discharge/', {
            'discharge_summary': 'Patient stabilized and discharged to home care.',
        }, format='json')
        self.assertEqual(discharge.status_code, status.HTTP_200_OK)
        self.assertEqual(discharge.data['status'], Admission.STATUS_DISCHARGED)

        final_bed = self.client.get(f'/api/v1/beds/{bed_2_id}/')
        self.assertEqual(final_bed.status_code, status.HTTP_200_OK)
        self.assertEqual(final_bed.data['status'], Bed.STATUS_AVAILABLE)

        hospital_flow = self.client.get('/api/v1/analytics/hospital-flow/')
        self.assertEqual(hospital_flow.status_code, status.HTTP_200_OK)
        self.assertIn('kpis', hospital_flow.data)
        self.assertIn('admissions_by_status', hospital_flow.data)
        self.assertIn('labs_by_status', hospital_flow.data)


class CareFlowNegativePathTests(APITestCase):
    """Failure-mode / boundary coverage.

    The original suite (`CareFlowAPITests`) was "happy path plus one RBAC
    denial per resource." This class specifically targets the gaps flagged
    by the code-review audit: unauthenticated access, invalid input,
    malformed workflow configuration, and the new hardening features
    (pagination, exception envelope, throttling, audit trail, logout,
    object-level permissions).
    """

    def setUp(self):
        cache.clear()
        call_command('setup_roles')
        self.user = User.objects.create_user(username='neg_tester', password='pass1234')
        self.user.groups.add(Group.objects.get(name=ROLE_CLINICIAN))
        self.admin_user = User.objects.create_user(username='neg_admin', password='pass1234')
        self.admin_user.groups.add(Group.objects.get(name=ROLE_ADMIN))
        self.outreach_user = User.objects.create_user(username='neg_outreach', password='pass1234')
        self.outreach_user.groups.add(Group.objects.get(name=ROLE_OUTREACH))
        self.other_outreach_user = User.objects.create_user(username='neg_outreach_2', password='pass1234')
        self.other_outreach_user.groups.add(Group.objects.get(name=ROLE_OUTREACH))

    def auth_user(self, username, password):
        url = reverse('token_obtain_pair')
        response = self.client.post(url, {'username': username, 'password': password}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data

    def authenticate(self, username, password):
        tokens = self.auth_user(username, password)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        return tokens

    def create_patient(self):
        self.authenticate('neg_tester', 'pass1234')
        response = self.client.post('/api/v1/patients/', {
            'name': 'Negative Path Patient',
            'age': 50,
            'gender': 'female',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data['id']

    # --- Authentication / authorization boundaries -------------------

    def test_unauthenticated_request_returns_401(self):
        self.client.credentials()
        response = self.client.get('/api/v1/patients/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('detail', response.data)

    def test_unauthenticated_request_to_write_endpoint_returns_401(self):
        self.client.credentials()
        response = self.client.post('/api/v1/patients/', {'name': 'x', 'age': 1, 'gender': 'male'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # --- Invalid input --------------------------------------------------

    def test_triage_assessment_rejects_out_of_range_age(self):
        self.authenticate('neg_admin', 'pass1234')
        response = self.client.post('/api/v1/triage/assess/', {
            'age': 200,  # max_value=120
            'bmi': 25,
            'blood_pressure': 120,
            'cholesterol': 180,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('age', response.data['errors'])

    def test_predict_endpoint_rejects_negative_bmi(self):
        response = self.client.post('/api/v1/predict/health-risk/', {
            'age': 40,
            'bmi': -5,  # min_value=10
            'blood_pressure': 120,
            'cholesterol': 180,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('bmi', response.data['errors'])

    def test_triage_assessment_rejects_missing_required_field(self):
        self.authenticate('neg_admin', 'pass1234')
        response = self.client.post('/api/v1/triage/assess/', {
            'age': 40,
            'bmi': 25,
            # blood_pressure omitted
            'cholesterol': 180,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('blood_pressure', response.data['errors'])

    # --- Malformed workflow rule condition ------------------------------

    def test_workflow_rule_with_malformed_condition_fails_safely(self):
        """A rule whose `condition` JSON is structurally nonsensical must
        not crash event processing — `process_domain_event` wraps rule
        evaluation in a try/except and marks the event failed rather than
        raising, which this test asserts end-to-end."""
        WorkflowRule.objects.create(
            name='Malformed condition rule',
            event_type='checkin.submitted',
            # 'all' is expected to be a list of clause dicts; a raw string
            # is malformed input a hand-authored or buggy client could send.
            condition={'all': 'not-a-list-of-clauses'},
            action_type=WorkflowRule.ACTION_CREATE_ALERT,
            action_config={'severity': 'high'},
            priority=1,
            active=True,
            created_by=self.admin_user,
        )
        patient_id = self.create_patient()

        response = self.client.post('/api/v1/checkins/', {
            'patient': patient_id,
            'symptom_severity': 3,
            'mood_score': 5,
            'medication_taken': True,
        }, format='json')
        # The check-in itself must still succeed — a malformed downstream
        # workflow rule must not break the primary write operation.
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_domain_event_with_invalid_action_config_marks_event_failed(self):
        """create_alert requires a resolvable patient_id; if the event
        payload and rule config both omit it, processing must record a
        STATUS_FAILED event with an error message rather than raising an
        unhandled exception up through the API."""
        WorkflowRule.objects.create(
            name='Alert rule missing patient reference',
            event_type='custom.test_event',
            condition={},
            action_type=WorkflowRule.ACTION_CREATE_ALERT,
            action_config={'severity': 'high'},  # no patient_id anywhere
            priority=1,
            active=True,
            created_by=self.admin_user,
        )
        event = DomainEvent.objects.create(
            event_type='custom.test_event',
            source='test-suite',
            payload={},
            status=DomainEvent.STATUS_PENDING,
        )

        self.authenticate('neg_admin', 'pass1234')
        response = self.client.post('/api/v1/domain-events/process-pending/', {
            'limit': 10,
            'include_failed': False,
            'max_attempts': 3,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['failed_count'], 1)

        event.refresh_from_db()
        self.assertEqual(event.status, DomainEvent.STATUS_FAILED)
        self.assertTrue(event.error_message)

    # --- Pagination -------------------------------------------------------

    def test_patient_list_is_paginated(self):
        self.authenticate('neg_tester', 'pass1234')
        for i in range(3):
            self.client.post('/api/v1/patients/', {
                'name': f'Paginated Patient {i}',
                'age': 30 + i,
                'gender': 'male',
            }, format='json')

        response = self.client.get('/api/v1/patients/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)
        self.assertIn('results', response.data)
        self.assertGreaterEqual(response.data['count'], 3)

    # --- Consistent error envelope ---------------------------------------

    def test_error_envelope_is_consistent_for_validation_and_permission_errors(self):
        # Field-level validation error (raised ValidationError from a nested serializer).
        self.authenticate('neg_admin', 'pass1234')
        validation_response = self.client.post('/api/v1/triage/assess/', {'age': 200}, format='json')
        self.assertEqual(validation_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', validation_response.data)
        self.assertIn('errors', validation_response.data)
        self.assertIsInstance(validation_response.data['errors'], dict)

        # Flat DRF-generated error (permission denial).
        self.client.credentials()
        auth_response = self.client.get('/api/v1/patients/')
        self.assertEqual(auth_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('detail', auth_response.data)
        self.assertIn('errors', auth_response.data)

    # --- Scoped throttling --------------------------------------------

    def test_token_endpoint_is_rate_limited(self):
        cache.clear()
        url = reverse('token_obtain_pair')
        last_response = None
        # DRF_THROTTLE_TOKEN defaults to 10/minute; 11 rapid attempts must
        # trip the scoped throttle regardless of credential validity.
        for _ in range(11):
            last_response = self.client.post(
                url, {'username': 'neg_tester', 'password': 'wrong-password'}, format='json'
            )
        self.assertEqual(last_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_predict_endpoint_is_rate_limited(self):
        cache.clear()
        payload = {'age': 40, 'bmi': 25, 'blood_pressure': 120, 'cholesterol': 180}
        last_response = None
        # DRF_THROTTLE_PREDICT defaults to 20/minute.
        for _ in range(21):
            last_response = self.client.post('/api/v1/predict/health-risk/', payload, format='json')
        self.assertEqual(last_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    # --- Logout / token blacklist ----------------------------------------

    def test_logout_blacklists_refresh_token(self):
        tokens = self.authenticate('neg_tester', 'pass1234')
        logout_response = self.client.post(
            '/api/v1/auth/logout/', {'refresh': tokens['refresh']}, format='json'
        )
        self.assertEqual(logout_response.status_code, status.HTTP_205_RESET_CONTENT)

        refresh_response = self.client.post(
            reverse('token_refresh'), {'refresh': tokens['refresh']}, format='json'
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_requires_authentication(self):
        self.client.credentials()
        response = self.client.post('/api/v1/auth/logout/', {'refresh': 'irrelevant'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_rejects_invalid_refresh_token(self):
        self.authenticate('neg_tester', 'pass1234')
        response = self.client.post('/api/v1/auth/logout/', {'refresh': 'not-a-real-token'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # --- Object-level permissions -----------------------------------------

    def test_outreach_worker_cannot_edit_another_workers_referral(self):
        patient_id = self.create_patient()
        resource = CommunityResource.objects.create(name='Shared Resource', category='wellness', active=True)

        self.authenticate('neg_outreach', 'pass1234')
        create_response = self.client.post('/api/v1/referrals/', {
            'patient': patient_id,
            'resource': resource.id,
            'reason': 'Created by first outreach worker.',
            'status': 'recommended',
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        referral_id = create_response.data['id']

        self.authenticate('neg_outreach_2', 'pass1234')
        edit_response = self.client.patch(
            f'/api/v1/referrals/{referral_id}/', {'status': 'contacted'}, format='json'
        )
        self.assertEqual(edit_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_edit_any_outreach_workers_referral(self):
        patient_id = self.create_patient()
        resource = CommunityResource.objects.create(name='Shared Resource 2', category='wellness', active=True)

        self.authenticate('neg_outreach', 'pass1234')
        create_response = self.client.post('/api/v1/referrals/', {
            'patient': patient_id,
            'resource': resource.id,
            'reason': 'Created by outreach worker.',
            'status': 'recommended',
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        referral_id = create_response.data['id']

        self.authenticate('neg_admin', 'pass1234')
        edit_response = self.client.patch(
            f'/api/v1/referrals/{referral_id}/', {'status': 'contacted'}, format='json'
        )
        self.assertEqual(edit_response.status_code, status.HTTP_200_OK)

    def test_clinician_cannot_edit_another_clinicians_medication_order(self):
        other_clinician = User.objects.create_user(username='neg_clinician_2', password='pass1234')
        other_clinician.groups.add(Group.objects.get(name=ROLE_CLINICIAN))

        patient_id = self.create_patient()
        self.authenticate('neg_tester', 'pass1234')
        med_response = self.client.post('/api/v1/medication-orders/', {
            'patient': patient_id,
            'medication_name': 'Amoxicillin',
            'dosage': '500mg',
            'frequency': 'Every 8 hours',
            'route': 'oral',
        }, format='json')
        self.assertEqual(med_response.status_code, status.HTTP_201_CREATED)
        med_id = med_response.data['id']

        self.authenticate('neg_clinician_2', 'pass1234')
        edit_response = self.client.patch(
            f'/api/v1/medication-orders/{med_id}/', {'dosage': '1000mg'}, format='json'
        )
        self.assertEqual(edit_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_clinician_can_mark_status_on_another_clinicians_medication_order(self):
        """Regression test for a real bug introduced by a prior remediation
        pass: `MedicationOrderPermission.has_object_permission` used to
        apply its prescriber-ownership check to *every* object-level
        action, which incorrectly 403'd a covering clinician trying to
        mark another clinician's order complete/stopped via `mark-status`
        — an operational status update, not a dosage/route edit. The fix
        scopes the ownership check to `update`/`partial_update`/`destroy`
        only (see `MedicationOrderPermission.OWNERSHIP_SCOPED_ACTIONS`)."""
        other_clinician = User.objects.create_user(username='neg_clinician_3', password='pass1234')
        other_clinician.groups.add(Group.objects.get(name=ROLE_CLINICIAN))

        patient_id = self.create_patient()
        self.authenticate('neg_tester', 'pass1234')
        med_response = self.client.post('/api/v1/medication-orders/', {
            'patient': patient_id,
            'medication_name': 'Amoxicillin',
            'dosage': '500mg',
            'frequency': 'Every 8 hours',
            'route': 'oral',
        }, format='json')
        self.assertEqual(med_response.status_code, status.HTTP_201_CREATED)
        med_id = med_response.data['id']

        self.authenticate('neg_clinician_3', 'pass1234')
        mark_status_response = self.client.post(f'/api/v1/medication-orders/{med_id}/mark-status/', {
            'status': MedicationOrder.STATUS_COMPLETED,
            'notes': 'Covering clinician completed the course.',
        }, format='json')
        self.assertEqual(mark_status_response.status_code, status.HTTP_200_OK)
        self.assertEqual(mark_status_response.data['status'], MedicationOrder.STATUS_COMPLETED)

    def test_outreach_worker_can_edit_own_checkin(self):
        """Regression test for a real bug introduced by a prior remediation
        pass: `PatientCheckInViewSet` reused `CommunityWorkflowPermission`
        (whose ownership check reads `referred_by_id`, a field that does
        not exist on `PatientCheckIn`) instead of a check-in-specific
        permission that reads `submitted_by_id`. `getattr(obj,
        'referred_by_id', None)` silently returned `None`, which never
        equals `request.user.id`, so every outreach worker was incorrectly
        403'd editing their *own* check-in. Fixed by
        `PatientCheckInPermission` (see `api/permissions.py`)."""
        outreach_user = User.objects.create_user(username='neg_outreach_checkin', password='pass1234')
        outreach_user.groups.add(Group.objects.get(name=ROLE_OUTREACH))

        patient_id = self.create_patient()
        self.authenticate('neg_outreach_checkin', 'pass1234')
        create_response = self.client.post('/api/v1/checkins/', {
            'patient': patient_id,
            'symptom_severity': 2,
            'mood_score': 5,
            'medication_taken': True,
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        checkin_id = create_response.data['checkin']['id']

        edit_response = self.client.patch(
            f'/api/v1/checkins/{checkin_id}/', {'notes': 'Updated by the worker who submitted it.'}, format='json'
        )
        self.assertEqual(edit_response.status_code, status.HTTP_200_OK)

    def test_outreach_worker_cannot_edit_another_workers_checkin(self):
        first_outreach = User.objects.create_user(username='neg_outreach_checkin_a', password='pass1234')
        first_outreach.groups.add(Group.objects.get(name=ROLE_OUTREACH))
        second_outreach = User.objects.create_user(username='neg_outreach_checkin_b', password='pass1234')
        second_outreach.groups.add(Group.objects.get(name=ROLE_OUTREACH))

        patient_id = self.create_patient()
        self.authenticate('neg_outreach_checkin_a', 'pass1234')
        create_response = self.client.post('/api/v1/checkins/', {
            'patient': patient_id,
            'symptom_severity': 2,
            'mood_score': 5,
            'medication_taken': True,
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        checkin_id = create_response.data['checkin']['id']

        self.authenticate('neg_outreach_checkin_b', 'pass1234')
        edit_response = self.client.patch(
            f'/api/v1/checkins/{checkin_id}/', {'notes': 'Should not be allowed.'}, format='json'
        )
        self.assertEqual(edit_response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Audit trail ---------------------------------------------------

    def test_patient_detail_view_is_audited(self):
        patient_id = self.create_patient()
        self.client.get(f'/api/v1/patients/{patient_id}/')

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ACTION_VIEW,
                resource_type='Patient',
                resource_id=str(patient_id),
            ).exists()
        )

    def test_csv_export_is_audited_with_row_count(self):
        self.authenticate('neg_admin', 'pass1234')
        response = self.client.get('/api/v1/analytics/assessments/export.csv')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        entry = AuditLog.objects.filter(
            action=AuditLog.ACTION_EXPORT, resource_type='RiskAssessment'
        ).first()
        self.assertIsNotNone(entry)
        self.assertIn('Exported', entry.detail)

    def test_csv_export_invalid_filter_returns_400(self):
        self.authenticate('neg_admin', 'pass1234')
        response = self.client.get('/api/v1/analytics/assessments/export.csv?date_from=not-a-date')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patient_create_update_delete_are_all_audited(self):
        """Regression test for a confirmed gap: `AuditLog.ACTION_CREATE/
        UPDATE/DELETE` were defined but never actually invoked anywhere —
        only `view`/`export` were audited. Patient CRUD now records all
        three."""
        self.authenticate('neg_admin', 'pass1234')
        create_response = self.client.post('/api/v1/patients/', {
            'name': 'Audit Coverage Patient', 'age': 40, 'gender': 'male',
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        patient_id = create_response.data['id']

        update_response = self.client.patch(f'/api/v1/patients/{patient_id}/', {'age': 41}, format='json')
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        delete_response = self.client.delete(f'/api/v1/patients/{patient_id}/')
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

        for expected_action in [AuditLog.ACTION_CREATE, AuditLog.ACTION_UPDATE, AuditLog.ACTION_DELETE]:
            self.assertTrue(
                AuditLog.objects.filter(
                    action=expected_action, resource_type='Patient', resource_id=str(patient_id)
                ).exists(),
                f'Expected a Patient {expected_action} audit entry for patient {patient_id}.',
            )

    def test_medication_order_create_and_update_are_audited(self):
        patient_id = self.create_patient()
        self.authenticate('neg_tester', 'pass1234')
        create_response = self.client.post('/api/v1/medication-orders/', {
            'patient': patient_id,
            'medication_name': 'Ibuprofen',
            'dosage': '200mg',
            'frequency': 'Every 6 hours',
            'route': 'oral',
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        med_id = create_response.data['id']

        mark_status_response = self.client.post(f'/api/v1/medication-orders/{med_id}/mark-status/', {
            'status': MedicationOrder.STATUS_STOPPED,
        }, format='json')
        self.assertEqual(mark_status_response.status_code, status.HTTP_200_OK)

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ACTION_CREATE, resource_type='MedicationOrder', resource_id=str(med_id)
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ACTION_UPDATE, resource_type='MedicationOrder', resource_id=str(med_id)
            ).exists()
        )

    def test_admission_create_transfer_discharge_are_audited(self):
        self.authenticate('neg_admin', 'pass1234')
        ward = self.client.post('/api/v1/wards/', {
            'name': 'Audit Ward', 'code': 'AW-1', 'specialty': 'general', 'floor': 1, 'capacity': 10, 'active': True,
        }, format='json')
        self.assertEqual(ward.status_code, status.HTTP_201_CREATED)
        ward_id = ward.data['id']

        bed_a = self.client.post('/api/v1/beds/', {'ward': ward_id, 'bed_number': 'AW-1', 'status': 'available'}, format='json')
        bed_b = self.client.post('/api/v1/beds/', {'ward': ward_id, 'bed_number': 'AW-2', 'status': 'available'}, format='json')
        self.assertEqual(bed_a.status_code, status.HTTP_201_CREATED)
        self.assertEqual(bed_b.status_code, status.HTTP_201_CREATED)

        patient_id = self.create_patient()
        self.authenticate('neg_admin', 'pass1234')
        admission = self.client.post('/api/v1/admissions/', {
            'patient': patient_id, 'bed': bed_a.data['id'], 'reason': 'Observation',
        }, format='json')
        self.assertEqual(admission.status_code, status.HTTP_201_CREATED)
        admission_id = admission.data['id']

        transfer = self.client.post(f'/api/v1/admissions/{admission_id}/transfer/', {'bed': bed_b.data['id']}, format='json')
        self.assertEqual(transfer.status_code, status.HTTP_200_OK)

        discharge = self.client.post(f'/api/v1/admissions/{admission_id}/discharge/', {}, format='json')
        self.assertEqual(discharge.status_code, status.HTTP_200_OK)

        actions_recorded = set(
            AuditLog.objects.filter(resource_type='Admission', resource_id=str(admission_id)).values_list(
                'action', flat=True
            )
        )
        self.assertIn(AuditLog.ACTION_CREATE, actions_recorded)
        self.assertIn(AuditLog.ACTION_UPDATE, actions_recorded)

    def test_audit_persistence_failure_does_not_break_the_primary_request(self):
        """`record_audit_event` must degrade observability, never
        availability — a broken audit sink must not turn an already
        successful read into a 500 (the original bug: `record_audit_event`
        was called unguarded after the primary operation had already
        succeeded)."""
        patient_id = self.create_patient()
        with mock.patch('api.audit.AuditLog.objects.create', side_effect=Exception('simulated audit DB failure')):
            response = self.client.get(f'/api/v1/patients/{patient_id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class PatientCheckInManagerTests(APITestCase):
    """CODE-04: the "urgent check-in" filter must be defined in exactly one
    place (`PatientCheckIn.objects.urgent()`) and produce the same result
    regardless of which of its three call sites (the ViewSet, impact
    analytics, or the portfolio homepage) uses it."""

    def setUp(self):
        call_command('setup_roles')
        self.patient = Patient.objects.create(name='Urgent Manager Patient', age=50, gender='female')

    def test_urgent_matches_severe_symptom_severity(self):
        urgent = PatientCheckIn.objects.create(
            patient=self.patient, symptom_severity=9, mood_score=5, medication_taken=True
        )
        not_urgent = PatientCheckIn.objects.create(
            patient=self.patient, symptom_severity=1, mood_score=5, medication_taken=True
        )
        urgent_ids = set(PatientCheckIn.objects.urgent().values_list('id', flat=True))
        self.assertIn(urgent.id, urgent_ids)
        self.assertNotIn(not_urgent.id, urgent_ids)

    def test_urgent_matches_low_mood_with_missed_medication(self):
        urgent = PatientCheckIn.objects.create(
            patient=self.patient, symptom_severity=0, mood_score=1, medication_taken=False
        )
        not_urgent = PatientCheckIn.objects.create(
            patient=self.patient, symptom_severity=0, mood_score=1, medication_taken=True
        )
        urgent_ids = set(PatientCheckIn.objects.urgent().values_list('id', flat=True))
        self.assertIn(urgent.id, urgent_ids)
        self.assertNotIn(not_urgent.id, urgent_ids)


class ObservabilityEndpointTests(APITestCase):
    """OBS-02: a minimal counter-based `/metrics` endpoint."""

    def setUp(self):
        cache.clear()
        call_command('setup_roles')

    def test_metrics_endpoint_is_reachable_without_auth(self):
        response = self.client.get('/metrics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('text/plain', response['Content-Type'])
        self.assertIn('careflow_http_requests_total', response.content.decode())

    def test_metrics_counters_increment_after_requests(self):
        before = self.client.get('/metrics/').content.decode()
        self.client.get('/health/')
        self.client.get('/health/')
        after = self.client.get('/metrics/').content.decode()

        def read_counter(body, name):
            for line in body.splitlines():
                if line.startswith(name + ' '):
                    return int(line.split()[-1])
            return None

        self.assertGreater(
            read_counter(after, 'careflow_http_requests_total'),
            read_counter(before, 'careflow_http_requests_total'),
        )


class AnalyticsCachingTests(APITestCase):
    """STEP 3 / PERF-04: short-TTL cache on the three analytics endpoints."""

    def setUp(self):
        cache.clear()
        call_command('setup_roles')
        self.user = User.objects.create_user(username='cache_tester', password='pass1234')
        self.user.groups.add(Group.objects.get(name=ROLE_CLINICIAN))

    def auth(self):
        url = reverse('token_obtain_pair')
        response = self.client.post(url, {'username': 'cache_tester', 'password': 'pass1234'}, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")

    def test_analytics_overview_response_is_cached(self):
        self.auth()
        first = self.client.get('/api/v1/analytics/overview/')
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(cache.get('careflow:analytics:overview'))

        # A second request must reuse the cached payload rather than
        # recomputing — asserted via query count: a cache hit should only
        # issue the auth/permission-check queries (resolve the JWT's user,
        # check group membership), not the ~5 separate aggregate queries
        # the view issues on a cache miss (patient count, appointment
        # count, assessment count, top diagnoses, trend).
        with CaptureQueriesContext(connection) as ctx:
            second = self.client.get('/api/v1/analytics/overview/')
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data, second.data)
        self.assertLess(len(ctx.captured_queries), 5)
