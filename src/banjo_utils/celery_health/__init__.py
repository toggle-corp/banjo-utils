"""Pod-local liveness heartbeats for celery worker & beat processes.

Celery worker and beat are non-HTTP processes, so the HTTP
``HealthProbeMiddleware`` in :mod:`banjo_utils.health` does not apply. Instead
each process periodically *touches* a heartbeat file, and the kubelet runs the
stdlib :mod:`banjo_utils.celery_probe` reader as an ``exec`` liveness probe to
``stat()`` that file. Mirrors the philosophy of ``health.py``: pod-local,
cheap, dependency-free, detects a wedged process -- and deliberately avoids
per-probe broker round-trips (``celery inspect ping`` was rejected for its
false-positive restarts under load and broker CPU cost; see
https://github.com/celery/celery/issues/4079).

This package is split so the dependency surface stays minimal:

- This module (``__init__``) holds :class:`HeartbeatSchedulerMixin`, which is
  **base-agnostic and has no runtime celery/django dependency** -- celery is
  only referenced under ``TYPE_CHECKING``.
- :mod:`~banjo_utils.celery_health.persistent` subclasses celery's own
  ``PersistentScheduler`` (celery-only, the dependency-free test vehicle).
- :mod:`~banjo_utils.celery_health.database` subclasses
  ``django_celery_beat``'s ``DatabaseScheduler`` (the primary path for most
  projects); it imports its base at class-definition time, so it lives in its
  own submodule and is only loaded when ``--scheduler`` points at it.
- :mod:`~banjo_utils.celery_health.worker` holds the worker bootstep.

Neither ``celery`` nor ``django-celery-beat`` is a runtime dependency of
banjo-utils: a celery project already has celery installed, and beat users add
``django-celery-beat`` themselves.
"""

from __future__ import annotations

import os
import typing
from pathlib import Path

from banjo_utils.celery_probe import HEARTBEAT_FILE_ENV

# Beat writes a different file than the worker so the two heartbeats never
# clobber one another when wrongly configured to share a dir. A beat liveness
# probe must therefore point the reader at this path (via --heartbeat-file or
# the BANJO_CELERY_HEARTBEAT_FILE env), since the reader's own default targets
# the worker file.
DEFAULT_BEAT_HEARTBEAT_FILE = "/tmp/celery_beat_heartbeat"  # noqa: S108


def resolve_writer_heartbeat_file(default: str) -> str:
    """Resolve the path a writer touches: ``BANJO_CELERY_HEARTBEAT_FILE`` or ``default``."""
    return os.environ.get(HEARTBEAT_FILE_ENV) or default


def touch_heartbeat(path: str) -> None:
    """Create ``path`` if missing and bump its mtime (a 0-byte heartbeat)."""
    Path(path).touch()


class HeartbeatSchedulerMixin:
    """Mix into any celery beat ``Scheduler`` to touch a heartbeat file each tick.

    Override the scheduler with ``celery beat --scheduler <dotted.path>``. The
    file is touched **after** ``super().tick()`` returns, so the heartbeat only
    advances when a tick actually completes (a wedged tick goes stale and the
    liveness probe restarts the pod).

    The path comes from ``BANJO_CELERY_HEARTBEAT_FILE`` (set by the chart),
    falling back to :data:`heartbeat_file_default`.

    .. warning::
       The heartbeat advances **only as often as beat ticks**, and the tick
       cadence is capped by the scheduler's ``max_interval``. The probe's
       ``--max-age`` must therefore exceed that cap, or a perfectly healthy beat
       gets restarted between ticks. ``DatabaseScheduler`` defaults to ~5s
       (fine), but ``max_interval`` is operator-overridable via
       ``celery beat --max-interval <seconds>``: passing e.g. ``--max-interval
       3600`` makes beat sleep up to an hour between ticks, so the heartbeat
       goes stale and the probe false-restarts beat. Keep ``--max-interval``
       (if set at all) below the probe's ``--max-age``.
    """

    #: Per-class default path; overridden by the env var at tick time.
    heartbeat_file_default: typing.ClassVar[str] = DEFAULT_BEAT_HEARTBEAT_FILE

    def tick(self, *args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        # ``super()`` is the real scheduler base this mixin is combined with;
        # cast to Any since the mixin itself is base-agnostic (no celery dep).
        result = typing.cast("typing.Any", super()).tick(*args, **kwargs)
        touch_heartbeat(resolve_writer_heartbeat_file(self.heartbeat_file_default))
        return result
