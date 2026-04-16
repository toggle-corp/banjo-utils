from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from django.conf import LazySettings

from io import StringIO
from typing import Any
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.db.utils import OperationalError

from banjo_utils.management.commands.wait_for_resources import (
    TimeoutException,
)


def run_command(*args: Any, **kwargs: Any):
    out, err = StringIO(), StringIO()
    call_command("wait_for_resources", *args, stdout=out, stderr=err, **kwargs)
    return out.getvalue(), err.getvalue()


@patch("banjo_utils.management.commands.wait_for_resources.connections")
@patch("time.sleep", return_value=None)
def test_wait_for_db_retries_then_succeeds(mock_sleep: MagicMock, mock_connections: dict[str, Any]):
    conn = mock_connections["default"]
    conn.ensure_connection.side_effect = [OperationalError, None]

    out, _ = run_command("--db")

    assert "DB is available" in out
    assert mock_sleep.called


@patch("banjo_utils.management.commands.wait_for_resources.cache")
@patch("time.sleep", return_value=None)
def test_wait_for_redis_success(mock_sleep: MagicMock, mock_cache: MagicMock):
    mock_cache.set.return_value = None
    mock_cache.get.return_value = "pong"

    out, _ = run_command("--redis")

    assert "Redis is available" in out
    mock_sleep.assert_not_called()


@patch("banjo_utils.management.commands.wait_for_resources.httpx.get")
@patch("time.sleep", return_value=None)
def test_wait_for_minio_retries_then_succeeds(mock_sleep: MagicMock, mock_get: MagicMock, settings: LazySettings):
    settings.AWS_S3_ENDPOINT_URL = "http://minio:9000"

    mock_get.side_effect = [
        MagicMock(status_code=503),
        MagicMock(status_code=200),
    ]

    out, _ = run_command("--minio")

    assert "Minio is available" in out
    assert mock_sleep.called


@patch("time.sleep", return_value=None)
def test_minio_skipped_when_no_endpoint(mock_sleep: MagicMock, settings: LazySettings):
    settings.AWS_S3_ENDPOINT_URL = None

    out, _ = run_command("--minio")

    assert "Skipping wait" in out
    mock_sleep.assert_not_called()


@patch("banjo_utils.management.commands.wait_for_resources.connections")
@patch("time.sleep")
def test_timeout_handled(mock_sleep: MagicMock, mock_connections: dict[str, Any]):
    mock_connections["default"].ensure_connection.side_effect = OperationalError

    def raise_timeout(_):
        raise TimeoutException

    mock_sleep.side_effect = raise_timeout
    _, err = run_command("--db")
    assert "Timed out" in err


@patch("banjo_utils.management.commands.wait_for_resources.connections")
@patch("banjo_utils.management.commands.wait_for_resources.cache")
@patch("time.sleep", return_value=None)
def test_multiple_flags(mock_sleep: MagicMock, mock_cache: MagicMock, mock_connections: dict[str, Any]):
    mock_connections["default"].ensure_connection.return_value = None
    mock_cache.set.return_value = None
    mock_cache.get.return_value = "pong"

    out, _ = run_command("--db", "--redis")

    assert "DB is available" in out
    assert "Redis is available" in out
