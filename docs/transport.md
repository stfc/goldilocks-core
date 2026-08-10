# HTTP and MCP transports

The optional transports expose the same `recommend`, `generate`, and `compute` operations as Python and the CLI. Both deserialize requests with `goldilocks_core.server.request.from_dict()` and dispatch through `run_core_job()`.

## Shared request shape

The common JSON-like request fields are:

```json
{
  "structure": "path/to/structure.cif",
  "intent": {
    "code": "quantum_espresso",
    "task": "scf_single_point",
    "functional": "PBEsol",
    "pseudo_mode": "efficiency"
  },
  "hints": {
    "k_grid": [4, 4, 4],
    "spin_polarized": false
  },
  "pseudo_root": "path/to/pseudopotentials",
  "kmesh_model": null
}
```

`structure` accepts:

- a server-local file path string;
- an inline CIF or POSCAR string;
- `{"content": "...", "format": "cif"}` or `{"content": "...", "format": "poscar"}`.

`intent` and `hints` use the fields of `CalculationIntent` and `CalculationHints`. Pseudopotentials can be supplied as a `pseudo_metadata` list or loaded from a server-local `pseudo_root`. `kmesh_model` uses the `ModelSpec` fields `name`, `version`, `model_type`, `target`, `feature_set`, `source`, `location`, and optional `revision`.

Unknown fields and invalid values are rejected. The shared parser constructs the same validated `CoreJobRequest` for both transports.

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

The defaults are `127.0.0.1:8000`. Applications can also call `goldilocks_core.server.http.create_app()` and serve the returned FastAPI application themselves.

### POST /recommend

Runs the `recommend` preset. The body uses the shared request shape. `mode` may be omitted or set to `"recommend"`; `outputs` is not accepted.

```bash
curl -X POST http://127.0.0.1:8000/recommend \
    -H 'content-type: application/json' \
    -d '{
      "structure": "structure.cif",
      "hints": {"k_grid": [4, 4, 4]}
    }'
```

The response is `CoreResult.to_dict()` with analysis, advice, k-points, selection, warnings, and empty generated files.

### POST /generate

Runs the `generate` preset. `mode` may be omitted or set to `"generate"`; `outputs` is not accepted. `output_dir` optionally publishes generated files on the server filesystem.

```bash
curl -X POST http://127.0.0.1:8000/generate \
    -H 'content-type: application/json' \
    -d '{
      "structure": "structure.cif",
      "hints": {"k_grid": [4, 4, 4]},
      "pseudo_root": "path/to/pseudopotentials",
      "output_dir": "run/"
    }'
```

The response is `CoreResult.to_dict()` with `generated_files` and, when requested, a `bundle` publication record.

### POST /compute

Runs a record query. `outputs` is required and must contain at least one supported record name. `output_dir` is not accepted.

```bash
curl -X POST http://127.0.0.1:8000/compute \
    -H 'content-type: application/json' \
    -d '{
      "structure": "structure.cif",
      "hints": {"k_grid": [4, 4, 4]},
      "outputs": ["StructureAnalysisRecord", "KPointSelection"]
    }'
```

The response is `CoreRecords.to_dict()`: an object containing only the requested type names.

Supported output names are:

- `StructureAnalysisRecord`
- `ParameterAdvice`
- `KPointSelection`
- `SelectionRecord`
- `GeneratedFiles`

### GET /health

```bash
curl http://127.0.0.1:8000/health
```

Returns `{"status": "ok"}`. It reports process liveness, not model availability.

### HTTP errors

Transport and stage errors use 4xx responses with a structured message:

```json
{
  "error": {
    "kind": "invalid_request",
    "message": "POST /compute requires 'outputs'."
  }
}
```

- `422 invalid_request`: malformed shared request, unknown field, invalid endpoint combination, or contract validation failure during deserialization;
- `400 stage_error`: a `ValueError` raised while executing a stage;
- `404 not_found`: a requested file was not found.

Other unhandled failures use FastAPI's normal server-error behavior.

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

The generated MCP schemas forbid unknown object fields. Hint values use typed booleans, numbers, strings, and a three-integer k-grid. `smearing_type` is `fixed`, `gaussian`, `mp`, or `cold`; `vdw_method` is `d3`, `d3bj`, `ts`, or `mbd`.

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

`outputs` is a required list whose items are one of the five supported record names. The tool returns `CoreRecords` JSON containing only those records.

MCP schema or tool failures are reported through the MCP protocol by the server implementation.

## Runtime reuse and ownership

Each HTTP application and MCP server uses one `CoreRuntime` for its process lifetime. This retains lazily loaded k-mesh and metallicity model state across calls.

`create_app(runtime=...)` and `create_server(runtime=...)` accept a caller-owned runtime. A transport closes only a runtime it created. Supplying a runtime lets an embedding application coordinate its lifecycle explicitly.
