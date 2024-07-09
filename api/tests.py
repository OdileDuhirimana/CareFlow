from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

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
    ResourceReferral,
    WorkflowRule,
)
from .roles import ROLE_ADMIN, ROLE_CLINICIAN, ROLE_OUTREACH


class CareFlowAPITests(APITestCase):
    def setUp(self):
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
        response = self.client.post('/api/patients/', self.patient_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data['id']

    def seed_community_resources(self):
        self.auth_user('admin_tester', 'pass1234')
        for payload in self.community_resources:
            response = self.client.post('/api/community-resources/', payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_predict_endpoint(self):
        url = '/api/predict/health-risk/'
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
        response = self.client.post('/api/patients/', self.patient_payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        pid = response.data['id']

        # List
        response = self.client.get('/api/patients/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data) >= 1)

        # Retrieve
        response = self.client.get(f'/api/patients/{pid}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Update
        response = self.client.patch(f'/api/patients/{pid}/', {'diagnosis': 'Updated'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['diagnosis'], 'Updated')

        # Delete
        response = self.client.delete(f'/api/patients/{pid}/')
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
        response = self.client.post('/api/triage/assess/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['alert_created'])
        self.assertIsNotNone(response.data['alert_id'])
        self.assertIn(response.data['assessment']['risk_level'], ['High', 'Critical'])

    def test_appointment_analytics_and_csv_export(self):
        patient_id = self.create_patient()

        triage_response = self.client.post('/api/triage/assess/', {
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

        appointment_response = self.client.post('/api/appointments/', {
            'patient': patient_id,
            'clinician_name': 'Dr. Stone',
            'reason': 'Follow-up',
            'scheduled_at': (timezone.now() + timedelta(days=2)).isoformat(),
            'status': 'scheduled',
        }, format='json')
        self.assertEqual(appointment_response.status_code, status.HTTP_201_CREATED)

        analytics_response = self.client.get('/api/analytics/overview/')
        self.assertEqual(analytics_response.status_code, status.HTTP_200_OK)
        self.assertIn('kpis', analytics_response.data)
        self.assertIn('risk_distribution_last_30_days', analytics_response.data)
        self.assertIn('top_diagnoses', analytics_response.data)
        self.assertIn('assessment_trend', analytics_response.data)

        csv_response = self.client.get('/api/analytics/assessments/export.csv')
        self.assertEqual(csv_response.status_code, status.HTTP_200_OK)
        self.assertIn('text/csv', csv_response['Content-Type'])
        self.assertIn('risk_level', csv_response.content.decode())

    def test_care_plan_and_alert_resolution_flow(self):
        patient_id = self.create_patient()
        triage_response = self.client.post('/api/triage/assess/', {
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

        care_plan_response = self.client.get(f'/api/patients/{patient_id}/care-plan/')
        self.assertEqual(care_plan_response.status_code, status.HTTP_200_OK)
        self.assertIn('next_actions', care_plan_response.data)
        self.assertGreaterEqual(len(care_plan_response.data['next_actions']), 1)

        resolve_response = self.client.patch(f'/api/alerts/{alert_id}/', {'resolved': True}, format='json')
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
        response = self.client.post('/api/checkins/', {
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
        self.client.post('/api/triage/assess/', {
            'patient_id': patient_id,
            'age': 70,
            'bmi': 34,
            'blood_pressure': 170,
            'cholesterol': 285,
            'smoker': False,
            'exercise_minutes': 0,
            'chronic_conditions': 3,
        }, format='json')

        response = self.client.get(f'/api/patients/{patient_id}/community-recommendations/?auto_refer=true')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('recommendations', response.data)
        self.assertGreaterEqual(len(response.data['recommendations']), 1)

        self.assertGreater(ResourceReferral.objects.count(), 0)
        self.assertGreater(CommunityResource.objects.count(), 0)

    def test_referral_and_impact_analytics(self):
        self.seed_community_resources()
        patient_id = self.create_patient()
        resource = CommunityResource.objects.first()
        response = self.client.post('/api/referrals/', {
            'patient': patient_id,
            'resource': resource.id,
            'reason': 'Patient needs social support.',
            'status': 'contacted',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        impact = self.client.get('/api/analytics/impact/')
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
        appointment = self.client.post('/api/appointments/', {
            'patient': patient_id,
            'clinician_name': 'Dr. Blocked',
            'reason': 'Should not be allowed for outreach role',
            'scheduled_at': (timezone.now() + timedelta(days=1)).isoformat(),
            'status': 'scheduled',
        }, format='json')
        self.assertEqual(appointment.status_code, status.HTTP_403_FORBIDDEN)

        resource = CommunityResource.objects.create(name='Local Support Desk', category='wellness', active=True)
        referral = self.client.post('/api/referrals/', {
            'patient': patient_id,
            'resource': resource.id,
            'reason': 'Outreach referral is allowed.',
            'status': 'recommended',
        }, format='json')
        self.assertEqual(referral.status_code, status.HTTP_201_CREATED)

    def test_workflow_rule_auto_schedules_high_risk_followup(self):
        self.auth_user('admin_tester', 'pass1234')
        rule_response = self.client.post('/api/workflow-rules/', {
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
        triage = self.client.post('/api/triage/assess/', {
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
        process_response = self.client.post('/api/domain-events/process-pending/', {
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

        denied = self.client.post('/api/workflow-rules/', {
            'name': 'Outreach should fail',
            'event_type': 'triage.assessed',
            'condition': {},
            'action_type': 'create_alert',
            'action_config': {'severity': 'high'},
            'priority': 50,
            'active': True,
        }, format='json')
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        listing = self.client.get('/api/workflow-rules/')
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
        ward = self.client.post('/api/wards/', {
            'name': 'General Ward',
            'code': 'GW-A',
            'specialty': 'general',
            'floor': 2,
            'capacity': 30,
            'active': True,
        }, format='json')
        self.assertEqual(ward.status_code, status.HTTP_201_CREATED)
        ward_id = ward.data['id']

        bed_1 = self.client.post('/api/beds/', {
            'ward': ward_id,
            'bed_number': 'A-101',
            'status': 'available',
        }, format='json')
        self.assertEqual(bed_1.status_code, status.HTTP_201_CREATED)
        bed_1_id = bed_1.data['id']

        bed_2 = self.client.post('/api/beds/', {
            'ward': ward_id,
            'bed_number': 'A-102',
            'status': 'available',
        }, format='json')
        self.assertEqual(bed_2.status_code, status.HTTP_201_CREATED)
        bed_2_id = bed_2.data['id']

        patient_id = self.create_patient()

        admission = self.client.post('/api/admissions/', {
            'patient': patient_id,
            'bed': bed_1_id,
            'reason': 'Post-surgery observation',
            'diagnosis_on_admission': 'Recovery monitoring',
        }, format='json')
        self.assertEqual(admission.status_code, status.HTTP_201_CREATED)
        admission_id = admission.data['id']

        bed_state = self.client.get(f'/api/beds/{bed_1_id}/')
        self.assertEqual(bed_state.status_code, status.HTTP_200_OK)
        self.assertEqual(bed_state.data['status'], Bed.STATUS_OCCUPIED)

        med = self.client.post('/api/medication-orders/', {
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

        med_status = self.client.post(f'/api/medication-orders/{med_id}/mark-status/', {
            'status': MedicationOrder.STATUS_COMPLETED,
            'notes': 'Course completed without complications.',
        }, format='json')
        self.assertEqual(med_status.status_code, status.HTTP_200_OK)
        self.assertEqual(med_status.data['status'], MedicationOrder.STATUS_COMPLETED)

        lab = self.client.post('/api/lab-orders/', {
            'patient': patient_id,
            'admission': admission_id,
            'test_name': 'CBC',
            'priority': LabOrder.PRIORITY_URGENT,
        }, format='json')
        self.assertEqual(lab.status_code, status.HTTP_201_CREATED)
        lab_id = lab.data['id']

        lab_start = self.client.post(f'/api/lab-orders/{lab_id}/start/', {}, format='json')
        self.assertEqual(lab_start.status_code, status.HTTP_200_OK)
        self.assertEqual(lab_start.data['status'], LabOrder.STATUS_IN_PROGRESS)

        lab_complete = self.client.post(f'/api/lab-orders/{lab_id}/complete/', {
            'result_value': 'Normal',
            'result_summary': 'No active infection.',
        }, format='json')
        self.assertEqual(lab_complete.status_code, status.HTTP_200_OK)
        self.assertEqual(lab_complete.data['status'], LabOrder.STATUS_COMPLETED)

        transfer = self.client.post(f'/api/admissions/{admission_id}/transfer/', {
            'bed': bed_2_id,
            'reason': 'Moved closer to nursing station',
        }, format='json')
        self.assertEqual(transfer.status_code, status.HTTP_200_OK)
        self.assertEqual(transfer.data['bed'], bed_2_id)

        old_bed = self.client.get(f'/api/beds/{bed_1_id}/')
        self.assertEqual(old_bed.status_code, status.HTTP_200_OK)
        self.assertEqual(old_bed.data['status'], Bed.STATUS_AVAILABLE)

        discharge = self.client.post(f'/api/admissions/{admission_id}/discharge/', {
            'discharge_summary': 'Patient stabilized and discharged to home care.',
        }, format='json')
        self.assertEqual(discharge.status_code, status.HTTP_200_OK)
        self.assertEqual(discharge.data['status'], Admission.STATUS_DISCHARGED)

        final_bed = self.client.get(f'/api/beds/{bed_2_id}/')
        self.assertEqual(final_bed.status_code, status.HTTP_200_OK)
        self.assertEqual(final_bed.data['status'], Bed.STATUS_AVAILABLE)

        hospital_flow = self.client.get('/api/analytics/hospital-flow/')
        self.assertEqual(hospital_flow.status_code, status.HTTP_200_OK)
        self.assertIn('kpis', hospital_flow.data)
        self.assertIn('admissions_by_status', hospital_flow.data)
        self.assertIn('labs_by_status', hospital_flow.data)
