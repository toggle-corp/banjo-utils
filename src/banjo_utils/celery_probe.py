"""Pod-local liveness probe reader for celery worker & beat heartbeats.

This module is intentionally **stdlib-only** -- it must NOT import ``celery``
or ``django``. It is ``exec``'d by the kubelet as a liveness probe inside the
same container as the heartbeat *writer* (the worker bootstep or the beat
scheduler mixin), so it has to start fast and work even in stripped images
where celery may not be importable in the probe's environment.

Design mirrors ``banjo_utils.health``: pod-local, cheap, dependency-free, and
it only answers "is this process wedged?". A worker/beat process touches a
heartbeat file on a fixed interval; this reader ``stat()``s that file and
fails (exit 1) when the file is missing or its mtime is older than
``--max-age``. It deliberately performs **no** broker round-trip (the reason
``celery inspect ping`` was rejected: false-positive restarts under load and
broker CPU cost -- see https://github.com/celery/celery/issues/4079).

Usage (as installed console script)::

    banjo-celery-probe [--heartbeat-file PATH] [--max-age SECONDS]

Path resolution order: ``--heartbeat-file`` CLI arg, then the
``BANJO_CELERY_HEARTBEAT_FILE`` env var (inherited from the writer's
container), then the code default.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Name of the env var both writer and reader agree on. The reader inherits it
# from the container the writer runs in, so a chart can set it once and the
# mount path / writer / reader never drift.
HEARTBEAT_FILE_ENV = "BANJO_CELERY_HEARTBEAT_FILE"

# Code default used only when neither the CLI arg nor the env var is set. The
# worker writer uses this same path by default; beat writes a different file,
# so beat probes must pass --heartbeat-file or set BANJO_CELERY_HEARTBEAT_FILE.
DEFAULT_HEARTBEAT_FILE = "/tmp/celery_worker_heartbeat"  # noqa: S108

# Staleness budget in seconds. 120s == 4x the worker's 30s write interval, so
# up to 3 missed touches are tolerated before the probe flags the process.
# The real wedge budget is k8s ``failureThreshold * periodSeconds`` (set in the
# chart); this is just the per-probe staleness check.
DEFAULT_MAX_AGE = 120


def is_fresh(path: str, max_age: float, now: float | None = None) -> bool:
    """Return ``True`` if ``path`` exists and was touched within ``max_age`` seconds.

    Returns ``False`` if the file is missing (writer never started / crashed)
    or stale (writer wedged).
    """
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        return False
    if now is None:
        now = time.time()
    return (now - mtime) <= max_age


def resolve_heartbeat_file(cli_value: str | None) -> str:
    """Resolve the heartbeat path: CLI arg, then env var, then code default."""
    if cli_value:
        return cli_value
    return os.environ.get(HEARTBEAT_FILE_ENV) or DEFAULT_HEARTBEAT_FILE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="banjo-celery-probe",
        description="Liveness probe for a celery worker/beat heartbeat file.",
    )
    parser.add_argument(
        "--heartbeat-file",
        default=None,
        help=(f"Path to the heartbeat file. Defaults to the {HEARTBEAT_FILE_ENV} env var, then {DEFAULT_HEARTBEAT_FILE}."),
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=DEFAULT_MAX_AGE,
        help=f"Maximum heartbeat age in seconds before failing. Default {DEFAULT_MAX_AGE}.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 when the heartbeat is fresh, 1 otherwise."""
    args = _build_parser().parse_args(argv)
    path = resolve_heartbeat_file(args.heartbeat_file)
    return 0 if is_fresh(path, args.max_age) else 1


if __name__ == "__main__":
    sys.exit(main())
