# CareFlow API

CareFlow is a Django REST API for patient operations, explainable triage risk scoring, alerting, scheduling, and analytics.

## Portfolio Features

- JWT-authenticated patient records and care-plan generation
- Role-based access control (admin, clinician, outreach) for production-like workflows
- Explainable triage scoring (`risk_score`, `risk_level`, top key drivers)
- Persistent risk assessments and automatic high-risk alerts
- Appointment scheduling workflow
- Remote monitoring check-ins with automatic urgent escalation
- Community resource directory + patient referral workflows
- Patient journey and community recommendation endpoints
- Full inpatient hospital flow: wards, beds, admissions, transfers, discharge
- Medication ordering lifecycle and lab workflow (ordered -> in progress -> completed)
- Event-driven workflow automation engine (domain events + configurable rules)
- Analytics dashboard endpoint for KPIs + trend data
- Social impact analytics for referrals and vulnerable check-ins
- Hospital flow analytics for occupancy and operational KPIs
- CSV export for risk assessments
- OpenAPI schema + Swagger docs
- Polished portfolio homepage at `/`

## Local Run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Docker Run

```bash
docker compose up --build
```

## Key Endpoints

- `POST /api/auth/token/`
- `POST /api/predict/health-risk/` (public demo scoring)
- `POST /api/triage/assess/` (authenticated + stores assessment)
- `POST /api/checkins/` (remote monitoring)
- `POST /api/admissions/`, `POST /api/admissions/{id}/transfer/`, `POST /api/admissions/{id}/discharge/`
- `GET/POST /api/wards/`, `GET/POST /api/beds/`
- `POST /api/medication-orders/`, `POST /api/medication-orders/{id}/mark-status/`
- `POST /api/lab-orders/`, `POST /api/lab-orders/{id}/start/`, `POST /api/lab-orders/{id}/complete/`
- `GET /api/patients/{id}/community-recommendations/`
- `GET /api/patients/{id}/journey/`
- `POST /api/referrals/`
- `GET/POST /api/workflow-rules/`
- `GET /api/domain-events/`, `POST /api/domain-events/process-pending/`
- `GET /api/analytics/overview/`
- `GET /api/analytics/impact/`
- `GET /api/analytics/hospital-flow/`
- `GET /api/analytics/assessments/export.csv`
- `GET /api/patients/{id}/care-plan/`
- `GET /api/auth/me/`
- `GET /health/` and `GET /health/ready/`

## Demo Bootstrap (One Command)

```bash
./scripts/demo_bootstrap.sh
```

This command runs migrations, configures roles, seeds realistic demo data, and verifies Django checks.

## Deployment Notes

- Startup entrypoint runs `migrate` and `collectstatic` automatically
- Production security settings are enabled when `DEBUG=false`
- Startup fails in production if `SECRET_KEY` is not explicitly set
- CI runs migrations, role setup, demo seed, deploy checks, schema validation, and tests
- Configure `.env` from `.env.example`
- `render.yaml` is included for one-click Render deployment

## Deploy On Render

1. Push this repository to GitHub.
2. In Render, create a new Blueprint and point it to this repo.
3. Render will read `render.yaml` and create:
   - `careflow-api` web service (Docker)
   - `careflow-db` PostgreSQL database
4. After first deploy, open:
   - `https://<your-service>.onrender.com/health/`
   - `https://<your-service>.onrender.com/api/docs/`
5. Optional first-time setup:
   - `python manage.py setup_roles`
   - `python manage.py seed_demo_data --password <secure-demo-password>`

### Render environment variables

Configured automatically via `render.yaml`:
- `SECRET_KEY` (generated)
- `JWT_SECRET` (generated)
- `DATABASE_URL` (from Render Postgres)
- `DEBUG=false`
- `ALLOWED_HOSTS=.onrender.com`
- `CSRF_TRUSTED_ORIGINS=https://*.onrender.com`
- `SECURE_SSL_REDIRECT=true`

Set manually to match your frontend/domain:
- `CORS_ALLOWED_ORIGINS` (for example `https://careflow-web.onrender.com`)

## Default Admin

Create an admin user with:

```bash
python manage.py createsuperuser
```
