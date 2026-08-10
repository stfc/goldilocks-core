# Transports

The optional transports expose the same `recommend`, `generate`, and `compute` operations as Python and the CLI. They deserialize requests with `goldilocks_core.server.request.from_dict()` and dispatch through `run_core_job()`.

Two classes of transport differ in how they locate structure files and pseudopotentials:

- **Python, CLI, and MCP** accept server-local paths. Callers may supply `structure` as a path and pseudopotentials via `pseudo_root` or `output_dir`.
- **HTTP** is browser-safe and never accepts server paths. It takes inline structure content, identifies pseudopotentials by filename/library, and never exposes `output_dir` or `pseudo_root`. Any path-shaped field is rejected as `invalid_request`.

Both share the same validated `CoreJobRequest` construction from the parser.

## MCP

### Install and serve

Install the optional MCP dependency:

```bash
uv sync --extra mcp
```

Run the stdio server:

```bash
uv run goldilocks-core serve mcp
```

Applications can call `goldilocks_core.server.mcp.create_server()` to obtain the configured `MCPServer`.

### Shared tool fields

All three tools accept:

- `structure: string | {content: string, format?: "cif" | "poscar"}`;
- `intent?: {code, task, functional, pseudo_mode}`;
- `hints?: {k_spacing, k_grid, smearing_type, smearing_width_ry, spin_polarized, spin_orbit_coupling, pseudo_mode, pseudo_type, relativistic_mode, conv_thr, mixing_beta, electron_maxstep, use_vdw, vdw_method}`;
- `pseudo_metadata?: PseudoMetadata[]`;
- `pseudo_root?: string`;
- `kmesh_model?: ModelSpec`.

The generated MCP schemas forbid unknown object fields. Hint values use typed booleans, numbers, strings, and a three-integer k-grid. `smearing_type` is `fixed`, `gaussian`, `mp`, or `cold`; `vdw_method` is `d3`, `d3bj`, `ts`, or `mbd`. `structure` may be a server-local path string or inline content.

### recommend tool

```text
recommend(structure, intent?, hints?, pseudo_metadata?, pseudo_root?, kmesh_model?)
```

Runs the recommendation preset and returns `CoreResult` JSON.

### generate tool

```text
generate(structure, intent?, hints?, pseudo_metadata?, pseudo_root?, output_dir?, kmesh_model?)
```

Runs the generation preset and returns `CoreResult` JSON. `output_dir` optionally publishes the generated files on the server filesystem.

### compute tool

```text
compute(structure, outputs, intent?, hints?, pseudo_metadata?, pseudo_root?, kmesh_model?)
```

`outputs` is a required list whose items are one of the supported record names. The tool returns `CoreRecords` JSON containing only those records.

MCP schema or tool failures are reported through the MCP protocol by the server implementation.

## HTTP

### Install and serve

Install the optional HTTP dependencies:

```bash
uv sync --extra http
```

Run FastAPI with the built-in command:

```bash
uv run goldilocks-core serve http --host 127.0.0.1 --port 8000
```

The defaults are `127.0.0.1:8000`. Applications can call `goldilocks_core.server.http.create_app(runtime=..., config=...)` and serve the returned FastAPI application themselves. `goldilocks_core.server.main.app` is a module-level application for process servers (uvicorn, the container).

### Browser-safe request shape

The HTTP surface accepts only inline structure content and never server paths. A request body looks like:

```json
{
  "structure": {
    "content": "data_CIF_or_POSCAR",
    "format": "cif"
  },
  "intent": {
    "code": "quantum_espresso",
    "task": "scf_single_point",
    "functional": "PBEsol",
    "pseudo_mode": "efficiency"
  },
  "hints": {
    "k_grid": [4, 4, 4],
    "spin_polarized": false
  }
}
```

