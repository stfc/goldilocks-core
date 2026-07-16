# HTTP server transport

`goldilocks-core` can run as a synchronous, stateless HTTP server over the fixed Core pipeline. It is a **transport only**: it maps a JSON request body to a `CoreJobRequest`, runs it through one long-lived `CoreRuntime`, and returns `CoreResult` JSON.

This is not an application server. There is no auth, sessions, multi-tenant isolation, job queue, persistence, file uploads beyond inline structure text, WebSockets, pod/container management, or frontend. Those belong in `goldilocks`/`goldilocks-api`.

## Install

The HTTP dependencies are optional so the core library stays light:

```bash
uv sync --extra http          # development
pip install goldilocks-core[http]  # or with pip
```

`import goldilocks_core` does not import or require the HTTP dependencies. The server module is only loaded when you import `goldilocks_core.server.http` or run `goldilocks-core serve`.

## Run

```bash
goldilocks-core serve [--host 127.0.0.1] [--port 8000] \
  [--pseudo-root DIR] [--structure-root DIR] [--bundle-root DIR] \
  [--model PATH | --heuristic-kpoints] [--model-name NAME] [--model-version VER]
```

The default host is loopback (`127.0.0.1`). Binding to `0.0.0.0` is an explicit operator choice. There is no CORS or TLS; terminate those at a reverse proxy in the application layer.

Backend composition mirrors the CLI: the default QRF k-point model, `--heuristic-kpoints` for advice-based resolution, or `--model` for a local CSLR model. Composition is process configuration. Callables are never serialized into request JSON and no model pipeline is built per request.

If the `[http]` extra is not installed, `serve` raises a clear install hint before binding.

## Endpoints

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/health` | — | `{"status": "ok"}` (liveness; does not load models or run a job) |
| `POST` | `/recommend` | request body | `CoreResult` JSON (stages end at `select`) |
| `POST` | `/generate` | request body | `CoreResult` JSON with `generated_files` |
| `POST` | `/bundle` | request body (requires `output_dir`) | `CoreResult` JSON with `bundle` |

The path encodes the mode, mirroring `goldilocks-core recommend|generate|bundle`. There is no `mode` field in the body and no union `/jobs` endpoint.

### Request body

```json
{
  "structure": {"content": "<inline CIF or POSCAR text>", "format": "cif"},
  "intent":   {"code": "quantum_espresso", "task": "scf_single_point", "functional": "PBE", "pseudo_mode": "efficiency"},
  "hints":    {"k_grid": [4, 4, 4], "use_vdw": true, "vdw_method": "d3bj"},
  "pseudo_metadata": [{"filepath": "/p/Si.UPF", "filename": "Si.UPF", "header_format": "attr", "element": "Si", ...}],
  "output_dir": "run-001"
}
```

- `structure` (required): inline text or a server-side path.
  - `{"content": "<text>", "format": "cif" | "poscar"}` parses inline text. When `format` is null, the server tries CIF then POSCAR. The structure object is strict: unknown keys are rejected, exactly one of `content` or `path` is required (not both), and `format` is rejected alongside `path`.
  - `{"path": "<relative-path>"}` reads a file under the configured `--structure-root`. Absolute paths, `..` traversal, and embedded NUL/control/format/surrogate characters are rejected. The path is confined to the root with a descriptor walk that rejects symlink components, so a symlink inside the root cannot read a file outside it. Intermediate components are opened with `O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK` (the kernel refuses a non-directory — FIFO/device/socket/regular file — with `ENOTDIR` before its driver `open` runs) and the final component is opened non-blocking and required to be a regular file, so a FIFO, device, or socket planted under the root is rejected with 422 rather than blocking the worker. Missing files map to `404`.
- `intent` (optional): `CalculationIntent.from_dict` payload. Defaults to Quantum ESPRESSO SCF, PBE, efficiency.
- `hints` (optional): `CalculationHints.from_dict` payload. Unknown keys and malformed value types are rejected.
- `pseudo_metadata` (optional): list of `PseudoMetadata.from_dict` payloads. When absent, the server uses pseudopotential metadata loaded once at startup from `--pseudo-root`. Per-request metadata overrides the configured default.
- `output_dir` (required for `/bundle`): relative path resolved against `--bundle-root` (default `goldilocks_output`). Absolute paths and `..` traversal are rejected; symlink components in the path are rejected so a bundle can never be published outside the configured root.

The body never carries executable backend choice. `mode` is set by the endpoint, not the body, and is rejected if present. Unknown top-level fields and `output_dir` on non-bundle endpoints are rejected as `invalid_request` so typos and wrong-endpoint fields cannot silently change behavior.

### Response

The response is strict `CoreResult` JSON from `CoreResult.to_dict()`: `intent`, `analysis`, `advice`, `selection`, `generated_files`, `warnings`, `bundle`, and `stages`. Provenance and warnings are always preserved on success. The request is not echoed.

For `/bundle`, `bundle.path` is the server-relative `output_dir` the client supplied (e.g. `run-001`), never the absolute host path the server wrote to.

### Error schema

All error responses use a deterministic schema and do not leak internals:

```json
{"error": {"kind": "<kind>", "message": "<human-readable detail>"}}
```

| Condition | Status | `kind` |
| --- | --- | --- |
| Malformed JSON, non-standard constants (`NaN`/`Infinity`/`-Infinity`), overflow to a non-finite number, duplicate object keys, malformed UTF-8, unpaired surrogate code points anywhere in the body, missing/unknown fields, bad structure content, unknown structure keys, both/neither `content` and `path`, `format` with `path`, unsupported `code`/`task`, path traversal, embedded NUL/control/format/surrogate characters, symlink component, special file (FIFO/device/socket) in a confined path, missing `output_dir`, `mode` or `output_dir` on the wrong endpoint | 422 | `invalid_request` |
| Missing server-side structure file path | 404 | `not_found` |
| Unknown route | 404 | `not_found` |
| Disallowed method | 405 | `method_not_allowed` |
| `ValueError` from a pipeline stage (e.g. incomplete pseudo selection); an existing bundle destination (reported with the server-relative `output_dir`, never the absolute host path) | 400 | `stage_error` |
| Internal model/registry/filesystem failures (including `EACCES`/`EMFILE`/`EIO` on a confined path), or any unexpected error | 500 | `internal_error` (message redacted, no host paths) |

## Runtime lifetime

The server owns one `CoreRuntime` for the process lifetime. It is created at application startup (FastAPI lifespan), reused across requests, and closed on shutdown, including when startup initialization (e.g. pseudo loading) fails. Models load lazily on first use and are shared by every request. `/health` does not load models or run a job.

Request execution is offloaded from the ASGI event loop to a thread pool: structure parsing, model inference, generation, and bundle I/O are blocking, so the parse + `runtime.run` runs off the loop while the single thread-safe runtime is shared across concurrent requests. A caller-provided runtime is not closed by the server; only the app-owned runtime (built by `create_app` from backend composition, or by `serve`) is closed at shutdown.

## Configuration

| Option / env | Purpose |
| --- | --- |
| `--host` / `--port` | Bind address. Loopback by default. |
| `--pseudo-root` | Directory of UPF files loaded once at startup as default pseudo metadata. |
| `--structure-root` | Allowlist root for server-side structure paths. When unset, only inline content is accepted. |
| `--bundle-root` | Root for bundle output directories. Defaults to `goldilocks_output`. |
| `GOLDILOCKS_MODEL_REGISTRY`, `GOLDILOCKS_METALLICITY_CHECKPOINT`, `GOLDILOCKS_METALLICITY_ATOM_INIT` | Model registry and artifact override paths captured by `CoreRuntime`. |
| `--model` / `--heuristic-kpoints` | Kmesh backend composition (mutually exclusive). |

## Example

```bash
curl -s http://127.0.0.1:8000/recommend \
  -H 'content-type: application/json' \
  -d '{"structure": {"content": "<CIF text>", "format": "cif"}, "hints": {"k_grid": [4, 4, 4]}}' \
  | python -m json.tool
