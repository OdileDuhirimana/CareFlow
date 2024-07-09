## 🩺 **CareFlow – Predictive Healthcare API (Django REST + AI Integration)**

### 🌍 **Project Overview**

CareFlow is an advanced **healthcare intelligence platform** built with **Django REST Framework (DRF)** and **AI-powered predictive models**.
It helps hospitals and clinics **forecast patient risks**, **streamline record management**, and **generate real-time health analytics** — all while maintaining **HIPAA-grade data security** and **scalable cloud deployment**.

The system acts as a **backend API** that supports both a **hospital dashboard frontend** and **mobile apps** used by medical staff.

---

## ⚙️ **Core Features**

### 🧬 1. Patient Management

* Register, update, and manage patient profiles
* Secure electronic health record (EHR) storage
* Upload and store medical documents and lab results
* Smart search and filtering by demographics, diseases, or ID

### 🧠 2. Predictive Analytics (AI/ML)

* Integrated **Machine Learning models** predicting:

    * Risk of chronic diseases (e.g., diabetes, hypertension)
    * Hospital readmission likelihood
    * Medication adherence probability
* Models trained with **scikit-learn / TensorFlow**
* Real-time inference API endpoint:
  `POST /api/predict/health-risk/`

### 🩸 3. Doctor & Staff Management

* Role-based authentication (doctor, nurse, admin)
* Scheduling system for appointments & shifts
* Multi-hospital support (each hospital has its own sub-admin)

### 💳 4. Billing & Insurance Integration

* Patient billing with **Stripe API** integration for online payments
* Generate invoices & receipts
* Insurance claim tracking and history

### 📊 5. Hospital Analytics Dashboard

* Interactive analytics: admissions, discharges, high-risk patients
* Visual charts with aggregated health data
* Exportable reports (CSV, PDF)
* Integration with **Grafana or Metabase** (optional)

### 🔒 6. Authentication & Security

* JWT-based authentication
* Encrypted sensitive data (AES or Fernet encryption)
* Role-based access control (RBAC)
* Audit trail for sensitive operations
* Two-factor authentication (2FA) for admin users

### 🧾 7. Notifications & Communication

* Email & SMS notifications (appointment reminders, alerts)
* Integration with **Twilio** or **SendGrid**
* Push notification system (Firebase Cloud Messaging)

### ☁️ 8. Deployment & DevOps

* Dockerized microservice structure
* CI/CD setup using GitHub Actions
* Deployed on AWS/GCP with PostgreSQL or MySQL
* Automated backup for patient records and model files

---

## 🧠 **AI/ML Components**

* Models trained on synthetic or Kaggle health datasets
* Example models:

    * Logistic Regression / XGBoost for disease prediction
    * LSTM model for time-series health metrics
* Saved as `.pkl` or `.h5` files and loaded via API endpoints
* Retraining pipeline script (`train_model.py`)
* ML version control using **DVC**

---

## 🔐 **Environment Variables / Secrets**

