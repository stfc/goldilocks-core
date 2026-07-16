# MCP server transport

`goldilocks-core` can run as an MCP (Model Context Protocol) server exposing the fixed Core pipeline as tools for LLM agents. It is a **transport only**: it maps constrained tool arguments to a `CoreJobRequest` via the shared deserializer, runs it through one long-lived `CoreRuntime`, and returns strict `CoreResult` JSON.

This is not an application server. There is no auth, sessions, multi-tenant isolation, job queue, persistence, file uploads beyond inline structure text, arbitrary execution of generated inputs, downloads, containers, frontend, or job management. Those belong in `goldilocks`/`goldilocks-api`.

## Relationship to `goldilocks-mcp`

This Core-level MCP exposes the **full Core pipeline** (recommend / generate / bundle / analyze). It is deliberately distinct from the separate `goldilocks-mcp` repository, which exposes the ML k-point *models* only. Merging them would couple Core's release cadence to the model-exposing repo and pull model-only tools into a pipeline transport, violating the thin-transport-over-`run_core_job` boundary. They may share a host process at deploy time; they do not share a package.

## Install

The MCP dependencies are optional so the core library stays light:

```bash
uv sync --extra mcp            # development
pip install goldilocks-core[mcp]  # or with pip
```

`import goldilocks_core` does not import or require the MCP dependencies. The server module is only loaded when you import `goldilocks_core.server.mcp` or run `goldilocks-core mcp`.

## Run

```bash
goldilocks-core mcp \
  [--pseudo-root DIR] [--structure-root DIR] [--bundle-root DIR] \
  [--model PATH | --heuristic-kpoints] [--model-name NAME] [--model-version VER]
```

The server runs over **stdio only** in v1 — the agent-native path used by
LLM-agent hosts (Claude Desktop and similar). HTTP-style transports
(``sse`` / ``streamable-http``) are deliberately not exposed: the MCP Python
SDK only offers those through the FastMCP high-level wrapper, whose
raw-argument extension points are internal/unsupported, and this transport
refuses to depend on those internals. Operators needing network exposure should
terminate TLS and front stdio with a small adapter in the application layer.

Backend composition mirrors the CLI and the HTTP `serve` command: the default QRF k-point model, `--heuristic-kpoints` for advice-based resolution, or `--model` for a local CSLR model. Composition is process configuration, not tool-call data. Callables are never serialized into tool arguments and no `CoreRuntime` or `Pipeline` is built per call.

If the `[mcp]` extra is not installed, `mcp` raises a clear install hint before running.

## Tools

All tools return strict `CoreResult` JSON (or, for `analyze`, the `StructureAnalysisRecord` JSON). Provenance and warnings are always preserved on success.

| Tool | Input | Output | Pipeline |
| --- | --- | --- | --- |
| `recommend` | structure + intent + hints (+ optional pseudo) | `CoreResult` JSON (stages end at `select`) | Load → Analyze → Advise → Kmesh → Select |
| `generate` | same | `CoreResult` JSON with `generated_files` | … → Generate |
| `bundle` | same + `output_dir` (required) | `CoreResult` JSON with `bundle`; `bundle.path` is server-relative | … → Bundle |
| `analyze` | structure only | `StructureAnalysisRecord` JSON (facts) | Analyze only |

There is no `mode` argument: the tool selects the pipeline mode. There is no `advise`-only tool — advice without selection is half a recommendation; `recommend` is the right granularity. `analyze` is included as a thin fact-only tool for agents that want structure facts before committing to a full run. It runs only the Analyze stage (a stateless stage with no model resources) and does not consult the shared runtime.

### Tool input schemas

Tool inputs are **structured objects**, never a free JSON-string payload. Schemas are derived from the Core contract `Literal` aliases and field sets, so agents get constrained inputs:

