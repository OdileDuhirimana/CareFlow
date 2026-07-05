"""Helpers for recording PHI-adjacent access/export in the audit trail.

Why explicit calls instead of signals/middleware
--------------------------------------------------
A generic "log every request" middleware would produce enormous noise (every
static asset, health check, and read-only list call) and would not capture
*which* patient record was viewed within a bulk endpoint. Django `post_save`
signals would catch create/update but not read/export access, which is the
actual compliance-relevant gap for this application (see
`AssessmentExportCSVView`). Instead, `record_audit_event` is called
explicitly at every call site that creates, updates, deletes, views, or
exports Patient / MedicationOrder / Admission / RiskAssessment data (see
`api/views.py`). This keeps the audit trail meaningful and easy to reason
about, at the cost of requiring discipline to add a call site when a new
PHI-touching endpoint is introduced — an accepted tradeoff for a
portfolio-scale project, documented in the README's "Known Tradeoffs"
section.

Why failures here must never bubble up
---------------------------------------
`record_audit_event` is always called *after* the primary operation (the
read, write, or export) has already succeeded. If writing the audit row
itself raised (e.g. a transient DB error, or an unusual proxy header
tripping the `GenericIPAddressField` validator), the exception would
previously propagate straight out of the view and turn an
already-successful patient read or CSV export into an opaque 500 for the
caller — the audit trail failing would make the *primary* operation look
broken too, which is exactly backwards for a logging concern.
`record_audit_event` therefore catches and logs any exception internally
and returns `None` on failure rather than raising, so a broken audit sink
degrades observability, never availability. This is enforced once here (a
single defensive boundary) rather than duplicated in a try/except at every
call site, per the DRY principle.
"""
from __future__ import annotations

import logging
from typing import Any

from .metrics import increment_counter
from .models import AuditLog

logger = logging.getLogger('careflow.audit')


def _client_ip(request) -> str | None:
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def record_audit_event(
    request,
    action: str,
    resource_type: str,
    resource_id: Any = '',
    detail: str = '',
) -> AuditLog | None:
    """Persist one audit trail row and mirror it to structured logs.

    `request` may be any DRF/Django request with a `.user` attribute; unauthenticated
    access (e.g. the public prediction endpoint) is recorded with `actor=None`.

    Returns the created `AuditLog` row, or `None` if audit persistence itself
    failed (see module docstring: a failure here is logged, never raised).
    """
    actor = getattr(request, 'user', None)
    if actor is not None and not getattr(actor, 'is_authenticated', False):
        actor = None

    try:
        entry = AuditLog.objects.create(
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id != '' else '',
            detail=detail,
            ip_address=_client_ip(request),
        )
    except Exception:
        # Deliberately broad: any failure to persist the audit row must
        # degrade observability, not availability. The primary operation
        # (already completed by the time this is called) must not be
        # turned into a 500 because logging failed. See module docstring.
        logger.exception(
            'audit_event_persist_failed',
            extra={
                'audit_action': action,
                'resource_type': resource_type,
                'resource_id': str(resource_id) if resource_id != '' else None,
                'actor': actor.username if actor else None,
            },
        )
        return None

    increment_counter('careflow_audit_events_total')
    logger.info(
        'audit_event',
        extra={
            'audit_action': action,
            'resource_type': resource_type,
            'resource_id': str(resource_id) if resource_id != '' else None,
            'actor': actor.username if actor else None,
            'ip_address': entry.ip_address,
        },
    )
    return entry
