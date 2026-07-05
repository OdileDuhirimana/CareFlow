"""Celery application instance for the domain-event background pipeline.

See `careflow/settings.py`'s Celery section for the full rationale,
including why `CELERY_TASK_ALWAYS_EAGER` defaults to `True` (synchronous,
in-process execution — identical to this project's previous behavior) when
`REDIS_URL` is not configured, so local dev/CI need no broker or worker
process to exercise domain-event-driven behavior.
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'careflow.settings')

app = Celery('careflow')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
