from __future__ import annotations

import os
import typing
from pathlib import Path

if typing.TYPE_CHECKING:
    import pytest

from banjo_utils.celery_probe import (
    DEFAULT_MAX_AGE,
    HEARTBEAT_FILE_ENV,
    is_fresh,
    main,
    resolve_heartbeat_file,
)


def _write_heartbeat(path: str, age_seconds: float) -> None:
    """Create ``path`` and backdate its mtime by ``age_seconds``."""
    p = Path(path)
    p.touch()
    mtime = p.stat().st_mtime
    os.utime(path, (mtime, mtime - age_seconds))


def test_is_fresh_true_for_recent_file(tmp_path: Path):
    path = str(tmp_path / "hb")
    _write_heartbeat(path, age_seconds=10)

    assert is_fresh(path, max_age=120) is True


def test_is_fresh_false_for_stale_file(tmp_path: Path):
    path = str(tmp_path / "hb")
    _write_heartbeat(path, age_seconds=300)

    assert is_fresh(path, max_age=120) is False


def test_is_fresh_false_for_missing_file(tmp_path: Path):
    assert is_fresh(str(tmp_path / "does-not-exist"), max_age=120) is False


def test_resolve_prefers_cli_over_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, "/from/env")

    assert resolve_heartbeat_file("/from/cli") == "/from/cli"


def test_resolve_falls_back_to_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, "/from/env")

    assert resolve_heartbeat_file(None) == "/from/env"


def test_resolve_falls_back_to_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(HEARTBEAT_FILE_ENV, raising=False)

    assert resolve_heartbeat_file(None).startswith("/")


def test_main_exits_zero_for_fresh_file(tmp_path: Path):
    path = str(tmp_path / "hb")
    _write_heartbeat(path, age_seconds=5)

    assert main(["--heartbeat-file", path, "--max-age", "120"]) == 0


def test_main_exits_one_for_stale_file(tmp_path: Path):
    path = str(tmp_path / "hb")
    _write_heartbeat(path, age_seconds=300)

    assert main(["--heartbeat-file", path, "--max-age", "120"]) == 1


def test_main_exits_one_for_missing_file(tmp_path: Path):
    assert main(["--heartbeat-file", str(tmp_path / "nope")]) == 1


def test_main_reads_path_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = str(tmp_path / "hb")
    _write_heartbeat(path, age_seconds=5)
    monkeypatch.setenv(HEARTBEAT_FILE_ENV, path)

    assert main([]) == 0


def test_default_max_age_is_120(tmp_path: Path):
    assert DEFAULT_MAX_AGE == 120

    path = str(tmp_path / "hb")
    _write_heartbeat(path, age_seconds=119)
    assert main(["--heartbeat-file", path]) == 0

    _write_heartbeat(path, age_seconds=121)
    assert main(["--heartbeat-file", path]) == 1
