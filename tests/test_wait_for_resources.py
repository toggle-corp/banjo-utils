from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from django.conf import LazySettings

import sys
from io import StringIO
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import django
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.utils import OperationalError
from kombu.exceptions import OperationalError as KombuOperationalError
from storages.backends.s3 import S3Storage

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
def test_wait_for_cache_success(mock_sleep: MagicMock, mock_cache: MagicMock):
    mock_cache.set.return_value = None
    mock_cache.get.return_value = "pong"

    out, _ = run_command("--cache")

    assert "Cache is available" in out
    mock_sleep.assert_not_called()


@patch("kombu.Connection")
@patch("time.sleep", return_value=None)
def test_wait_for_celery_broker_retries_then_succeeds(
    mock_sleep: MagicMock,
    mock_connection: MagicMock,
    settings: LazySettings,
):
    settings.CELERY_BROKER_URL = "amqp://guest:guest@rabbitmq:5672//"

    conn = mock_connection.return_value.__enter__.return_value
    conn.ensure_connection.side_effect = [KombuOperationalError, None]

    out, _ = run_command("--celery-broker")

    assert "Celery broker is available" in out
    assert mock_sleep.called


@patch("time.sleep", return_value=None)
def test_celery_broker_skipped_when_no_broker_url(mock_sleep: MagicMock, settings: LazySettings):
    settings.CELERY_BROKER_URL = None

    out, _ = run_command("--celery-broker")

    assert "Skipping wait" in out
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

    out, _ = run_command("--db", "--cache")

    assert "DB is available" in out
    assert "Cache is available" in out


S3_BACKEND = "storages.backends.s3.S3Storage"
FS_BACKEND = "django.core.files.storage.FileSystemStorage"

requires_django_storages_setting = pytest.mark.skipif(
    django.VERSION < (4, 2),
    reason="settings.STORAGES requires Django 4.2+",
)


def s3_storage(bucket_name: str) -> dict[str, Any]:
    return {"BACKEND": S3_BACKEND, "OPTIONS": {"bucket_name": bucket_name}}


def storages_setting(**s3_buckets: str) -> dict[str, Any]:
    # S3 storages use non-default aliases: on Django 4.2, overriding STORAGES in
    # tests also overrides DEFAULT_FILE_STORAGE/STATICFILES_STORAGE, which drops
    # the OPTIONS of the "default" and "staticfiles" aliases.
    return {
        "default": {"BACKEND": FS_BACKEND},
        "staticfiles": {"BACKEND": FS_BACKEND},
        **{alias: s3_storage(bucket) for alias, bucket in s3_buckets.items()},
    }


def not_found() -> ClientError:
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket")


@pytest.fixture
def s3_client():
    """Mock boto3 client returned by every S3Storage's ``connection.meta.client``."""
    with patch.object(S3Storage, "connection", new_callable=PropertyMock) as mock_connection:
        yield mock_connection.return_value.meta.client


def head_bucket_calls(client: MagicMock) -> list[str]:
    return [call.kwargs["Bucket"] for call in client.head_bucket.call_args_list]


@requires_django_storages_setting
@patch("time.sleep", return_value=None)
def test_wait_for_s3_multiple_buckets_success(mock_sleep: MagicMock, s3_client: MagicMock, settings: LazySettings):
    settings.STORAGES = storages_setting(media="media", static="static")

    out, _ = run_command("--s3")

    assert "Waiting for S3 bucket 'media' (storage 'media')" in out
    assert "Waiting for S3 bucket 'static' (storage 'static')" in out
    assert "S3 is available" in out
    assert sorted(head_bucket_calls(s3_client)) == ["media", "static"]
    mock_sleep.assert_not_called()


@requires_django_storages_setting
@patch("time.sleep", return_value=None)
def test_wait_for_s3_retries_then_succeeds(mock_sleep: MagicMock, s3_client: MagicMock, settings: LazySettings):
    settings.STORAGES = storages_setting(media="media", static="static")

    attempts: dict[str, int] = {}

    def head_bucket(Bucket: str):
        attempts[Bucket] = attempts.get(Bucket, 0) + 1
        if Bucket == "static" and attempts[Bucket] == 1:
            raise not_found()

    s3_client.head_bucket.side_effect = head_bucket

    out, _ = run_command("--s3")

    assert "S3 bucket 'static' (storage 'static') not available: ClientError" in out
    assert "S3 is available" in out
    assert attempts == {"media": 1, "static": 2}
    assert mock_sleep.call_count == 1


@requires_django_storages_setting
@patch("time.sleep")
def test_wait_for_s3_timeout(mock_sleep: MagicMock, s3_client: MagicMock, settings: LazySettings):
    settings.STORAGES = storages_setting(media="media")
    s3_client.head_bucket.side_effect = EndpointConnectionError(endpoint_url="http://minio:9000/media")

    def raise_timeout(_):
        raise TimeoutException

    mock_sleep.side_effect = raise_timeout

    out, err = run_command("--s3")

    assert "not available: EndpointConnectionError" in out
    assert "S3 is available" not in out
    assert "Timed out" in err


@requires_django_storages_setting
@patch("time.sleep", return_value=None)
def test_wait_for_s3_no_s3_storages(mock_sleep: MagicMock, s3_client: MagicMock, settings: LazySettings):
    settings.STORAGES = storages_setting()

    out, _ = run_command("--s3")

    assert "No S3-backed storage is configured. Skipping wait" in out
    s3_client.head_bucket.assert_not_called()
    mock_sleep.assert_not_called()


@requires_django_storages_setting
@patch("time.sleep", return_value=None)
def test_wait_for_s3_skips_non_s3_storages(mock_sleep: MagicMock, s3_client: MagicMock, settings: LazySettings):
    settings.STORAGES = {
        **storages_setting(media="media"),
        "uploads": {"BACKEND": FS_BACKEND},
        "legacy": {"BACKEND": "storages.backends.s3boto3.S3Boto3Storage", "OPTIONS": {"bucket_name": "legacy"}},
    }

    out, _ = run_command("--s3")

    assert "'default'" not in out
    assert "'staticfiles'" not in out
    assert "'uploads'" not in out
    assert "S3 is available" in out
    assert sorted(head_bucket_calls(s3_client)) == ["legacy", "media"]


@requires_django_storages_setting
def test_wait_for_s3_requires_bucket_name(s3_client: MagicMock, settings: LazySettings):
    settings.STORAGES = {**storages_setting(), "media": {"BACKEND": S3_BACKEND}}

    with pytest.raises(CommandError, match="no bucket_name"):
        run_command("--s3")
    s3_client.head_bucket.assert_not_called()


@pytest.mark.skipif(django.VERSION >= (4, 2), reason="Django < 4.2 falls back to DEFAULT_FILE_STORAGE")
@patch("time.sleep", return_value=None)
def test_wait_for_s3_default_file_storage_fallback(mock_sleep: MagicMock, s3_client: MagicMock, settings: LazySettings):
    settings.DEFAULT_FILE_STORAGE = S3_BACKEND
    settings.AWS_STORAGE_BUCKET_NAME = "media"

    out, _ = run_command("--s3")

    assert "Waiting for S3 bucket 'media' (storage 'default')" in out
    assert head_bucket_calls(s3_client) == ["media"]


def test_wait_for_s3_requires_django_storages():
    missing = {"storages.backends.s3": None, "storages.backends.s3boto3": None}
    with patch.dict(sys.modules, missing), pytest.raises(ImportError, match=r"django-storages\[s3\]"):
        run_command("--s3")