| Variable                              | Description                        |
| ------------------------------------- | ---------------------------------- |
| `SECRET_KEY`                          | Django secret key                  |
| `DEBUG`                               | True (dev) / False (prod)          |
| `DATABASE_URL`                        | PostgreSQL/MySQL connection string |
| `JWT_SECRET`                          | JWT signing secret                 |
| `STRIPE_SECRET_KEY`                   | Stripe secret for billing          |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` | For sending alerts                 |
| `AI_MODEL_PATH`                       | Path to saved model file           |
| `ALLOWED_HOSTS`                       | Frontend domains                   |
| `BASE_URL`                            | API base URL                       |
| `TIMEZONE`                            | e.g., Africa/Kigali                |

---

## 🧱 **Tech Stack**

* **Backend:** Django REST Framework
* **Database:** PostgreSQL / MySQL
* **ML:** Scikit-learn, TensorFlow, Pandas, NumPy
* **Auth:** JWT (SimpleJWT)
* **Payments:** Stripe API
* **Emails:** SMTP / SendGrid
* **Containers:** Docker, Docker Compose
* **Deployment:** AWS EC2 + RDS or Render

---

## 🧩 **API Examples**

### ➕ Register a Patient

`POST /api/patients/`

```json
{
  "name": "John Doe",
  "age": 45,
  "gender": "male",
  "blood_type": "O+",
  "diagnosis": "Hypertension"
}
```

### 🧠 Predict Health Risk

`POST /api/predict/health-risk/`

```json
{
  "age": 45,
  "bmi": 29.5,
  "blood_pressure": 135,
  "cholesterol": 220
}
```

**Response:**

```json
{
  "risk_score": 0.82,
  "risk_level": "High",
  "recommended_action": "Schedule cardiac evaluation."
}
```

---

## 🚀 **Project Milestones for Junie AI**

| Phase         | Deliverables                                   |
| ------------- | ---------------------------------------------- |
| 1️⃣ Setup     | Django REST setup, PostgreSQL config, JWT auth |
| 2️⃣ Models    | Database models for patients, doctors, records |
| 3️⃣ AI        | Integrate ML model training & prediction API   |
| 4️⃣ Features  | Add billing, notifications, analytics          |
| 5️⃣ Testing   | Unit tests, API testing (Pytest + Postman)     |
| 6️⃣ Dockerize | Dockerfile + docker-compose.yml                |
| 7️⃣ Deploy    | Deploy to AWS or Render with CI/CD             |
| 8️⃣ Docs      | Swagger/OpenAPI + project README               |

---

## 💥 **Why It Impresses**

* Combines **AI, data science, and backend engineering**
* Tackles a **real-world domain (healthcare)** with scalability in mind
* Shows mastery of **security, DevOps, and ML integration**
* Perfectly fits portfolio, hackathon, or interview showpiece material


## 🩺 **CareFlow – Predictive Healthcare API (Django REST + AI Integration)**

### 🌍 **Project Overview**

CareFlow is an advanced **healthcare intelligence platform** built with **Django REST Framework (DRF)** and **AI-powered predictive models**.
It helps hospitals and clinics **forecast patient risks**, **streamline record management**, and **generate real-time health analytics** — all while maintaining **HIPAA-grade data security** and **scalable cloud deployment**.

The system acts as a **backend API** that supports both a **hospital dashboard frontend** and **mobile apps** used by medical staff.

---

## ⚙️ **Core Features**

### 🧬 1. Patient Management

* Register, update, and manage patient profiles
* Secure electronic health record (EHR) storage
* Upload and store medical documents and lab results
* Smart search and filtering by demographics, diseases, or ID

### 🧠 2. Predictive Analytics (AI/ML)

* Integrated **Machine Learning models** predicting:

    * Risk of chronic diseases (e.g., diabetes, hypertension)
    * Hospital readmission likelihood
    * Medication adherence probability
* Models trained with **scikit-learn / TensorFlow**
* Real-time inference API endpoint:
  `POST /api/predict/health-risk/`

### 🩸 3. Doctor & Staff Management

* Role-based authentication (doctor, nurse, admin)
* Scheduling system for appointments & shifts
* Multi-hospital support (each hospital has its own sub-admin)

### 💳 4. Billing & Insurance Integration

* Patient billing with **Stripe API** integration for online payments
* Generate invoices & receipts
* Insurance claim tracking and history

### 📊 5. Hospital Analytics Dashboard

* Interactive analytics: admissions, discharges, high-risk patients
* Visual charts with aggregated health data
* Exportable reports (CSV, PDF)
* Integration with **Grafana or Metabase** (optional)

### 🔒 6. Authentication & Security

* JWT-based authentication
* Encrypted sensitive data (AES or Fernet encryption)
* Role-based access control (RBAC)
* Audit trail for sensitive operations
* Two-factor authentication (2FA) for admin users

### 🧾 7. Notifications & Communication

* Email & SMS notifications (appointment reminders, alerts)
* Integration with **Twilio** or **SendGrid**
* Push notification system (Firebase Cloud Messaging)

### ☁️ 8. Deployment & DevOps

* Dockerized microservice structure
* CI/CD setup using GitHub Actions
* Deployed on AWS/GCP with PostgreSQL or MySQL
* Automated backup for patient records and model files

---

## 🧠 **AI/ML Components**

* Models trained on synthetic or Kaggle health datasets
* Example models:

    * Logistic Regression / XGBoost for disease prediction
    * LSTM model for time-series health metrics
* Saved as `.pkl` or `.h5` files and loaded via API endpoints
* Retraining pipeline script (`train_model.py`)
* ML version control using **DVC**

---

## 🔐 **Environment Variables / Secrets**

| Variable                              | Description                        |
| ------------------------------------- | ---------------------------------- |
| `SECRET_KEY`                          | Django secret key                  |
| `DEBUG`                               | True (dev) / False (prod)          |
| `DATABASE_URL`                        | PostgreSQL/MySQL connection string |
| `JWT_SECRET`                          | JWT signing secret                 |
| `STRIPE_SECRET_KEY`                   | Stripe secret for billing          |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` | For sending alerts                 |
| `AI_MODEL_PATH`                       | Path to saved model file           |
| `ALLOWED_HOSTS`                       | Frontend domains                   |
| `BASE_URL`                            | API base URL                       |
| `TIMEZONE`                            | e.g., Africa/Kigali                |

---

## 🧱 **Tech Stack**

* **Backend:** Django REST Framework
* **Database:** PostgreSQL / MySQL
* **ML:** Scikit-learn, TensorFlow, Pandas, NumPy
* **Auth:** JWT (SimpleJWT)
* **Payments:** Stripe API
* **Emails:** SMTP / SendGrid
* **Containers:** Docker, Docker Compose
* **Deployment:** AWS EC2 + RDS or Render

