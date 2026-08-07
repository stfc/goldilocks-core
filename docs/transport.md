# Transports: HTTP and MCP

goldilocks-core exposes the same `CoreRuntime` entrypoints over two server
transports: an HTTP API (FastAPI + uvicorn) and an MCP server (stdio). Both are
**transports only** — no auth, sessions, queues, persistence, WebSockets, pod
management, or frontend live here. Both own one long-lived `CoreRuntime` for the
process lifetime and reuse its model state across requests/tool calls.

For the CLI and Python API see [cli.md](cli.md) and [tutorial.md](tutorial.md).

## Install the extras

HTTP and MCP dependencies live behind optional extras and are imported lazily,
so a plain `import goldilocks_core` never pulls them in.

```bash
uv sync --extra http       # FastAPI + uvicorn
uv sync --extra mcp        # the mcp SDK
uv sync --extra http --extra mcp
```

Without the extra, the relevant `serve` subcommand raises an `ImportError`
naming the missing extra.

## Start a server

### HTTP

CLI:

```bash
goldilocks-core serve http --host 127.0.0.1 --port 8000
```

`--host` defaults to loopback; `--port` defaults to 8000. The server owns one
`CoreRuntime`, created at startup and closed on shutdown.

Programmatic:

```python
from goldilocks_core.server.http import create_app, serve

# Build the FastAPI app (e.g. to mount under your own server):
app = create_app()

# Or run uvicorn directly:
serve(host="127.0.0.1", port=8000)
```

`create_app(runtime=None)` accepts a pre-built `CoreRuntime`; when omitted, the
app owns one for its lifetime. OpenAPI docs are disabled (`docs_url=None`,
`redoc_url=None`, `openapi_url=None`).

### MCP

CLI:

```bash
goldilocks-core serve mcp
```

Runs the MCP server over stdio. The server owns one `CoreRuntime`, created at
startup and closed on shutdown.

Programmatic:

```python
from goldilocks_core.server.mcp import create_server, serve

server = create_server()   # MCPServer with six tools registered
serve()                    # anyio.run(server.run_stdio_async)
```

`create_server(runtime=None)` accepts a pre-built `CoreRuntime`; when omitted,
the server owns one for its lifetime.

## Request shape

Both transports share one request parser, `from_dict` in
`server/request.py`. It is the **only** place a JSON mapping becomes a
`CoreJobRequest`. Unknown keys, bad types, and explicit `null` for required
sections are rejected with a `RequestError` naming the field — fields are never
silently dropped.

Top-level keys accepted by the body:

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `structure` | string \| object | yes | Path string, or inline `{content, format?}`. |
| `intent` | object | no | `CalculationIntent` fields (`code`, `task`, `functional`, `pseudo_mode`). |
| `hints` | object | no | `CalculationHints` fields. |
| `mode` | `"recommend"` \| `"generate"` | no | Selected by the endpoint/tool; defaults to `recommend`. |
| `pseudo_metadata` | list | no | Per-entry `PseudoMetadata` dicts. |
| `pseudo_root` | string | no | Directory of UPF files loaded server-side. |
| `output_dir` | string | no | Bundle directory; meaningful only with `generate`. |
| `kmesh_model` | object | no | `ModelSpec` for a local k-index model. |

Example `recommend` body:

```json
{
  "structure": "path/to/Si.cif",
  "hints": {"k_grid": [4, 4, 4], "spin_polarized": true}
}
```

Inline structure content:

```json
{
  "structure": {"content": "<CIF text>", "format": "cif"},
  "intent": {"functional": "PBE"}
}
```

## HTTP endpoints

All endpoints accept a JSON body (the request shape above) and return
`to_jsonable(result)` — a `CoreResult` for `recommend`/`generate`, or the stage
record for the raw endpoints.

| Method | Path | Runs | Returns |
| --- | --- | --- | --- |
| `GET` | `/health` | nothing | `{"status": "ok"}` (liveness; no model load) |
| `POST` | `/analyze` | Load → Analyze | `StructureAnalysisRecord` JSON |
| `POST` | `/kmesh` | Load → Kmesh | `KPointSelection` JSON |
| `POST` | `/advise` | Load → Analyze → Advise | `ParameterAdvice` JSON |
| `POST` | `/select` | Load → Analyze → Advise → Select | `SelectionRecord` JSON |
| `POST` | `/recommend` | Load → Analyze → Advise → Kmesh → Select | `CoreResult` JSON |
| `POST` | `/generate` | full path through Generate | `CoreResult` JSON (with `generated_files`; `bundle` when `output_dir` given) |

`curl` example:

```bash
curl -s localhost:8000/recommend \
    -H 'Content-Type: application/json' \
    -d '{"structure": "path/to/Si.cif"}' | jq
```

## MCP tools

The MCP server registers six tools. `recommend` and `generate` take the
pipeline argument schema; the raw stage tools (`analyze`, `kmesh`, `advise`,
`select`) take the stage argument schema (no `output_dir`). `mode` is selected
by the tool, not by the body. Argument schemas are strict Pydantic models
(`extra="forbid"`, so `additionalProperties: false`) mirroring the Core
contracts; validation is then routed through the shared `from_dict` parser.

| Tool | Runs | Returns |
| --- | --- | --- |
| `recommend` | Load → Analyze → Advise → Kmesh → Select | `CoreResult` JSON |
| `generate` | full path through Generate | `CoreResult` JSON |
| `analyze` | Load → Analyze | `StructureAnalysisRecord` JSON |
| `kmesh` | Load → Kmesh | `KPointSelection` JSON |
| `advise` | Load → Analyze → Advise | `ParameterAdvice` JSON |
| `select` | Load → Analyze → Advise → Select | `SelectionRecord` JSON |

Server instructions (sent to clients):

> Goldilocks Core DFT input recommendation pipeline. Tools return strict
> CoreResult or stage-record JSON. No auth, sessions, persistence, or
> execution of generated inputs.

## Error semantics

Errors return a JSON body of the form `{"error": {"kind": ..., "message": ...}}`.
The HTTP status is derived from the error kind.

| Kind | HTTP status | When |
| --- | --- | --- |
| `invalid_request` | 422 | Malformed body, unknown keys, bad types, failed `from_dict` validation. |
| `not_found` | 404 | `FileNotFoundError` (e.g. missing structure path). |
| `method_not_allowed` | 405 | Wrong HTTP method on a known path. |
| `stage_error` | 400 | A stage raised `ValueError` (e.g. unsupported code/task, disordered structure). |
| `stage_error` | 422 | `DimensionalityClassificationError` or `SymmetryAnalysisError`. |
| `http_error` | (passthrough) | Other `HTTPException` status codes. |
| `internal_error` | 500 | Anything else; the message is replaced with `"internal server error"`. |

`RequestError` (a `ValueError` subclass) carries a `kind` and `message`.
Stage `ValueError`s become `stage_error` with the original message preserved.
For MCP, errors surface through the MCP protocol's tool-error channel.

## Runtime ownership

Both servers follow the same ownership rule: when you do not pass a
`runtime=`, the server creates a `CoreRuntime` at startup and closes it on
shutdown. When you pass a pre-built `CoreRuntime`, the server reuses it and
does **not** close it — its lifetime is yours. There is no per-request or
per-call runtime; model state is loaded once and reused.