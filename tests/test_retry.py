from __future__ import annotations

import time
import typing

if typing.TYPE_CHECKING:
    from pytest_mock import MockerFixture

from banjo_utils.utils.retry import RetryHelper


def test_defaults():
    r = RetryHelper()
    assert r.base_wait_seconds == 2
    assert r.wait_max_seconds == 60
    assert r.attempt == 1
    assert r.next_wait == 2


def test_wait_increases_attempt_and_wait(mocker: MockerFixture):
    mock_sleep = mocker.patch("time.sleep")

    r = RetryHelper(base_wait_seconds=2, wait_max_seconds=100)

    r.wait()
    mock_sleep.assert_called_once_with(2)
    assert r.attempt == 2
    assert r.next_wait > 2


def test_wait_is_capped(mocker: MockerFixture):
    mocker.patch("time.sleep")

    r = RetryHelper(base_wait_seconds=2, wait_max_seconds=5)
    for _ in range(10):
        r.wait()

    assert r.next_wait == 5


def test_total_time_increases():
    r = RetryHelper()
    t0 = r.total_time()
    time.sleep(0.01)
    assert r.total_time() > t0


def test_try_again_message():
    r = RetryHelper(base_wait_seconds=2)
    msg = r.try_again_message("DB not available")

    assert "DB not available" in msg
    assert "Attempt: 1" in msg
    assert "2 seconds" in msg
