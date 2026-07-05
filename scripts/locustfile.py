"""Load-testing profile for docs/load-test.md.

Run with:
    locust -f scripts/locustfile.py --host http://127.0.0.1:8001 --headless \
        --users 20 --spawn-rate 5 --run-time 30s --csv /tmp/careflow-loadtest

Requires `manage.py seed_demo_data` to have been run against the target
server first (uses the seeded `clinician_demo` account). Dev-only tool —
see requirements-dev.txt.

A single JWT is fetched once (module load) and shared across all simulated
users, rather than each simulated user logging in independently. This is
deliberate: `POST /api/v1/auth/token/` carries its own tight scoped
throttle (`DRF_THROTTLE_TOKEN`, default 10/minute — see
`careflow/settings.py`) specifically to resist credential-stuffing, and a
naive "every simulated user logs in" load-test profile mostly measures that
throttle rejecting login storms rather than the actual endpoints under
test. That throttle-saturation behavior is itself documented as a distinct,
real finding in docs/load-test.md — this file isolates it from the
per-endpoint latency numbers by authenticating once.
"""
import os

from locust import HttpUser, task, between

_SHARED_TOKEN = os.environ.get('CAREFLOW_LOADTEST_TOKEN', '')


class CareFlowUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.headers = {'Authorization': f'Bearer {_SHARED_TOKEN}'} if _SHARED_TOKEN else {}

    @task(3)
    def list_patients(self):
        self.client.get('/api/v1/patients/', headers=self.headers, name='/api/v1/patients/ [list]')

    @task(2)
    def analytics_overview(self):
        self.client.get('/api/v1/analytics/overview/', headers=self.headers, name='/api/v1/analytics/overview/')

    @task(2)
    def public_predict(self):
        self.client.post(
            '/api/v1/predict/health-risk/',
            json={'age': 55, 'bmi': 27.5, 'blood_pressure': 130, 'cholesterol': 210},
            name='/api/v1/predict/health-risk/ [public, uncached]',
        )

    @task(1)
    def submit_checkin(self):
        self.client.post(
            '/api/v1/checkins/',
            json={
                'patient': 1,
                'symptom_severity': 3,
                'mood_score': 6,
                'medication_taken': True,
            },
            headers=self.headers,
            name='/api/v1/checkins/ [triggers domain-event processing]',
        )
