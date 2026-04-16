import pytest
from django.conf import LazySettings, settings


def pytest_configure():
    settings.configure(
        DEBUG=True,
        SECRET_KEY="test",  # noqa: S106
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
            },
        },
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "banjo_utils",
        ],
        MIDDLEWARE=[
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
        ],
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        },
    )


@pytest.fixture(autouse=True)
def reset_settings(settings: LazySettings):
    caches = {**settings.CACHES}
    yield
    settings.CACHES = caches
