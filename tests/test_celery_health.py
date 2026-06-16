from __future__ import annotations

import builtins
import importlib
import os
import sys
import typing

import pytest
from celery.beat import PersistentScheduler
from django_celery_beat.schedulers import DatabaseScheduler

from banjo_utils.celery_health import (
    DEFAULT_BEAT_HEARTBEAT_FILE,
    HeartbeatSchedulerMixin,
    resolve_writer_heartbeat_file,
)
from banjo_utils.celery_health.database import HeartbeatDatabaseScheduler
from banjo_utils.celery_health.persistent import HeartbeatPersistentScheduler
from banjo_utils.celery_probe import HEARTBEAT_FILE_ENV

if typing.TYPE_CHECKING:
    from pathlib import Path


class _FakeBase:
    """Stand-in for a celery scheduler base recording tick() calls."""

    def __init__(self) -> None:
        self.tick_calls = 0

    def tick(self, *args: typing.Any, **kwargs: typing.Any) -> float:
        self.tick_calls += 1
        return 5.0


class _RaisingBase:
    def tick(self, *args: typing.Any, **kwargs: typing.Any) -> float:
        raise RuntimeError("boom")


def test_resolve_writer_prefers_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, "/from/env")

    assert resolve_writer_heartbeat_file("/default") == "/from/env"


def test_resolve_writer_falls_back_to_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(HEARTBEAT_FILE_ENV, raising=False)

    assert resolve_writer_heartbeat_file("/default") == "/default"


def test_default_beat_path_is_beat_heartbeat():
    assert DEFAULT_BEAT_HEARTBEAT_FILE == "/tmp/celery_beat_heartbeat"  # noqa: S108


def test_mixin_tick_touches_file_and_passes_through_super(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = str(tmp_path / "beat_hb")
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, path)

    class Sched(HeartbeatSchedulerMixin, _FakeBase):
        pass

    sched = Sched()
    result = sched.tick()

    assert result == 5.0  # mixin returns whatever super().tick() returned
    assert sched.tick_calls == 1
    assert os.path.exists(path)  # noqa: PTH110


def test_mixin_does_not_touch_when_super_tick_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Proves the touch happens *after* super().tick() returns -- a tick that
    # never completes must not refresh the heartbeat.
    path = str(tmp_path / "beat_hb")
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, path)

    class Sched(HeartbeatSchedulerMixin, _RaisingBase):
        pass

    with pytest.raises(RuntimeError, match="boom"):
        Sched().tick()

    assert not os.path.exists(path)  # noqa: PTH110


def test_persistent_scheduler_overrides_tick():
    assert issubclass(HeartbeatPersistentScheduler, PersistentScheduler)
    assert issubclass(HeartbeatPersistentScheduler, HeartbeatSchedulerMixin)
    # Mixin must sit before the base in the MRO so its tick() wins.
    assert HeartbeatPersistentScheduler.tick is HeartbeatSchedulerMixin.tick


def test_database_scheduler_overrides_tick():
    assert issubclass(HeartbeatDatabaseScheduler, DatabaseScheduler)
    assert HeartbeatDatabaseScheduler.tick is HeartbeatSchedulerMixin.tick


def test_database_scheduler_raises_friendly_error_without_dcb(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, "banjo_utils.celery_health.database", raising=False)
    real_import = builtins.__import__

    def fake_import(name: str, *args: typing.Any, **kwargs: typing.Any):
        if name.startswith("django_celery_beat"):
            raise ImportError("simulated missing dep")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match="django-celery-beat"):
        importlib.import_module("banjo_utils.celery_health.database")
