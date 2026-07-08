"""Worker liveness heartbeat via a celery bootstep.

A celery worker is a non-HTTP process, so its liveness is proven by touching a
heartbeat file on the worker's own :class:`~celery.worker.components.Timer`.
The timer runs in the worker's MainProcess; under the (default) **prefork**
pool, long-running tasks execute in forked child processes and never stall the
timer -- so the heartbeat keeps advancing while real work is in flight.

.. caution::
   Under the ``gevent``/``eventlet`` pools the timer shares the single event
   loop with tasks, so a CPU-bound or blocking task *can* stall the heartbeat
   and trigger a liveness restart. The bootstep is intended for prefork.

Wire it up in your ``celery.py`` right after creating the app::

    from banjo_utils.celery_health.worker import setup_worker_heartbeat

    app = Celery("proj")
    setup_worker_heartbeat(app)

The reader side is :mod:`banjo_utils.celery_probe`, run as a kubelet ``exec``
liveness probe.
"""

from __future__ import annotations

import contextlib
import typing
from pathlib import Path

from celery import bootsteps
from celery.worker.components import Timer
from typing_extensions import override

from banjo_utils.celery_health import resolve_writer_heartbeat_file, touch_heartbeat

if typing.TYPE_CHECKING:
    from celery import Celery

# Worker writes its own file, distinct from beat's. Matches the reader's
# DEFAULT_HEARTBEAT_FILE so a no-config setup still lines up.
DEFAULT_WORKER_HEARTBEAT_FILE = "/tmp/celery_worker_heartbeat"  # noqa: S108

# Touch every 30s. The reader's 120s default --max-age gives a 4x margin
# (up to 3 missed touches tolerated). Chatty 1s touches are unnecessary for
# liveness; ~2min wedge detection is fine.
WRITE_INTERVAL = 30.0


class WorkerHeartbeatStep(bootsteps.StartStopStep):
    """Bootstep that periodically touches the worker heartbeat file.

    Requires the worker ``Timer`` so ``call_repeatedly`` is available when the
    step starts. The heartbeat path is resolved from
    ``BANJO_CELERY_HEARTBEAT_FILE`` (set by the chart), falling back to
    :data:`DEFAULT_WORKER_HEARTBEAT_FILE`.
    """

    requires = (Timer,)

    def __init__(self, worker: typing.Any, **kwargs: typing.Any) -> None:
        self.tref: typing.Any = None
        self.heartbeat_file = resolve_writer_heartbeat_file(DEFAULT_WORKER_HEARTBEAT_FILE)
        super().__init__(worker, **kwargs)

    @override
    def start(self, parent: typing.Any) -> None:
        # Touch once up front so liveness passes before the first interval, then
        # keep refreshing on the worker's timer (runs in MainProcess; prefork
        # children never stall it).
        touch_heartbeat(self.heartbeat_file)
        self.tref = parent.timer.call_repeatedly(
            WRITE_INTERVAL,
            touch_heartbeat,
            (self.heartbeat_file,),
        )

    @override
    def stop(self, parent: typing.Any) -> None:
        if self.tref is not None:
            self.tref.cancel()
            self.tref = None
        # Remove the heartbeat on a clean stop so a not-yet-restarted pod looks
        # dead to the probe rather than falsely alive on a stale file.
        with contextlib.suppress(FileNotFoundError):
            Path(self.heartbeat_file).unlink()


def setup_worker_heartbeat(app: Celery) -> type[WorkerHeartbeatStep]:
    """Register the worker heartbeat bootstep on ``app``.

    One-liner to call right after creating your Celery app. Returns the step
    class for reference. Idempotent -- the worker blueprint stores steps in a
    set, so calling twice registers it once.
    """
    # ``app.steps`` is a defaultdict(set) at runtime but celery types it loosely
    # (class-level ``steps = None``); cast so the subscript type-checks.
    worker_steps = typing.cast("typing.Any", app.steps)
    worker_steps["worker"].add(WorkerHeartbeatStep)
    return WorkerHeartbeatStep
