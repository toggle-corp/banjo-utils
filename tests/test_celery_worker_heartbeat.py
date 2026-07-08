from __future__ import annotations

import os
import typing
from unittest.mock import MagicMock

if typing.TYPE_CHECKING:
    from pathlib import Path

    import pytest

from celery import Celery
from celery.worker.components import Timer

from banjo_utils.celery_health.worker import (
    DEFAULT_WORKER_HEARTBEAT_FILE,
    WRITE_INTERVAL,
    WorkerHeartbeatStep,
    setup_worker_heartbeat,
)
from banjo_utils.celery_probe import DEFAULT_HEARTBEAT_FILE, HEARTBEAT_FILE_ENV


def test_write_interval_is_30_seconds():
    assert WRITE_INTERVAL == 30.0


def test_worker_default_path_matches_reader_default():
    # The worker writer and the reader share a default so a no-config setup
    # (no env, no --heartbeat-file) still lines up.
    assert DEFAULT_WORKER_HEARTBEAT_FILE == "/tmp/celery_worker_heartbeat"  # noqa: S108
    assert DEFAULT_WORKER_HEARTBEAT_FILE == DEFAULT_HEARTBEAT_FILE


def test_setup_registers_step_on_worker_blueprint():
    app = Celery("test")
    setup_worker_heartbeat(app)

    assert WorkerHeartbeatStep in typing.cast("typing.Any", app.steps)["worker"]


def test_step_requires_timer():
    assert Timer in WorkerHeartbeatStep.requires


def test_start_touches_immediately_and_schedules_repeat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = str(tmp_path / "worker_hb")
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, path)

    worker = MagicMock()
    step = WorkerHeartbeatStep(worker)
    step.start(worker)

    # Touched immediately so liveness passes before the first interval elapses.
    assert os.path.exists(path)  # noqa: PTH110
    # And a repeating touch is scheduled on the worker's timer.
    worker.timer.call_repeatedly.assert_called_once()
    interval = worker.timer.call_repeatedly.call_args.args[0]
    assert interval == WRITE_INTERVAL


def test_stop_cancels_timer_and_unlinks_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = str(tmp_path / "worker_hb")
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, path)

    worker = MagicMock()
    tref = MagicMock()
    worker.timer.call_repeatedly.return_value = tref

    step = WorkerHeartbeatStep(worker)
    step.start(worker)
    assert os.path.exists(path)  # noqa: PTH110

    step.stop(worker)

    tref.cancel.assert_called_once()
    assert not os.path.exists(path)  # noqa: PTH110


def test_stop_is_safe_when_file_already_gone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = str(tmp_path / "worker_hb")
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, path)

    worker = MagicMock()
    step = WorkerHeartbeatStep(worker)
    step.start(worker)
    os.remove(path)  # noqa: PTH107

    # Should not raise even though the file is already gone.
    step.stop(worker)