- `intent.code`: `quantum_espresso` (from `CodeName`).
- `intent.task`: `scf_single_point` (from `CalcTask`).
- `hints.vdw_method`: `d3`, `d3bj`, `ts`, `mbd` (from `VdwMethod`).
- `hints.k_grid`: a 3-integer array (`prefixItems` / `minItems` 3 / `maxItems` 3).
- `structure.format`: `cif` or `poscar`.
- `pseudo_metadata` items mirror `PseudoMetadata.from_dict`; `filepath`, `filename`, and `header_format` are required.

`accuracy_level` is absent from every schema: it was removed from the contracts because no stage implemented distinct accuracy/cost semantics. `mode` is absent: the tool encodes it. Every schema root object and every named nested model (`StructureArg`, `IntentArg`, `HintsArg`, `PseudoMetadataArg`) carries `additionalProperties: false`, so the published contract is strict.

**Two nested fields are intentional free-form metadata-map exceptions**, not closed objects: `pseudo_metadata` items' `pseudo_info` and `sssp_recommended_cutoff` publish `type: object, additionalProperties: true`, because the Core `PseudoMetadata` contract models them as `dict[str, Any]` (raw UPF header metadata and raw SSSP cutoff maps whose keys are not part of the Core contract). Their free-form *contents* are accepted by contract design; everything else about `PseudoMetadata` is closed and type-checked at runtime (see below). These are the only open objects in the published schemas.

The published schema only *describes* the inputs; it does not validate them. Tool arguments are **not validated by the MCP SDK**. The server is built on the public low-level `mcp.server.Server`: tools are registered through the public `@server.list_tools` and `@server.call_tool(validate_input=False)` extension points, so the untouched client argument dict is forwarded straight to the tool. FastMCP's high-level wrapper would normally generate a lax, coercing root argument model with `extra="ignore"`, which would silently drop unknown root keys, coerce `"3"`/`3.0`/`true` into integers, and collapse an explicit `null` into an omitted section before the shared deserializer ran; using the low-level `Server` with `validate_input=False` avoids that without depending on any internal SDK class or hook. Every field is routed through the shared `parse_core_job_request` deserializer, the single source of truth for validation, which performs `isinstance`-based strict checks with no coercion:

- Unknown root keys (including `mode` and `output_dir` on the wrong tool) are rejected, not silently dropped.
- Booleans, strings, and floats are not coerced into ints/floats (`k_grid: "3"`, `3.0`, `true`; `k_spacing: "0.2"`; `spin_polarized: "true"` are all rejected).
- An explicit `null` for `intent`, `hints`, or `pseudo_metadata` is rejected as malformed, not treated as omitted. Omitting a section uses the contract default.

The MCP module defines no duplicate parser.

### Structure input

`structure` accepts either inline text or an allowlisted server-side path:

- `{"content": "<text>", "format": "cif" | "poscar"}` parses inline text. When `format` is null, the server tries CIF then POSCAR. The structure object is strict: unknown keys are rejected, exactly one of `content` or `path` is required (not both), and `format` is rejected alongside `path`.
- `{"path": "<relative-path>"}` reads a file under the configured `--structure-root`. Absolute paths, `..` traversal, and embedded NUL/control/format/surrogate characters are rejected. The path is confined to the root with a descriptor walk that rejects symlink components, so a symlink inside the root cannot read a file outside it. Missing files map to a `not_found` error.

### `output_dir` (bundle)

Required for `bundle`. Resolved against `--bundle-root` (default `goldilocks_output`). Absolute paths and `..` traversal are rejected; symlink components in the path are rejected so a bundle can never be published outside the configured root. The `bundle.path` in the response is the server-relative `output_dir` the caller supplied (e.g. `run-001`), never the absolute host path the server wrote to.

### Pseudo metadata

Two mutually-supported sources: a per-call `pseudo_metadata` list (overrides), or pseudopotential metadata loaded once at startup from `--pseudo-root` (the default). When the body supplies none, selection runs with empty metadata and returns `fallback` provenance and warnings — this is not an error.

## Error model

Expected validation/path/stage failures become stable MCP tool errors: `isError: true` results with a useful, safe message. Deeper validation (path confinement, contract coupled-field checks, stage failures) returns a JSON error body using the same kind vocabulary as the HTTP transport:

