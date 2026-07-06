# Banjo utils

Reusable Django utilities and management commands for Toggle projects.

---

## Features

- Shared management command: `wait_for_resources`
  — Wait for database, Redis, Minio (S3) resources to be available before startup
- Create Initial Users: `create_initial_users`
    - Create Users with specified roles and permissions, useful to populate the database with default users during development or testing
- Health endpoints: `HealthProbeMiddleware`
    - Dependency-free `/healthz/live/` and `/healthz/ready/` endpoints for Kubernetes liveness/readiness probes
- Celery worker & beat health: `banjo-celery-probe` + `banjo_utils.celery_health`
    - Heartbeat-file liveness probes for the non-HTTP celery worker and beat processes

---

## Installation

**Using [uv](https://github.com/astral-sh/uv):**
```bash
uv pip install "git+https://github.com/toggle-corp/banjo-utils.git@v0.1.0"
```

Or add to your `pyproject.toml`:
```toml
[project]
dependencies = [
    "banjo-utils",
]

[tool.uv.sources]
banjo-utils = { git = "https://github.com/toggle-corp/banjo-utils", tag = "v0.1.0" }
```

---

## Setup in Django

- **Add to `INSTALLED_APPS` in your Django project's `settings.py`:**

    ```python
    INSTALLED_APPS = [
        # ... your other apps ...
        "banjo_utils",
    ]
    ```

---

## Usage

**Access the management command:**
```bash
python manage.py wait_for_resources --db --cache
```

**Command options:**
- `--db`: Wait for database
- `--cache`: Wait for the Django cache backend (requires a redis client in your project, e.g. via `django-redis` or `redis`; it is not a banjo-utils runtime dependency)
- `--minio`: Wait for Minio (S3 storage)
- `--celery-broker`: Wait for the Celery broker at `CELERY_BROKER_URL` (requires `kombu`, installed with celery; it is not a banjo-utils runtime dependency)
- `--timeout`: Set max wait time (seconds)

**Examples:**
```bash
python manage.py wait_for_resources --db --cache
python manage.py wait_for_resources --timeout 300 --minio --celery-broker
python manage.py create_initial_users --users-json="
[
    {
        "username": "admin",
        "email": "test@example.com",
        "password": "admin123",
        "is_superuser": true,
        "is_staff": true
    },
    {
        "username": "user1",
        "email": "user1@gmail.com",
        "password": "user123",
        "is_superuser": false,
        "is_staff": false
    }
]'
```

---

## Health endpoints

`HealthProbeMiddleware` serves dependency-free endpoints for Kubernetes liveness
and readiness probes:

- `GET /healthz/live/` — liveness. Returns `200 ok` if the WSGI process can
  answer HTTP. A failure tells the kubelet to restart the pod.
- `GET /healthz/ready/` — readiness. Returns `200 ok` once the process is up. A
  failure pulls the pod from the Service endpoints.

Both endpoints check only pod-local health. Shared dependencies (DB, Redis, S3)
are deliberately **not** checked: a shared-dependency outage would fail every
pod's readiness at once, draining the Service to zero endpoints and stampeding
the dependency on recovery. Use a deep health-check tool (e.g.
[`django-health-check`](https://github.com/revsys/django-health-check)) plus
external monitoring for that.

**Register the middleware first** in `settings.py`, so probe requests
short-circuit before any other middleware runs (this also bypasses the
`ALLOWED_HOSTS` check, so the kubelet may hit the pod by IP):

```python
MIDDLEWARE = [
    "banjo_utils.health.HealthProbeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # ... your other middleware ...
]
```

Both trailing-slash and slash-less forms are accepted (`/healthz/live` and
`/healthz/live/`). Override the paths via settings if they conflict with
existing routes:

```python
BANJO_HEALTH_PROBE_LIVE_URL = "/healthz/live/"
BANJO_HEALTH_PROBE_READY_URL = "/healthz/ready/"
```

> Probe scheduling (intervals, thresholds) and graceful-shutdown draining
> (`preStop`) are deploy-side concerns configured in your Kubernetes manifests
> / Helm chart, not here.

### Keeping probe requests out of Sentry

`banjo-utils` never talks to Sentry, and these endpoints raise no exceptions, so
**error** monitoring stays quiet. **Performance/tracing** is different: Sentry
instruments requests at the WSGI/ASGI layer — outside Django's middleware stack
— so probe hits create transactions (and consume quota) even though the
middleware short-circuits them. Filter them out in your `sentry_sdk.init`:

```python
import sentry_sdk
from banjo_utils.health import make_sentry_traces_sampler_with_health_probe_ignore

# Use directly with init — pass your normal sample rate as the fallback...
sentry_sdk.init(traces_sampler=make_sentry_traces_sampler_with_health_probe_ignore(0.1))

# ...or wrap your own sampler (it's called for non-probe requests).
sentry_sdk.init(traces_sampler=make_sentry_traces_sampler_with_health_probe_ignore(my_sampler))
```

If you maintain your own `traces_sampler`, pair the `is_health_probe_path`
predicate with the `extract_sentry_request_health_probe_path` helper (which reads the path out of
Sentry's WSGI/ASGI sampling context):

```python
from banjo_utils.health import extract_sentry_request_health_probe_path, is_health_probe_path

def traces_sampler(sampling_context):
    if is_health_probe_path(extract_sentry_request_health_probe_path(sampling_context)):
        return 0.0
    return 0.1
```

`is_health_probe_path` is just a path predicate, so it also drops into a
`before_send` hook or a logging filter — pass it whatever path that context
exposes (`event["request"]["url"]`, `record.args`, `request.path`, …). All
helpers honour the `BANJO_HEALTH_*` URL overrides above.

---

## Celery worker & beat health

Celery worker and beat are **non-HTTP** processes, so `HealthProbeMiddleware`
above does not apply to them. Instead each process periodically *touches* a
0-byte heartbeat file, and the kubelet runs the stdlib `banjo-celery-probe`
reader as an `exec` **liveness** probe that `stat()`s the file and fails when
it is missing or stale.

Same philosophy as the HTTP probes: pod-local, cheap, dependency-free, detects
a *wedged* process. It deliberately does **no** broker round-trip — `celery
inspect ping` was rejected because it causes false-positive restarts under load
and adds broker CPU cost (see
[celery/celery#4079](https://github.com/celery/celery/issues/4079)).

Neither `celery` nor `django-celery-beat` is a runtime dependency of
banjo-utils — a celery project already has celery installed, and beat users add
`django-celery-beat` themselves.

### The probe reader

`banjo-celery-probe` is installed as a console script (stdlib-only; it imports
neither celery nor django, so it stays fast and works in stripped images):

```bash
banjo-celery-probe [--heartbeat-file PATH] [--max-age SECONDS]
```

It exits `0` if the file was touched within `--max-age` seconds (default
`120`), and `1` if the file is **stale or missing**. The path is resolved from,
in order: the `--heartbeat-file` arg, the `BANJO_CELERY_HEARTBEAT_FILE` env var
(inherited from the writer's container), then a code default.

> The reader's `--max-age` is just a small staleness check. The real
> wedge-detection budget is the kubelet's `failureThreshold × periodSeconds`,
> set in your manifest/Helm chart (same way `api.probes` already reasons). Use
> a `startupProbe` reusing the same exec command for boot grace rather than
> `initialDelaySeconds`.

### Worker

Register the heartbeat bootstep right after creating your Celery app, e.g. in
`main/celery.py`:

```python
from celery import Celery
from banjo_utils.celery_health.worker import setup_worker_heartbeat

app = Celery("main")
setup_worker_heartbeat(app)  # touches /tmp/celery_worker_heartbeat every 30s
```

The bootstep runs on the worker's own `Timer` (in the parent `MainProcess`).
Under the default **prefork** pool, long-running tasks execute in forked child
processes and never stall the timer, so the heartbeat keeps advancing while
real work is in flight.

> **Caveat:** under the `gevent`/`eventlet` pools the timer shares the single
> event loop with tasks, so a CPU-bound or blocking task can stall the
> heartbeat and trigger a liveness restart. The bootstep targets prefork.

### Beat

Beat is customised via celery's `--scheduler` flag (not a bootstep). The
scheduler touches the heartbeat file **after** each `tick()` completes, proving
a tick actually ran:

```bash
# Primary path: django-celery-beat's DatabaseScheduler (most projects)
celery -A main beat --scheduler banjo_utils.celery_health.database.HeartbeatDatabaseScheduler

# Plain celery beat (no django-celery-beat)
celery -A main beat --scheduler banjo_utils.celery_health.persistent.HeartbeatPersistentScheduler
```

To wrap any other scheduler base, mix in `HeartbeatSchedulerMixin`:

```python
from banjo_utils.celery_health import HeartbeatSchedulerMixin
from somewhere import SomeScheduler

class HeartbeatSomeScheduler(HeartbeatSchedulerMixin, SomeScheduler):
    pass
```

Beat writes `/tmp/celery_beat_heartbeat` by default — a **different** file from
the worker — so point the beat probe at it via `--heartbeat-file` or
`BANJO_CELERY_HEARTBEAT_FILE` (the reader's own default targets the worker
file). The reader's `120s` default `--max-age` suits `DatabaseScheduler` (tick
cadence ~5s → ample margin). For `HeartbeatPersistentScheduler` the
`max_interval` is 300s, so set `--max-age` **above** 300s.

### Deployment notes

These are manifest/Helm concerns (no code in banjo-utils):

- **Graceful shutdown is automatic on `SIGTERM`** — celery's warm shutdown
  stops accepting new tasks and drains in-flight ones. The only lever is
  `terminationGracePeriodSeconds`.
- **Beat must be a singleton.** Deploy it with `strategy: Recreate` (or
  `maxSurge: 0`) so a rolling update never runs two beats at once — duplicate
  schedulers fire duplicate scheduled tasks.
- **Heartbeat file storage.** The file is 0 bytes (`touch` only bumps mtime),
  but a container's `/tmp` is the node-disk-backed overlay layer. To avoid disk
  writes (SSD wear) and to satisfy `readOnlyRootFilesystem: true`, mount a tiny
  RAM-backed `emptyDir { medium: Memory, sizeLimit: 1Mi }` at the heartbeat
  directory and set `BANJO_CELERY_HEARTBEAT_FILE` to a path inside it.
- **Celery version:** 5.6.1 broke heartbeat-file creation; fixed in **5.6.2**.
  Use ≥5.6.2 (or a 5.5.x release).

---

## Development

1. Clone the repository
2. Install as editable with uv:
    ```bash
    uv sync --all-groups --all-extras
    ```
3. Type checking
    ```bash
    uv run --all-groups --all-extras pyright
    ```
3. Running Tests
    ```bash
    uv run --all-groups --all-extras pytest
    ```
4. Run commands for example project
    ```bash
    uv run --all-groups --all-extras python example/manage.py runserver
    uv run --all-groups --all-extras python example/manage.py wait_for_resources --db --cache --celery-broker
    ```

---

## License

Apache-2.0
