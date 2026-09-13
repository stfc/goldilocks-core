# Deployment

Run the HTTP transport for Workbench browsers or API clients. This page covers
worker processes, startup behavior, and memory.

## Starting the server

```bash
uv run --extra http goldilocks serve http --static-root web/dist
```

One uvicorn master accepts connections; each worker process runs a full
`Service`. The worker count is planned from the machine at startup:

- CPU: cores visible to the process (`sched_getaffinity`), capped by the cgroup
  CPU quota when one applies (`cpu.max` or `cpu.cfs_quota_us`).
- Memory budget: the cgroup memory limit when set (`memory.max`), otherwise
  available memory (`MemAvailable`, or `sysconf` where `/proc` is absent).
- Per-worker cost: measured once at startup by loading the real model stack —
  the QRF k-point model (`models/qrf-kpoints`) and the metallicity classifier
  (`models/metallicity-cgcnn`) — in a throwaway forked process.

The plan is `min(cpu count, 0.6 × memory budget / per-worker cost)`, at least
one worker. A single usable CPU always means one worker. A quantity that
cannot be measured (no cgroup files, no `fork` support) drops out and the plan
falls back to the CPU count.

Set `GOLDILOCKS_WEB_WORKERS` to pin the count; it wins over planning. In
Docker, `docker run --memory` limits feed the planning automatically, so a
memory-capped container plans fewer workers without configuration.

## Startup sequence

Each worker prewarms the models before accepting requests. The QRF model and
the metallicity classifier load once per worker and every compute request
reuses them; there is no per-request model load. Startup therefore takes about
one model load per worker.

The server boots without installed runtime assets: `/ready` reports what is
missing and compute fails per request until `goldilocks assets install
workbench` runs. Installed but corrupt assets fail startup instead.

## Memory

A warm worker holds the deserialized models for its lifetime. Plan for roughly
`workers × per-worker cost` plus a few hundred megabytes of interpreter,
framework, and featurizer baseline per worker. The container image bundles the
runtime assets and applies the same planning from its own cgroup limits.

## Handler concurrency

Each worker bounds its request thread pool by the measured CPU count (between
2 and 8 handlers). `/health` and Workbench static files run on the event loop
and stay responsive while compute and inspection handlers queue.