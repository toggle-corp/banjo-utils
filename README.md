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
python manage.py wait_for_resources --db --redis
```

**Command options:**
- `--db`: Wait for database
- `--redis`: Wait for Redis server
- `--minio`: Wait for Minio (S3 storage)
- `--timeout`: Set max wait time (seconds)

**Examples:**
```bash
python manage.py wait_for_resources --db --redis
python manage.py wait_for_resources --timeout 300 --minio
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
    uv run --all-groups --all-extras python example/manage.py wait_for_resources --db --redis
    ```

---

## License

Apache-2.0