`structure` must be an object of inline content; a plain path string is rejected. `pseudo_root`, `output_dir`, and `pseudo_metadata.filepath` are rejected as server-path misuse. Pseudopotentials are identified by filename and library via `pseudo_metadata` (or injected by the operator's deployment config), never by a filesystem path. `intent` and `hints` use the fields of `CalculationIntent` and `CalculationHints`. `kmesh_model` uses the `ModelSpec` fields `name`, `version`, `model_type`, `target`, `feature_set`, `source`, `location`, and optional `revision`.

### GET /health

```bash
curl http://127.0.0.1:8000/health
```

Returns `{"status": "ok"}`. It reports process liveness, not model availability.

### GET /tasks

```bash
curl http://127.0.0.1:8000/tasks
```

Returns a catalogue of backend-owned Task Graph Descriptions (stages, presets, and selectable record ids) with stable identifiers. This drives the Workbench's Graph view.

### POST /structure/load

```bash
curl -X POST http://127.0.0.1:8000/structure/load \
    -H 'content-type: application/json' \
    -d '{"content": "data_CIF", "format": "cif"}'
```

Validates and normalises inline structure content and returns a canonical Structure Document (lattice vectors and parameters, sites with species and occupancies, and source metadata).

### POST /recommend

Runs the `recommend` preset. `mode` may be omitted or set to `"recommend"`; `outputs` is not accepted.

```bash
curl -X POST http://127.0.0.1:8000/recommend \
    -H 'content-type: application/json' \
    -d '{"structure": {"content": "data_CIF", "format": "cif"}, "hints": {"k_grid": [4, 4, 4]}}'
```

The response is `CoreResult.to_dict()` with analysis, advice, k-points, selection, warnings, and empty generated files.

### POST /generate

Runs the `generate` preset. `mode` may be omitted or set to `"generate"`; `outputs` and `output_dir` are not accepted.

```bash
curl -X POST http://127.0.0.1:8000/generate \
    -H 'content-type: application/json' \
    -d '{"structure": {"content": "data_CIF", "format": "cif"}, "hints": {"k_grid": [4, 4, 4]}}'
```

The response is `CoreResult.to_dict()` with `generated_files` containing the in-memory generated input contents. The Workbench assembles its input archive from these contents in the browser; the HTTP surface never writes to server paths.

### POST /compute

Runs a record query. `outputs` is required and must contain at least one supported record id.

```bash
curl -X POST http://127.0.0.1:8000/compute \
    -H 'content-type: application/json' \
    -d '{"structure": {"content": "data_CIF", "format": "cif"}, "hints": {"k_grid": [4, 4, 4]}, "outputs": ["analysis", "k_points"]}'
```

The response is `RecordSetResponse`: an object containing only the requested record ids.

Supported record ids are:

- `analysis`
- `advice`
- `k_points`
- `selection`
- `generated_files`

### HTTP errors

Expected transport and stage errors return stable structured responses with a typed envelope:

```json
{
  "error": {
    "kind": "invalid_request",
    "message": "POST /compute requires 'outputs'.",
    "status": 422,
    "details": null
  }
}
```

Failure kinds and their HTTP statuses:

- `invalid_request` (422): malformed request, unknown field, invalid endpoint combination, or a server-path field on the browser-safe surface;
- `stage_error` (400): a `ValueError` raised while executing a stage;
- `not_found` (404): a requested file was not found;
- `server_busy` (503): computation capacity is saturated after the configured wait; the response is retryable and carries a `Retry-After` header;
- `unexpected` (500): any unhandled failure. The full server-side traceback is logged and the browser receives a stable envelope — the error is never silently replaced.

The Workbench preserves the failure kind, message, status, structured details, and raw response through its `CoreClient` seam.

### Workbench serving

When a configured build directory exists (`GOLDILOCKS_WEB_DIST`, default `web/dist`), the app also serves the built Workbench under the same origin. The static mount is registered after every API route so the SPA fallback never shadows `/health` or `/tasks`. Development uses a Vite proxy to the local FastAPI app; no CORS is configured. `server/config.py` documents the operator-controlled deployment values.

## Runtime reuse and ownership

Each HTTP application and MCP server uses one `CoreRuntime` for its process lifetime. This retains lazily loaded k-mesh and metallicity model state across calls.

`create_app(runtime=...)` and `create_server(runtime=...)` accept a caller-owned runtime. A transport closes only a runtime it created. Supplying a runtime lets an embedding application coordinate its lifecycle explicitly.
