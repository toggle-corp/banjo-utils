from __future__ import annotations

import typing

from django.conf import settings
from django.http import HttpResponse

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest

    # A Sentry ``traces_sampler`` receives the sampling context dict and returns
    # a sample rate. Typed loosely here to avoid a hard dependency on sentry-sdk.
    SamplingContext = dict[str, typing.Any]
    TracesSampler = Callable[[SamplingContext], float]

# Default URLs for the Kubernetes probe endpoints. Override in Django
# settings via BANJO_HEALTH_PROBE_LIVE_URL / BANJO_HEALTH_PROBE_READY_URL.
DEFAULT_LIVE_URL = "/healthz/live/"
DEFAULT_READY_URL = "/healthz/ready/"


def get_health_probe_paths() -> tuple[str, str]:
    """Return the configured ``(live, ready)`` probe paths.

    Trailing slashes are stripped so callers can compare against an incoming
    path without worrying about the slash.
    """
    live: str = getattr(settings, "BANJO_HEALTH_PROBE_LIVE_URL", DEFAULT_LIVE_URL)
    ready: str = getattr(settings, "BANJO_HEALTH_PROBE_READY_URL", DEFAULT_READY_URL)
    return live.rstrip("/"), ready.rstrip("/")


def is_health_probe_path(path: str) -> bool:
    """Return ``True`` if ``path`` targets a probe endpoint.

    Trailing slashes are ignored, so both ``/healthz/live`` and
    ``/healthz/live/`` match.

    Use this anywhere you want to treat probe traffic specially -- e.g. inside
    a Sentry ``traces_sampler`` or ``before_send`` hook, a logging filter, or
    an access-log skip list::

        from banjo_utils.health import extract_sentry_request_health_probe_path, is_health_probe_path

        def traces_sampler(sampling_context):
            if is_health_probe_path(extract_sentry_request_health_probe_path(sampling_context)):
                return 0.0
            return 0.1
    """
    return path.rstrip("/") in get_health_probe_paths()


def extract_sentry_request_health_probe_path(sampling_context: SamplingContext) -> str:
    """Pull the request path out of a Sentry sampling context (WSGI or ASGI).

    Returns an empty string if the context carries no request (e.g. a
    background task transaction). Handy for feeding ``is_health_probe_path``
    from your own ``traces_sampler``.
    """
    environ = sampling_context.get("wsgi_environ")
    if environ:
        return environ.get("PATH_INFO", "")
    scope = sampling_context.get("asgi_scope")
    if scope:
        return scope.get("path", "")
    return ""


def make_sentry_traces_sampler_with_health_probe_ignore(default: float | TracesSampler) -> TracesSampler:
    """Build a Sentry ``traces_sampler`` that never samples probe requests.

    Sentry instruments requests at the WSGI/ASGI layer -- outside Django's
    middleware stack -- so probe hits create transactions (and consume quota)
    even though ``HealthProbeMiddleware`` short-circuits them. This sampler
    returns ``0.0`` for probe paths and delegates everything else to
    ``default``.

    ``default`` may be a plain sample rate or another ``traces_sampler``
    callable to defer to::

        import sentry_sdk
        from banjo_utils.health import make_sentry_traces_sampler_with_health_probe_ignore

        # Use directly with init...
        sentry_sdk.init(traces_sampler=make_sentry_traces_sampler_with_health_probe_ignore(0.1))

        # ...or wrap your own sampler.
        sentry_sdk.init(traces_sampler=make_sentry_traces_sampler_with_health_probe_ignore(my_sampler))
    """

    def traces_sampler(sampling_context: SamplingContext) -> float:
        path = extract_sentry_request_health_probe_path(sampling_context)
        if path and is_health_probe_path(path):
            return 0.0
        if callable(default):
            return default(sampling_context)
        return default

    return traces_sampler


class HealthProbeMiddleware:
    """Serve Kubernetes liveness/readiness probe endpoints.

    Register this as the *first* entry in ``MIDDLEWARE`` so probe requests
    short-circuit before any other middleware runs. This keeps the probes
    cheap and dependency-free: they report whether the WSGI process can
    answer HTTP at all, and never touch the database, cache or session.

    Because the response is returned before ``request.get_host()`` is called,
    probe requests bypass the ``ALLOWED_HOSTS`` check -- so the kubelet may hit
    the pod by IP without any extra probe ``httpHeaders`` configuration.

    Liveness vs readiness:
      - ``/healthz/live/`` answers "is this process wedged?" -- a failure means
        the kubelet should restart the pod.
      - ``/healthz/ready/`` answers "can this pod serve traffic?" -- a failure
        means the pod is pulled from the Service endpoints.

    Both intentionally check only pod-local health (i.e. "the process is up").
    Shared dependencies (DB, Redis, S3) are deliberately *not* checked here: a
    shared-dependency outage would fail every pod's readiness simultaneously,
    draining the Service to zero endpoints and stampeding the dependency on
    recovery. Surface those failures as request errors instead, and use an
    external monitoring tool for deep health checks.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if is_health_probe_path(request.path):
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
