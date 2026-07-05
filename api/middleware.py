"""Request-level middleware.

Kept to a single, narrowly-scoped middleware class rather than growing
`careflow/settings.py`'s `MIDDLEWARE` list with ad hoc inline functions —
consistent with the rest of the project's "one thing per module" style.
"""
from __future__ import annotations

from .metrics import record_response_status


class MetricsMiddleware:
    """Increments the `careflow_http_*` counters exposed at `/metrics`.

    Placed first in `MIDDLEWARE` (see `careflow/settings.py`) so its
    response-side code (everything after `self.get_response(request)`)
    runs *last* — Django processes middleware as nested layers, and the
    first-registered middleware is the outermost layer, so it observes the
    final `status_code` after every other middleware, the view, and
    exception handling have all run.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        record_response_status(response.status_code)
        return response
