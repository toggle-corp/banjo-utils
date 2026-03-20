import signal
from urllib.parse import urljoin

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError
from redis.exceptions import ConnectionError as RedisConnectionError

from toggle_django_utils.utils.retry import RetryHelper


class TimeoutException(Exception): ...


def timeout_handler(*_):
    raise TimeoutException("The command timed out.")


class Command(BaseCommand):
    help = "Wait for resources our application depends on"

    def wait_for_db(self):
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

    def wait_for_redis(self):
        self.stdout.write("Waiting for Redis...")
        retry_helper = RetryHelper()
        while True:
            try:
                cache.set("wait-for-it-ping", "pong", timeout=1)
                redis_conn = cache.get("wait-for-it-ping")
                if redis_conn != "pong":
                    raise TypeError
                break
            except (RedisConnectionError, TypeError):
                ...
            self.stdout.write(self.style.WARNING(retry_helper.try_again_message("Redis not available")))
            retry_helper.wait()
        self.stdout.write(self.style.SUCCESS(f"Redis is available after {retry_helper.total_time()} seconds"))

    def wait_for_minio(self):
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

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=600,
            help="The maximum time (in seconds) the command is allowed to run before timing out. Default is 10 min.",
        )
        parser.add_argument("--db", action="store_true", help="Wait for DB to be available")
        parser.add_argument("--redis", action="store_true", help="Wait for Redis to be available")
        parser.add_argument("--minio", action="store_true", help="Wait for MinIO (S3) storage to be available")

    def handle(self, **kwargs):
        timeout = kwargs["timeout"]

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)

        try:
            if kwargs.get("db"):
                self.wait_for_db()
            if kwargs.get("minio"):
                self.wait_for_minio()
            if kwargs.get("redis"):
                self.wait_for_redis()
        except TimeoutException:
            self.stderr.write(self.style.ERROR("Timed out while waiting for resources."))
        finally:
            signal.alarm(0)