---

## 🧩 **API Examples**

### ➕ Register a Patient

`POST /api/patients/`

```json
{
  "name": "John Doe",
  "age": 45,
  "gender": "male",
  "blood_type": "O+",
  "diagnosis": "Hypertension"
}
```

### 🧠 Predict Health Risk

`POST /api/predict/health-risk/`

```json
{
  "age": 45,
  "bmi": 29.5,
  "blood_pressure": 135,
  "cholesterol": 220
}
```

**Response:**

```json
{
  "risk_score": 0.82,
  "risk_level": "High",
  "recommended_action": "Schedule cardiac evaluation."
}
```

---

## 🚀 **Project Milestones for Junie AI**

| Phase         | Deliverables                                   |
| ------------- | ---------------------------------------------- |
| 1️⃣ Setup     | Django REST setup, PostgreSQL config, JWT auth |
| 2️⃣ Models    | Database models for patients, doctors, records |
| 3️⃣ AI        | Integrate ML model training & prediction API   |
| 4️⃣ Features  | Add billing, notifications, analytics          |
| 5️⃣ Testing   | Unit tests, API testing (Pytest + Postman)     |
| 6️⃣ Dockerize | Dockerfile + docker-compose.yml                |
| 7️⃣ Deploy    | Deploy to AWS or Render with CI/CD             |
| 8️⃣ Docs      | Swagger/OpenAPI + project README               |

---

# Getting Started (Implemented Minimal MVP)

This repository includes a minimal, working Django REST API that implements:
- JWT authentication (token obtain/refresh)
- Patients CRUD endpoints
- Health-risk prediction endpoint with a deterministic demo model

## Prerequisites
- Python 3.11+
- pip

## Install and run
1. Create and activate a virtual environment (recommended).
2. Install dependencies:
   pip install -r requirements.txt
3. Apply migrations and create a superuser (optional for admin):
   python manage.py migrate
   python manage.py createsuperuser
4. Run the server:
   python manage.py runserver 0.0.0.0:8000

## Auth endpoints (JWT)
- POST /api/auth/token/
- POST /api/auth/token/refresh/
Payload for token:
{
  "username": "<your_user>",
  "password": "<your_pass>"
}

## Patients endpoints
- GET /api/patients/
- POST /api/patients/
- GET /api/patients/{id}/
- PATCH /api/patients/{id}/
- DELETE /api/patients/{id}/

Notes:
- All patients endpoints require Authorization: Bearer <access_token>

## Prediction endpoint
- POST /api/predict/health-risk/
Request JSON body:
{
  "age": 45,
  "bmi": 29.5,
  "blood_pressure": 135,
  "cholesterol": 220
}

The result returns a risk_score [0,1], risk_level, and recommended_action.

## Run tests
python manage.py test

Expected tests executed:
- Obtain JWT token
- Create/List/Retrieve/Update/Delete Patient
- Predict health risk response schema

## Environment variables
The app reads the following from the environment (with safe defaults for local dev):
- SECRET_KEY (default: dev-secret-key)
- DEBUG (default: true)
- JWT_SECRET (default: SECRET_KEY)
- TIMEZONE (default: UTC)
- ALLOWED_HOSTS (default: *)

For production, please set proper SECRET_KEY, JWT_SECRET, DEBUG=false, and restrictive ALLOWED_HOSTS.

---

# Production readiness (added)

- Dockerfile with Gunicorn + WhiteNoise
- docker-compose.yml with Postgres and healthchecks
- Env-driven secure settings: DATABASE_URL, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, CORS_ALLOWED_ORIGINS
- drf-spectacular for OpenAPI schema and Swagger UI
- Basic JSON console logging
- Health check endpoint at GET /health/
- GitHub Actions CI workflow

## New endpoints
- GET /health/ — liveness/readiness
- GET /api/schema/ — OpenAPI schema (JSON)
- GET /api/docs/ — Swagger UI

## Docker (production-like)
1. Copy .env.example to .env and set strong secrets and hosts.
2. Build and run services:
   docker compose up -d --build
3. Apply migrations and create a superuser (first time):
   docker compose exec web python manage.py migrate
   docker compose exec web python manage.py createsuperuser
4. Access API at http://localhost:8000

## Security checklist
- DEBUG=false
- Strong, unique SECRET_KEY and JWT_SECRET
- ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS set to your domains
- Use HTTPS with reverse proxy or load balancer; enable SECURE_SSL_REDIRECT
- Rotate credentials regularly; restrict DB/network access
- Regular backups of Postgres and model artifacts

## CI
- On pushes and PRs to main/master, GitHub Actions installs deps, migrates, and runs tests
