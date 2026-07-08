---
status: accepted
date: 2026-06-16
deciders: [thenav56]
---

# 0001. Celery worker & beat liveness via a pod-local heartbeat file

## Context and Problem Statement

Celery worker and beat are long-running, **non-HTTP** processes, so the
existing `HealthProbeMiddleware` (which serves `/healthz/*` over HTTP) cannot
report their health to Kubernetes. We need a liveness signal that tells the
kubelet to restart a worker/beat pod when its process has *wedged* (deadlocked,
hung on a stuck task, or beat's scheduler loop stopped ticking) — without the
probe itself becoming a source of instability under load.

The forces: a liveness probe runs on every pod on a fixed interval (often
several pods × every ~10s), it must be cheap and self-contained, and a
false-positive failure restarts a healthy pod — which under load can cascade.

## Considered Options

- **A. `celery inspect ping`** — the documented worker health command; sends a
  control message over the broker and waits for a reply.
- **B. PID-file / process-existence check** — assert the celery process is
  still running.
- **C. Pod-local heartbeat file** — the process periodically touches a file;
  an exec probe checks the file's freshness.
- **D. Deep HTTP health endpoint** (e.g. `django-health-check`) — a service
  that actively checks broker/DB connectivity.

## Decision Outcome

Chosen: **Option C — a pod-local heartbeat file.**

- The **worker** runs a `StartStopStep` bootstep on its own `Timer` (in the
  parent `MainProcess`) that touches a heartbeat file every 30s. Under the
  prefork pool, tasks run in forked children and never stall the timer.
- **Beat** is customised via `--scheduler`; the scheduler touches its heartbeat
  file *after* each `tick()` returns, proving a tick completed.
- A stdlib-only reader (`banjo-celery-probe`) is run by the kubelet as an
  `exec` liveness probe: it `stat()`s the file and exits non-zero when the file
  is stale or missing. It imports neither celery nor django.

This mirrors the philosophy already established for the HTTP probes in
`src/banjo_utils/health.py`: **pod-local, cheap, dependency-free, and scoped to
"is this process wedged?"** — not "is the whole system healthy?".

## Consequences

- **Good:** no broker traffic per probe (no false-positive restarts under load,
  no broker CPU cost); detects a genuinely wedged process, not just a live PID;
  the reader is dependency-free and fast, so it works in stripped images and
  cannot itself hang on a network call.
- **Bad:** detection latency is ~2 min (reader's 120s default `--max-age` ≈ 4×
  the 30s write interval), not instant — acceptable for liveness.
- **Bad:** the probe deliberately does **not** verify broker/DB connectivity; a
  worker that is up but cannot reach the broker still looks "live". That is
  intentional (shared-dependency checks belong in monitoring, not liveness), but
  it is a real limitation to be aware of.
- **Bad:** the worker heartbeat assumes the **prefork** pool. Under
  `gevent`/`eventlet` the timer shares the event loop with tasks, so a blocking
  task can stall the heartbeat and cause a false restart.
- **Bad:** the beat reader's `--max-age` must exceed the scheduler's tick
  cadence — fine for `DatabaseScheduler` (~5s), but `PersistentScheduler`'s
  `max_interval` is 300s, so its probe needs `--max-age > 300`. This cadence is
  also **operator-overridable**: `celery beat --max-interval <seconds>` raises
  the scheduler's `max_interval` regardless of scheduler class, so beat sleeps
  (and skips touching the heartbeat) for up to that long between ticks. A value
  above the probe's `--max-age` silently causes false-positive restarts of a
  healthy beat — keep `--max-interval` below `--max-age`.
- **Cost:** the writer must be wired into project code (`setup_worker_heartbeat`
  / the `--scheduler` flag), and the heartbeat directory should be a small
  RAM-backed `emptyDir` to avoid disk wear — a manifest/Helm concern.
- **Revisit if:** projects move predominantly to a `gevent`/`eventlet` pool, or
  if we decide liveness *should* assert broker connectivity (which would
  reintroduce the Option A tradeoffs).

## Pros and Cons of the Options

### A. `celery inspect ping`

- Good: directly exercises the worker's ability to process a control message.
- Bad: every probe is a broker round-trip; under load workers are too busy to
  answer promptly, producing **false-positive restarts**, and the extra control
  traffic adds broker CPU cost. This is the documented failure mode in
  [celery/celery#4079](https://github.com/celery/celery/issues/4079) and the
  primary reason this option was rejected.
- Bad: the probe depends on celery being importable and the broker reachable —
  the opposite of a self-contained liveness check.

### B. PID-file / process-existence check

- Good: trivially cheap and dependency-free.
- Bad: a deadlocked or hung process keeps its PID, so this **cannot detect a
  wedge** — only a fully dead process. Insufficient for the actual requirement.
  (Per the discussion in celery/celery#4079: "PID is not a solution, can't
  catch deadlock.")

### C. Pod-local heartbeat file (chosen)

- Good: cheap, self-contained, no broker traffic; advances only while the
  process is actually doing work, so it catches wedges.
- Bad: ~2 min detection latency and the pool/cadence caveats noted above.

### D. Deep HTTP health endpoint

- Good: can report rich, system-wide health (broker, DB, storage).
- Bad: wrong tool for *liveness* — a shared-dependency outage would fail every
  pod at once. This is the deep-health/monitoring concern that `health.py`
  already documents as deliberately out of scope for probes. Complementary to,
  not a replacement for, this decision.