```

## Security and non-goals

Non-goals (stated in the module docstring): auth, sessions, multi-tenant isolation, job queues, persistence, multipart uploads, WebSockets, pod/container management, and any frontend. These are application-layer concerns for sibling repos.

Server-side path inputs are allowlisted to configured roots, which are canonicalized at startup. Absolute and `..` traversal escapes are rejected for both `structure.path` and `output_dir`, and embedded NUL/control/format/surrogate characters (Unicode general categories `Cc`/`Cf`/`Cs`, including C1 controls such as `U+0085` and lone surrogates) are rejected before any OS call so they surface as a deterministic 422 rather than a stage error or a `UnicodeEncodeError` from `os.open`. Paths are confined to the root with a descriptor walk that rejects symlink components (the kernel returns `ELOOP` on `open(O_NOFOLLOW)`); intermediate components are opened with `O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK`, so the kernel refuses a non-directory (FIFO/device/socket/regular file) with `ENOTDIR` before its driver `open` runs, and the final component is opened non-blocking and required to be a regular file, so a FIFO, device, or socket planted under a root cannot block a worker and is rejected with 422. Genuine client path conditions (`ENOENT`/`ELOOP`/`ENOTDIR`/`ENXIO`) map to deterministic 4xx with the client-relative path; server-side filesystem failures (`EACCES`/`EMFILE`/`EIO` and similar) map to a redacted 500 without host paths.

This confinement holds against a client that can only supply request JSON, but it is **not a complete race-free publication primitive** against an actor that can mutate the operator-controlled root between validation and use. The bundle stage's atomic `renameat2(RENAME_NOREPLACE)` publication refuses any final destination that appears between the descriptor check and publication, so a client cannot publish outside the root; however, a separately-privileged actor that reorganizes the operator-controlled root between the descriptor walk and the atomic rename can still interpose a parent component. That is outside the stated no-multi-tenant / operator-root threat model (the operator is trusted not to race the server), and hardening against it would require holding parent descriptors across publication or a dedicated publish root. The default bind is loopback; exposing the server is an explicit operator choice with no built-in CORS or TLS.