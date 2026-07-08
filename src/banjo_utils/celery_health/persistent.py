"""Heartbeat scheduler for celery's built-in ``PersistentScheduler``.

Use this when you run plain celery beat (no ``django-celery-beat``)::

    celery -A proj beat --scheduler banjo_utils.celery_health.persistent.HeartbeatPersistentScheduler

``PersistentScheduler`` has a ``max_interval`` of 300s, so a beat liveness
probe for this scheduler must set ``--max-age`` above 300s. Most projects use
the ``DatabaseScheduler`` instead (see
:mod:`banjo_utils.celery_health.database`); this dependency-free subclass is
kept primarily as the test vehicle for the mixin.
"""

from __future__ import annotations

from celery.beat import PersistentScheduler

from banjo_utils.celery_health import HeartbeatSchedulerMixin


class HeartbeatPersistentScheduler(HeartbeatSchedulerMixin, PersistentScheduler):
    """``PersistentScheduler`` that touches a heartbeat file after each tick."""
