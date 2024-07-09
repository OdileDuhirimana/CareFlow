#!/usr/bin/env bash
set -euo pipefail

if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="python3"
fi

DEMO_PASSWORD="${DEMO_PASSWORD:-careflow-demo-2026}"

$PYTHON_BIN manage.py migrate --noinput
$PYTHON_BIN manage.py setup_roles
$PYTHON_BIN manage.py seed_demo_data --password "$DEMO_PASSWORD"
$PYTHON_BIN manage.py check

echo "Demo environment ready."
echo "Login users: admin_demo / clinician_demo / outreach_demo"
echo "Password: $DEMO_PASSWORD"
