"""Cache-backend-outage-resilient throttle classes.

Why this module exists
-----------------------
DRF's built-in `SimpleRateThrottle.allow_request()` (the base class behind
`AnonRateThrottle`, `UserRateThrottle`, and `ScopedRateThrottle`) reads and
writes request history directly through `django.core.cache.cache` with no
exception handling of its own. In this project `CACHES['default']` is
Redis-backed whenever `REDIS_URL` is set (production/docker-compose — see
`careflow/settings.py`); if that Redis instance becomes unreachable at
runtime, the resulting `redis.exceptions.ConnectionError` /
`django_redis.exceptions.ConnectionInterrupted` propagates straight out of
`allow_request()`, through DRF's `APIView.check_throttles()`, and becomes an
unhandled 500.

Because `DEFAULT_THROTTLE_CLASSES` (`AnonRateThrottle` + `UserRateThrottle`)
applies to *every* endpoint by default, this is not a narrow edge case: a
Redis outage takes down the entire API surface — confirmed by hand against a
running instance (`GET /api/v1/...` and `POST /api/v1/auth/token/` both
500'd with an unhandled `ConnectionError` the moment the Redis container was
stopped). That is the same "observability/defense-in-depth failure must not
become an availability failure" problem already fixed once in this codebase
for the metrics counters (see `api/metrics.py::increment_counter`) and
already articulated as a design principle for the audit trail (see
`api/audit.py` module docstring) — this closes the same gap for throttling.

Why fail OPEN specifically for throttling (and only for the "can't reach
the counter store" case)
-------------------------------------------------------------------------
Rate limiting is defense-in-depth against abuse, not the primary access
control mechanism — that is `IsAuthenticated`/the `Has*Role`/`*Permission`
classes in `api/permissions.py`, which are completely unaffected by this
change and remain fail-closed. When the throttle's own cache backend is
down, there are exactly two options: block every request (fail closed —
turns a Redis blip into a full outage of a healthcare-ops API) or allow the
request through unmetered until the cache backend recovers (fail open —
briefly loses brute-force/scraping protection but keeps the service
available). For this application, an availability outage on every clinical
and patient-facing endpoint is worse than a temporary loss of rate-limiting
during an already-degraded infrastructure event, so this fails open. Any
other exception path in the underlying throttle (e.g. a genuine
over-the-limit result) is untouched — only cache/connection errors raised
*while checking* the throttle are caught.
"""
from __future__ import annotations

import logging

from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle

logger = logging.getLogger('careflow.throttling')


class FailOpenThrottleMixin:
    """Allow the request through if the throttle's cache backend errors out
    while being checked, instead of letting the exception surface as a 500.
    """

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            logger.warning(
                'throttle_check_failed_failing_open',
                extra={'throttle_class': type(self).__name__},
                exc_info=True,
            )
            return True


class ResilientAnonRateThrottle(FailOpenThrottleMixin, AnonRateThrottle):
    pass


class ResilientUserRateThrottle(FailOpenThrottleMixin, UserRateThrottle):
    pass


class ResilientScopedRateThrottle(FailOpenThrottleMixin, ScopedRateThrottle):
    pass
