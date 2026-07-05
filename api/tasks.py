"""Celery tasks for the domain-event background-processing pipeline.

Why a task that re-fetches the event by id rather than accepting the
`DomainEvent` instance directly: Celery task arguments are serialized
(JSON, per `CELERY_TASK_SERIALIZER` in settings) and sent to a broker a
separate worker process reads from — passing a live Django model instance
across that boundary doesn't work (and wouldn't reflect the DB state by
the time the worker picks it up anyway, if there's any queueing delay).
Passing the primary key and re-fetching inside the task is the standard,
correct Celery pattern for this reason.
"""
from __future__ import annotations

import logging

from celery import shared_task

from api.models import DomainEvent

logger = logging.getLogger('careflow.workflow')


@shared_task(
    name='api.process_domain_event',
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def process_domain_event_task(self, event_id: int) -> dict | None:
    # Imported inside the task body rather than at module level to avoid a
    # circular import: `api.services.workflow_engine` imports this module's
    # sibling dispatch call (`emit_domain_event` -> `process_domain_event_task.delay`),
    # so importing `process_domain_event` at module scope here would create
    # `api.tasks` <-> `api.services.workflow_engine` import cycle at Django
    # startup.
    from api.services.workflow_engine import process_domain_event

    try:
        event = DomainEvent.objects.get(pk=event_id)
    except DomainEvent.DoesNotExist:
        # Nothing to retry — the event genuinely does not exist (e.g. a
        # stale task left over from a rolled-back transaction). Logging
        # rather than raising avoids Celery's retry machinery repeatedly
        # trying to process a row that will never appear.
        logger.warning('domain_event_task_missing_event', extra={'event_id': event_id})
        return None

    return process_domain_event(event)


@shared_task(name='api.process_pending_domain_events')
def process_pending_domain_events_task(limit: int = 25, include_failed: bool = True, max_attempts: int = 3) -> dict:
    """Periodic sweep for anything that fell through the primary dispatch
    path (e.g. a worker outage between `.delay()` and task execution).
    Wired to `CELERY_BEAT_SCHEDULE` in `careflow/settings.py`; also directly
    callable via `POST /api/v1/domain-events/process-pending/` for manual
    triggering — see `api.services.workflow_engine.process_pending_domain_events`,
    which both this task and that endpoint delegate to.
    """
    from api.services.workflow_engine import process_pending_domain_events

    return process_pending_domain_events(limit=limit, include_failed=include_failed, max_attempts=max_attempts)
