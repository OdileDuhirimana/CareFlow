# Ensures the Celery app is loaded whenever Django starts, so `@shared_task`
# decorators (see api/tasks.py) always have an app to register against.
from .celery import app as celery_app

__all__ = ('celery_app',)
