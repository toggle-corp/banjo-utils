"""Heartbeat scheduler for ``django-celery-beat``'s ``DatabaseScheduler``.

This is the **primary** beat path -- most projects schedule via the database.
Use it with::

    celery -A proj beat --scheduler banjo_utils.celery_health.database.HeartbeatDatabaseScheduler

``django-celery-beat`` is **not** a runtime dependency of banjo-utils, so this
module is isolated: importing it (only when ``--scheduler`` points here) is
what pulls in the base class. If the package is missing we re-raise with a
friendly, actionable message.
"""

from __future__ import annotations

try:
    from django_celery_beat.schedulers import DatabaseScheduler
except ImportError as e:
    raise ImportError(
        "HeartbeatDatabaseScheduler requires django-celery-beat, "
        "which is not a banjo-utils runtime dependency. Install it in your project.",
    ) from e

from banjo_utils.celery_health import HeartbeatSchedulerMixin


class HeartbeatDatabaseScheduler(HeartbeatSchedulerMixin, DatabaseScheduler):
    """``DatabaseScheduler`` that touches a heartbeat file after each tick."""