```json
{"error": {"kind": "<kind>", "message": "<human-readable detail>"}}
```

| Condition | `kind` |
| --- | --- |
| Unparseable structure content, path traversal, embedded NUL/control/format/surrogate characters, symlink component, special file in a confined path, `..`/absolute `output_dir`, contradictory or out-of-range contract values caught by `from_dict`, unknown root or nested keys, wrong-type values (no coercion), explicit `null` for an optional section | `invalid_request` |
| Missing server-side structure file path | `not_found` |
| An existing bundle destination (reported with the server-relative `output_dir`, never the absolute host path) | `stage_error` |
| A `ValueError` from a pipeline stage, internal model/registry/config failures (including `EACCES`/`EMFILE`/`EIO` on a confined path), `FileExistsError` outside the bundle boundary, or any unexpected error | `internal_error` (message redacted, no host or model/config paths) |

Because SDK pre-validation is disabled, **every** client input failure (request, path, stage, internal) is returned as the stable `isError: true` JSON body above, never as SDK-generated `Error executing tool ...` prose. A stage `ValueError` is redacted to `internal_error` so internal model/config paths never leak; only the client-relative bundle destination is echoed (as `stage_error`).

## Runtime lifetime

The server owns one `CoreRuntime` for the process lifetime. It is created during the MCP server lifespan startup, reused across tool calls, and closed on shutdown, including when startup initialization fails. Models load lazily on first use and are shared by every tool call. `analyze` does not consult the runtime (it runs the stateless Analyze stage directly).

Tool execution (parse + `runtime.run`) is offloaded from the server's event loop to a worker thread, mirroring the HTTP transport, so a blocking model inference or bundle I/O does not block the transport. The single thread-safe runtime is shared across concurrent calls. A caller-provided runtime (passed to `create_server`) is not closed by the server; only the server-owned runtime (built by `create_server` from backend composition, or by `serve`) is closed at shutdown.

## Configuration

| Option / env | Purpose |
| --- | --- |
| `--pseudo-root` | Directory of UPF files loaded once at startup as default pseudo metadata. |
| `--structure-root` | Allowlist root for server-side structure paths. When unset, only inline content is accepted. |
| `--bundle-root` | Root for bundle output directories. Defaults to `goldilocks_output`. |
| `GOLDILOCKS_MODEL_REGISTRY`, `GOLDILOCKS_METALLICITY_CHECKPOINT`, `GOLDILOCKS_METALLICITY_ATOM_INIT` | Model registry and artifact override paths captured by `CoreRuntime`. |
| `--model` / `--heuristic-kpoints` | Kmesh backend composition (mutually exclusive). |

v1 runs over stdio only; there are no `--transport`, `--host`, or `--port` options. Network exposure is an application-layer concern (front stdio with a TLS-terminating adapter).

## Python API

`goldilocks_core.server.mcp.create_server(...)` builds the low-level `mcp.server.Server` and `serve(...)` runs it over stdio. These require the `[mcp]` extra and raise a clear `ImportError` otherwise.

## Security and non-goals

Non-goals (stated in the module docstring): auth, sessions, multi-tenant isolation, job queues, persistence, multipart uploads, WebSockets, pod/container management, execution of generated inputs, downloads, and any frontend. These are application-layer concerns for sibling repos.

Server-side path inputs are allowlisted to configured roots, canonicalized at construction. Absolute and `..` traversal escapes are rejected for both `structure.path` and `output_dir`, and embedded NUL/control/format/surrogate characters (Unicode general categories `Cc`/`Cf`/`Cs`) are rejected before any OS call. Paths are confined to the root with the same descriptor walk used by the HTTP transport; see [HTTP server](http.md) for the full confinement details. The bundle stage's atomic `renameat2(RENAME_NOREPLACE)` publication refuses any final destination that appears between validation and use, so a caller cannot publish outside the configured root.

The stdio transport assumes a trusted local host (the agent launcher). Network exposure is explicitly out of scope for this transport in v1; terminate TLS/CORS at a reverse proxy or stdio-to-HTTP adapter in the application layer.