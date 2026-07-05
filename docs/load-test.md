# Load Testing Findings

**Status: dev-environment approximation, not a production benchmark.**

These numbers come from running [locust](https://locust.io/)
(`scripts/locustfile.py`) against `python manage.py runserver` on a single
laptop-class machine, backed by SQLite, with **no** Redis/Celery worker
running (so `CELERY_TASK_ALWAYS_EAGER=True` — every domain event was
processed synchronously in-process; see `careflow/settings.py`). This
environment has no access to a real staging/production deployment
(managed Postgres, a real Gunicorn multi-worker fleet, a real Celery
worker pool, a real Redis instance) to benchmark against instead.

**What this is good for:** identifying *qualitative* bottlenecks and
confirming the app's own architectural claims (e.g. "the token endpoint's
throttle is the first thing to saturate, not the database") — the kind of
signal that transfers to a real deployment even if the specific
millisecond numbers do not.

**What this is NOT good for:** capacity planning, SLA commitments, or any
claim about how this API performs under real production traffic on real
production infrastructure. Treat every number below as "true for this one
laptop, this one run, this one day" — not as a production benchmark.

## Method

1. `python manage.py migrate && python manage.py setup_roles && python manage.py seed_demo_data --reset --password <redacted>`
2. `python manage.py runserver 127.0.0.1:8731` (SQLite, `DEBUG=true`, default throttle rates temporarily raised to isolate endpoint latency from throttle rejection — see "Two separate runs" below)
3. `locust -f scripts/locustfile.py --host http://127.0.0.1:8731 --headless --users N --spawn-rate N --run-time 15s`
4. Repeated for `N` in `{5, 20, 50, 100}` concurrent simulated users.

Traffic mix per simulated user (see `scripts/locustfile.py`): 30% `GET
/api/v1/patients/` (paginated list), 20% `GET /api/v1/analytics/overview/`
(the cached analytics endpoint), 20% `POST /api/v1/predict/health-risk/`
(public, uncached, CPU-bound scoring), 10% `POST /api/v1/checkins/`
(triggers domain-event processing).

### Two separate runs, on purpose

**Run A — default throttle rates** (`DRF_THROTTLE_ANON=60/minute`,
`DRF_THROTTLE_USER=300/minute`, `DRF_THROTTLE_PREDICT=20/minute`,
`DRF_THROTTLE_TOKEN=10/minute`, i.e. the real defaults from
`careflow/settings.py`). Finding below.

**Run B — throttle rates temporarily raised** (`.../minute` values raised
to `100000/minute` via env vars for the duration of the test only) to
isolate genuine endpoint/database latency from throttle rejections. All
the latency numbers in the "Findings" tables below are from Run B; Run A's
result is reported separately because it *is* itself a real finding.

## Finding 1 (Run A): the throttle is the first thing to saturate, not the database

At just 20 concurrent simulated users hitting the public
`/api/v1/predict/health-risk/` endpoint with **default** throttle
settings, essentially all requests after the first ~20/minute were
rejected with `429`, and the same was true for `/api/v1/patients/` and
`/api/v1/analytics/overview/` once the blanket per-user 300/minute rate
was divided across concurrent simulated identities sharing one token in a
15-second burst. **This is the throttle working as designed** (SEC-05/
SEC-09 — scoped rate limiting is meant to reject exactly this kind of
burst), not a bug — but it is worth stating plainly as a load-test
finding: under this test's traffic shape, rate limiting becomes the
binding constraint on throughput long before database contention does.
Any real capacity-planning exercise for this API has to model expected
legitimate traffic against these throttle ceilings first.

## Finding 2 (Run B): median latency stays low through 50 concurrent users, degrades sharply at 100

| Concurrent users | Aggregate p50 | Aggregate p95 | Aggregate p99 | Notable errors |
|---|---|---|---|---|
| 5   | 11 ms  | 23 ms  | 28 ms   | none (throttle raised) |
| 20  | 9 ms   | 29 ms  | 74 ms   | none (throttle raised) |
| 50  | 9 ms   | 68 ms  | 1,100 ms | 3 connection resets |
| 100 | 31 ms  | 420 ms | 1,100 ms | 11 connection resets |

Read this as: this single-process dev server, on SQLite, comfortably
absorbs the test's traffic mix up to ~50 concurrent simulated users with
sub-100ms p95 latency, then degrades sharply by 100 concurrent users (p95
jumps 6x, and a small number of connections are reset outright). The
inflection point between 50 and 100 is the most actionable single number
from this exercise — though, again, specific to `runserver` + SQLite on
this machine, not to Gunicorn + Postgres in a real deployment.

## Finding 3: `/api/v1/checkins/` (which triggers domain-event processing) does not stand out as disproportionately slower than read-only endpoints

At every concurrency level tested, `POST /api/v1/checkins/` (which
synchronously runs workflow-rule matching via
`emit_domain_event(auto_process=True)` in this no-Redis dev configuration)
showed latency in the same range as the plain read endpoints, not
dramatically worse. This is consistent with the demo dataset's workflow
rule set being small (3 rules) and each rule's action (create an alert,
appointment, or referral) being a handful of fast ORM writes — i.e. the
*current* demo-data-scale synchronous processing genuinely is cheap enough
not to show up as the dominant cost yet. This is exactly the caveat the
Celery migration (see README "Known Tradeoffs" / "Lessons Learned")
anticipates: the risk is not that synchronous processing is slow *today*
at this data volume, it's that it scales linearly with the number of
active `WorkflowRule` rows and the cost of each one's action, with no
circuit breaker between a slow/misbehaving rule and every future clinical
write of that event type. This test cannot demonstrate that failure mode
without a deliberately pathological rule (e.g. one with `scheduled_in_hours`
set to trigger an expensive query), which was out of scope for this pass.

## Finding 4: Celery async dispatch itself was not independently load-tested

Because this environment has no running Redis instance or Celery worker
process, `CELERY_TASK_ALWAYS_EAGER=True` for every run above — meaning
`process_domain_event_task.delay(...)` executed synchronously in-process,
identically to the pre-Celery code path. **The actual latency win from
moving domain-event processing off the request thread (the core promise
of the Celery migration) is not demonstrated by this load test** and
would require a real `docker-compose up` environment with `web`, `worker`,
and `redis` all running to measure honestly. This is flagged explicitly
rather than implied, per this document's own "what this is NOT good for"
caveat above.

## Honest summary

- The three analytics endpoints' new short-TTL cache (see README "Caching")
  was not independently isolated in this test (Run B's analytics numbers
  are a mix of cache hits and misses depending on request timing within
  the 60-second TTL window) — a cleaner follow-up would force a
  cache-cold vs. cache-warm comparison directly.
- All numbers are from one machine, one run, one day, under `runserver`
  (not Gunicorn) and SQLite (not Postgres). They should be treated as
  directional, not authoritative.
- The single most concrete, reusable finding is Finding 1: rate limiting,
  not the database, is the first bottleneck this API's default
  configuration hits under concurrent load — which is a reasonable
  security/availability tradeoff for a public-facing demo endpoint, but
  worth knowing explicitly rather than discovering by accident.
