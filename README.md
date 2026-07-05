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

Redis/Celery are optional for local development — with `REDIS_URL` unset,
domain events process synchronously in-process (`CELERY_TASK_ALWAYS_EAGER=True`),
identical in effect to running a worker. To exercise genuine async
dispatch locally, set `REDIS_URL` (e.g. a local `redis-server`) and run a
worker in a second terminal: `celery -A careflow worker --loglevel=info`.

## Docker Run

```bash
docker compose up --build
```

Starts `web` (Gunicorn), `worker` (Celery, domain-event processing),
`beat` (Celery, periodic retry sweep — optional, safe to scale to zero),
`redis` (Celery broker + shared cache/throttle backend), and `db`
(Postgres).

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
- Startup fails in production if `SECRET_KEY` or `DATABASE_URL` is not explicitly set
- CI runs migrations, role setup, demo seed, deploy checks, schema validation, and tests
- Configure `.env` from `.env.example`
- `render.yaml` defines three services (`careflow-api` production, `careflow-worker` Celery, `careflow-api-staging` — a second, independent environment) plus two managed Postgres databases and a shared Redis instance. **Only the code/config for staging has been written in this pass — it has not been provisioned or verified against a live Render account.** Standing it up is tracked in "Future Improvements."

### Rollback Runbook

If a deploy to `careflow-api` introduces a regression:

1. **Immediate mitigation — roll back the deploy.** Render retains prior
   successful deploys per service. In the Render dashboard: `careflow-api`
   → **Deploys** tab → find the last known-good deploy → **Rollback to
   this deploy**. This restores the previous Docker image immediately;
   it does not touch the database.
2. **If the regression involves a migration**, do not roll back the
   application code alone without first checking whether the new
   migration is backward-compatible with the old code:
   - If the migration only *added* a nullable column/table (the common,
     safe case), rolling back the app code is sufficient — the old code
     simply ignores the new column.
   - If the migration is destructive (dropped/renamed a column, altered a
     constraint the old code relies on), a code-only rollback will crash
     the old code against the new schema. In that case, write and apply a
     new *forward* migration that reverses the change, rather than trying
     to run migrations backward — Django's migration system supports
     unapplying migrations (`python manage.py migrate api <previous_migration_name>`)
     but this is riskier under concurrent traffic than a forward-fixing
     migration and should only be done during a maintenance window.
3. **Verify the rollback**: hit `GET /health/ready/` (confirms DB
   connectivity) and `GET /api/docs/` (confirms the app booted correctly),
   then re-run the specific request/flow that surfaced the regression.
4. **This is a documented procedure, not a verified one.** No actual
   rollback has been performed against a live Render deployment from this
   environment — this runbook describes the mechanism Render's dashboard
   provides and the general Django migration-safety reasoning, not a
   tested incident response.

## Deploy On Render

1. Push this repository to GitHub.
2. In Render, create a new Blueprint and point it to this repo.
3. Render will read `render.yaml` and create:
   - `careflow-api` web service (Docker)
   - `careflow-worker` Celery worker service (Docker)
   - `careflow-api-staging` second web service (Docker) — **written but not yet provisioned/verified**
   - `careflow-db` / `careflow-db-staging` PostgreSQL databases
   - `careflow-redis` Redis instance
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
- `REDIS_URL` (from the Render Redis instance)
- `DEBUG=false`
- `DATABASE_SSL_REQUIRE=true`
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
