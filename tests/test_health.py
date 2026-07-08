from __future__ import annotations

import typing

from django.http import HttpResponse
from django.test import RequestFactory

from banjo_utils.health import (
    DEFAULT_LIVE_URL,
    DEFAULT_READY_URL,
    HealthProbeMiddleware,
    extract_sentry_request_health_probe_path,
    get_health_probe_paths,
    is_health_probe_path,
    make_sentry_traces_sampler_with_health_probe_ignore,
)

if typing.TYPE_CHECKING:
    from django.http import HttpRequest
    from pytest_django.fixtures import SettingsWrapper

_SENTINEL = "downstream-was-called"


def _build_middleware() -> HealthProbeMiddleware:
    def get_response(request: HttpRequest) -> HttpResponse:
        return HttpResponse(_SENTINEL)

    return HealthProbeMiddleware(get_response)


def test_live_endpoint_returns_ok():
    middleware = _build_middleware()
    response = middleware(RequestFactory().get(DEFAULT_LIVE_URL))

    assert response.status_code == 200
    assert response.content == b"ok"
    assert response["Content-Type"] == "text/plain"


def test_ready_endpoint_returns_ok():
    middleware = _build_middleware()
    response = middleware(RequestFactory().get(DEFAULT_READY_URL))

    assert response.status_code == 200
    assert response.content == b"ok"


def test_probe_paths_short_circuit_downstream():
    middleware = _build_middleware()
    response = middleware(RequestFactory().get(DEFAULT_LIVE_URL))

    assert response.content != _SENTINEL.encode()


def test_non_probe_path_falls_through():
    middleware = _build_middleware()
    response = middleware(RequestFactory().get("/some/other/path/"))

    assert response.content == _SENTINEL.encode()


def test_trailing_slash_is_tolerated():
    middleware = _build_middleware()

    with_slash = middleware(RequestFactory().get("/healthz/live/"))
    without_slash = middleware(RequestFactory().get("/healthz/live"))

    assert with_slash.content == b"ok"
    assert without_slash.content == b"ok"


def test_urls_are_configurable(settings: SettingsWrapper):
    settings.BANJO_HEALTH_PROBE_LIVE_URL = "/livez"
    settings.BANJO_HEALTH_PROBE_READY_URL = "/readyz"
    middleware = _build_middleware()

    assert middleware(RequestFactory().get("/livez")).content == b"ok"
    assert middleware(RequestFactory().get("/readyz")).content == b"ok"
    # The defaults no longer match once overridden.
    assert middleware(RequestFactory().get(DEFAULT_LIVE_URL)).content == _SENTINEL.encode()


def test_disallowed_host_is_not_checked():
    # Probe requests arrive with the pod IP as Host; the middleware must
    # answer without triggering the ALLOWED_HOSTS check.
    middleware = _build_middleware()
    request = RequestFactory().get(DEFAULT_LIVE_URL, HTTP_HOST="10.1.2.3")
    response = middleware(request)

    assert response.status_code == 200
    assert response.content == b"ok"


def test_get_health_probe_paths_defaults():
    assert get_health_probe_paths() == ("/healthz/live", "/healthz/ready")


def test_get_health_probe_paths_respects_overrides(settings: SettingsWrapper):
    settings.BANJO_HEALTH_PROBE_LIVE_URL = "/livez/"
    settings.BANJO_HEALTH_PROBE_READY_URL = "/readyz/"

    assert get_health_probe_paths() == ("/livez", "/readyz")


def test_is_health_probe_path():
    assert is_health_probe_path("/healthz/live/")
    assert is_health_probe_path("/healthz/live")
    assert is_health_probe_path("/healthz/ready/")
    assert not is_health_probe_path("/")
    assert not is_health_probe_path("/api/v1/users/")


def test_extract_sentry_request_health_probe_path():
    assert extract_sentry_request_health_probe_path({"wsgi_environ": {"PATH_INFO": "/healthz/live/"}}) == "/healthz/live/"
    assert extract_sentry_request_health_probe_path({"asgi_scope": {"path": "/healthz/ready"}}) == "/healthz/ready"
    assert extract_sentry_request_health_probe_path({}) == ""


def test_sentry_sampler_drops_probe_requests_wsgi():
    sampler = make_sentry_traces_sampler_with_health_probe_ignore(0.25)

    probe = {"wsgi_environ": {"PATH_INFO": "/healthz/live/"}}
    normal = {"wsgi_environ": {"PATH_INFO": "/api/v1/users/"}}

    assert sampler(probe) == 0.0
    assert sampler(normal) == 0.25


def test_sentry_sampler_drops_probe_requests_asgi():
    sampler = make_sentry_traces_sampler_with_health_probe_ignore(0.25)

    probe = {"asgi_scope": {"path": "/healthz/ready"}}

    assert sampler(probe) == 0.0


def test_sentry_sampler_delegates_to_callable_default():
    def inner(sampling_context: dict[str, object]) -> float:
        return 0.5 if sampling_context.get("flagged") else 0.1

    sampler = make_sentry_traces_sampler_with_health_probe_ignore(inner)

    assert sampler({"wsgi_environ": {"PATH_INFO": "/healthz/live/"}}) == 0.0
    assert sampler({"wsgi_environ": {"PATH_INFO": "/x/"}}) == 0.1
    assert sampler({"wsgi_environ": {"PATH_INFO": "/x/"}, "flagged": True}) == 0.5


def test_sentry_sampler_with_empty_context_uses_default():
    sampler = make_sentry_traces_sampler_with_health_probe_ignore(0.3)

    assert sampler({}) == 0.3
