import signal
from typing import Any
from urllib.parse import urljoin

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandParser
from django.db import connections
from django.db.utils import OperationalError
from typing_extensions import override

from banjo_utils.utils.retry import RetryHelper


class TimeoutException(Exception): ...


def timeout_handler(*_: Any) -> None:
    raise TimeoutException("The command timed out.")


class Command(BaseCommand):
    help = "Wait for resources our application depends on"

    def wait_for_db(self) -> None:
        self.stdout.write("Waiting for DB...")
        retry_helper = RetryHelper()
        while True:
            try:
                db_conn = connections["default"]
                db_conn.ensure_connection()
                break
            except OperationalError:
                ...
            self.stdout.write(self.style.WARNING(retry_helper.try_again_message("DB not available")))
            retry_helper.wait()
        self.stdout.write(self.style.SUCCESS(f"DB is available after {retry_helper.total_time()} seconds"))

    def wait_for_cache(self) -> None:
        # ``--cache`` exercises Django's cache abstraction, not redis directly.
        # ``redis`` (redis-py) is not a banjo-utils runtime dependency; a
        # redis-backed project supplies it (typically via django-redis). Import
        # it lazily so ``--db``/``--celery-broker``/``--minio`` never require it,
        # and re-raise with a friendly message if the ``--cache`` path is used
        # without it.
        try:
            from redis.exceptions import ConnectionError as RedisConnectionError  # noqa: PLC0415
        except ImportError as e:
            raise ImportError(
                "wait_for_resources --cache requires the 'redis' package, which is "
                "not a banjo-utils runtime dependency. Install a redis client in your "
                "project (e.g. django-redis, which brings redis in).",
            ) from e

        self.stdout.write("Waiting for Cache...")
        retry_helper = RetryHelper()
        while True:
            try:
                cache.set("wait-for-it-ping", "pong", timeout=1)
                cache_value = cache.get("wait-for-it-ping")
                if cache_value != "pong":
                    raise TypeError
                break
            except (RedisConnectionError, TypeError):
                ...
            self.stdout.write(self.style.WARNING(retry_helper.try_again_message("Cache not available")))
            retry_helper.wait()
        self.stdout.write(self.style.SUCCESS(f"Cache is available after {retry_helper.total_time()} seconds"))

    def wait_for_celery_broker(self) -> None:
        # ``kombu`` (installed with celery) is not a banjo-utils runtime
        # dependency; a celery-backed project supplies it. Import it lazily so
        # ``--db``/``--cache``/``--minio`` never require it, and re-raise with a
        # friendly message if the ``--celery-broker`` path is used without it.
        try:
            from kombu import Connection  # noqa: PLC0415
            from kombu.exceptions import OperationalError as KombuOperationalError  # noqa: PLC0415
        except ImportError as e:
            raise ImportError(
                "wait_for_resources --celery-broker requires 'kombu' (installed with "
                "celery), which is not a banjo-utils runtime dependency. Install celery "
                "in your project.",
            ) from e

        broker_url = getattr(settings, "CELERY_BROKER_URL", None)
        if not broker_url:
            self.stdout.write(self.style.WARNING("No CELERY_BROKER_URL provided. Skipping wait"))
            return

        self.stdout.write("Waiting for Celery broker...")
        retry_helper = RetryHelper()
        while True:
            try:
                with Connection(broker_url, connect_timeout=5) as conn:
                    conn.ensure_connection(max_retries=1)
                break
            except KombuOperationalError:
                ...
            self.stdout.write(self.style.WARNING(retry_helper.try_again_message("Celery broker not available")))
            retry_helper.wait()
        self.stdout.write(self.style.SUCCESS(f"Celery broker is available after {retry_helper.total_time()} seconds"))

    def wait_for_minio(self) -> None:
        self.stdout.write("Waiting for Minio...")
        endpoint_url = getattr(settings, "AWS_S3_PROXIES", {}).get("http") or getattr(
            settings,
            "AWS_S3_ENDPOINT_URL",
            None,
        )
        if endpoint_url is None:
            self.stdout.write(self.style.WARNING("No endpoint_url is provided. Skipping wait"))
            return
        retry_helper = RetryHelper()
        while True:
            try:
                response = httpx.get(urljoin(endpoint_url, "/minio/health/live"), timeout=5)
                if response.status_code == 200:
                    break
            except httpx.RequestError:
                ...
            self.stdout.write(self.style.WARNING(retry_helper.try_again_message("Minio not available")))
            retry_helper.wait()
        self.stdout.write(self.style.SUCCESS(f"Minio is available after {retry_helper.total_time()} seconds"))

    @override
    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--timeout",
            type=int,
            default=600,
            help="The maximum time (in seconds) the command is allowed to run before timing out. Default is 10 min.",
        )
        parser.add_argument("--db", action="store_true", help="Wait for DB to be available")
        parser.add_argument("--cache", action="store_true", help="Wait for the Django cache backend to be available")
        parser.add_argument("--minio", action="store_true", help="Wait for MinIO (S3) storage to be available")
        parser.add_argument(
            "--celery-broker",
            action="store_true",
            help="Wait for the Celery broker (CELERY_BROKER_URL) to be available",
        )

    @override
    def handle(self, *_: Any, **kwargs: Any) -> None:
        timeout = kwargs["timeout"]
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)
        try:
            if kwargs.get("db"):
                self.wait_for_db()
            if kwargs.get("minio"):
                self.wait_for_minio()
            if kwargs.get("cache"):
                self.wait_for_cache()
            if kwargs.get("celery_broker"):
                self.wait_for_celery_broker()
        except TimeoutException:
            self.stderr.write(self.style.ERROR("Timed out while waiting for resources."))
        finally:
            signal.alarm(0)
