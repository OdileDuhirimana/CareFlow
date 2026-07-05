"""Custom DRF exception handling.

Why this exists
----------------
Before this module, error responses had two different shapes depending on
the code path that failed:

- ``raise ValidationError({'patient': 'msg'})`` -> DRF serializes this as
  ``{"patient": ["msg"]}`` (a field-keyed dict of lists).
- ``Response({'detail': 'msg'}, status=400)`` -> a flat ``{"detail": "msg"}``.

API consumers had to branch on which shape they received, which is a real
usability and maintainability problem for anyone integrating against this
API (including our own frontend, if one is ever built).

This handler normalizes every DRF-raised exception into one consistent
envelope:

    {
        "detail": "<human readable summary>",
        "errors": { ... field-level errors, or {} if none apply ... }
    }

Design decisions
-----------------
- We only touch responses that DRF's default handler already produced
  (i.e., we call ``exception_handler`` first and reshape its result). This
  keeps status codes and DRF's exception-type handling untouched — we are
  purely normalizing the response body shape, not reimplementing error
  handling.
- Non-DRF exceptions (anything the default handler returns ``None`` for)
  are intentionally left alone here so Django's normal 500 handling
  applies; this handler is not a catch-all replacement for proper
  exception handling in view code.
- Manual ``Response({'detail': ...}, status=...)`` calls written directly
  in views (e.g. ``AdmissionViewSet.transfer``) are NOT routed through
  ``EXCEPTION_HANDLER`` because they never raise — they return directly.
  Those call sites already use the ``{"detail": ...}`` shape, which is a
  subset of the normalized envelope (``errors`` simply empty), so they are
  already compatible with API consumers expecting this contract.
"""
from __future__ import annotations

from typing import Any

from rest_framework.views import exception_handler as drf_exception_handler


def careflow_exception_handler(exc: Exception, context: dict[str, Any]):
    """Normalize every DRF exception response into one envelope shape.

    Returns the reshaped ``Response`` object, or ``None`` for anything DRF's
    default handler does not turn into a response (letting Django's normal
    500 handling apply, as recommended by DRF's own documentation).
    """
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    original_data = response.data

    if isinstance(original_data, dict) and 'detail' in original_data and len(original_data) == 1:
        # Already the flat {"detail": "..."} shape DRF uses for
        # PermissionDenied/NotAuthenticated/NotFound/Throttled/etc.
        detail = original_data['detail']
        errors: dict[str, Any] = {}
    elif isinstance(original_data, dict):
        # Field-keyed validation errors, e.g. {"patient": ["msg"]} or
        # {"non_field_errors": ["msg"]}.
        errors = original_data
        detail = _summarize_field_errors(errors)
    elif isinstance(original_data, list):
        # Some serializers (e.g. list-level validation) raise a bare list.
        errors = {'non_field_errors': original_data}
        detail = _summarize_field_errors(errors)
    else:
        errors = {}
        detail = str(original_data)

    response.data = {'detail': detail, 'errors': errors}
    return response


def _summarize_field_errors(errors: dict[str, Any]) -> str:
    """Produce a single human-readable summary line from a field-error dict."""
    parts = []
    for field, messages in errors.items():
        if isinstance(messages, (list, tuple)):
            message_text = '; '.join(str(m) for m in messages)
        else:
            message_text = str(messages)
        parts.append(f'{field}: {message_text}' if field != 'non_field_errors' else message_text)
    return ' | '.join(parts) if parts else 'Invalid request.'
