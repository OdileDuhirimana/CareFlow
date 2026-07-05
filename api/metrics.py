"""Minimal, dependency-free Prometheus-format metrics endpoint (OBS-02).

Why a hand-rolled counter set instead of `django-prometheus`: this
project's actual monitoring need is "can an operator see basic
request/error/domain-event volume without standing up a full metrics
stack" — a handful of named counters answers that. `django-prometheus`
would add request-instrumenting middleware, per-endpoint histogram
buckets, and a dependency on the `prometheus_client` registry, which is
real value at real production scale but is disproportionate tooling for a
demo-data-scale portfolio project (the same reasoning the project already
applies elsewhere — see README "Known Tradeoffs"). This still emits
genuine Prometheus text exposition format, so it is a drop-in scrape
target for a real Prometheus server if one is ever pointed at this
deployment.

Why counters live in the Django cache rather than in-process globals: the
Docker image runs Gunicorn with multiple worker processes (see
`Dockerfile`), each an independent Python process with its own memory. An
in-process counter would only reflect the traffic that specific worker
happened to handle. Storing counters in the shared `CACHES` backend
(Redis in production, see `careflow/settings.py`) means `/metrics` reports
a total across every worker, not just whichever one served the `/metrics`
request itself. In local dev/CI (`LocMemCache`, single process), this
degrades gracefully to an accurate single-process count.

Why a fixed, pre-registered metric list rather than dynamic per-endpoint
labels: enumerating cache keys by pattern is not portably supported across
cache backends (`LocMemCache` has no `keys()`; the Redis backend does, but
relying on backend-specific behavior here would break local dev/CI, which
run without Redis). A fixed, small set of named counters avoids that
problem entirely and keeps cardinality bounded, which is itself a metrics
best practice.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.http import HttpResponse

logger = logging.getLogger('careflow.metrics')

_CACHE_KEY_PREFIX = 'careflow:metrics'

#: name -> (help text, Prometheus metric type). Add new counters here, then
#: call `increment_counter(name)` at the relevant call site — see
#: `api/middleware.py` (HTTP requests), `api/services/workflow_engine.py`
#: (domain events), and `api/audit.py` (audit trail writes) for the three
#: current instrumentation points.
_COUNTER_REGISTRY: dict[str, tuple[str, str]] = {
    'careflow_http_requests_total': ('Total HTTP requests received.', 'counter'),
    'careflow_http_responses_2xx_total': ('HTTP responses with a 2xx status code.', 'counter'),
    'careflow_http_responses_4xx_total': ('HTTP responses with a 4xx status code.', 'counter'),
    'careflow_http_responses_5xx_total': ('HTTP responses with a 5xx status code.', 'counter'),
    'careflow_domain_events_processed_total': (
        'Domain events successfully processed by the workflow engine.',
        'counter',
    ),
    'careflow_domain_events_failed_total': ('Domain events that failed processing.', 'counter'),
    'careflow_audit_events_total': ('Audit log entries successfully persisted.', 'counter'),
}


def _cache_key(metric_name: str) -> str:
    return f'{_CACHE_KEY_PREFIX}:{metric_name}'


def increment_counter(metric_name: str, amount: int = 1) -> None:
    """Increment a named counter by `amount` (default 1).

    Raises `ValueError` for an unregistered metric name — deliberately
    fails loud at the call site during development rather than silently
    dropping an intended metric (which would be much harder to notice than
    a test failure). This is a programming-error signal (a typo'd metric
    name), not a runtime/infrastructure failure, so it is intentionally
    exempt from the broad `except Exception` below.

    Why cache-backend failures (e.g. a Redis outage) are swallowed here
    rather than left to propagate: `record_response_status` (see
    `api/middleware.py`) calls this on *every* HTTP response via
    `MetricsMiddleware`, which is the outermost middleware layer (see that
    module's docstring). Before this fix, a Redis outage turned into an
    unhandled `ConnectionError`/`ConnectionInterrupted` here that propagated
    out of the middleware and produced a 500 on *every single request* —
    including `GET /health/`, the plain liveness probe that exists
    specifically so an orchestrator can tell "is the process up" without
    that answer depending on Redis being reachable (dependency health is
    `GET /health/ready/`'s job, not `/health/`'s). A metrics sink outage
    must degrade observability, never availability — the exact principle
    `api/audit.py::record_audit_event` already applies to audit-log writes
    for the same reason; this brings counter increments in line with it.
    """
    if metric_name not in _COUNTER_REGISTRY:
        raise ValueError(f'Unknown metric: {metric_name!r}. Register it in _COUNTER_REGISTRY first.')
    key = _cache_key(metric_name)
    try:
        # `cache.add` only sets the value if the key does not already exist —
        # this makes the first increment race-safe without a separate
        # existence check; `incr` is then atomic on both LocMemCache and Redis.
        cache.add(key, 0)
        try:
            cache.incr(key, amount)
        except ValueError:
            # Backend-specific edge case (e.g. key evicted between add/incr
            # under memory pressure) — reseed rather than raising out of what
            # is meant to be a best-effort observability hook.
            cache.set(key, amount)
    except Exception:
        logger.warning(
            'metrics_counter_increment_failed',
            extra={'metric': metric_name},
            exc_info=True,
        )


def record_response_status(status_code: int) -> None:
    increment_counter('careflow_http_requests_total')
    if 200 <= status_code < 300:
        increment_counter('careflow_http_responses_2xx_total')
    elif 400 <= status_code < 500:
        increment_counter('careflow_http_responses_4xx_total')
    elif status_code >= 500:
        increment_counter('careflow_http_responses_5xx_total')


def metrics_view(request) -> HttpResponse:
    """Render all registered counters in Prometheus text exposition format.

    Deliberately unauthenticated (like `/health/`) — a metrics scrape
    endpoint typically needs to be reachable by an internal scraper without
    an application-level credential; network-level access control (e.g. a
    firewall rule restricting `/metrics` to the scraper's IP range) is the
    standard way to protect it in a real deployment, documented in the
    README rather than enforced in-app here.
    """
    lines = []
    for name, (help_text, metric_type) in _COUNTER_REGISTRY.items():
        try:
            value = cache.get(_cache_key(name), 0)
        except Exception:
            # Same rationale as `increment_counter`: a cache-backend outage
            # must surface as "0/unknown" in the scrape output, not as a 500
            # on the scrape endpoint itself.
            logger.warning('metrics_counter_read_failed', extra={'metric': name}, exc_info=True)
            value = 0
        lines.append(f'# HELP {name} {help_text}')
        lines.append(f'# TYPE {name} {metric_type}')
        lines.append(f'{name} {value}')
    body = '\n'.join(lines) + '\n'
    return HttpResponse(body, content_type='text/plain; version=0.0.4; charset=utf-8')
