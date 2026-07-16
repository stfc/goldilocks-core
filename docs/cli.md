# CLI reference

The `goldilocks-core` command is a thin wrapper around `CoreJobRequest` and `CoreRuntime`. It parses arguments, owns one runtime for the one-shot process, runs the staged pipeline, closes the runtime, and prints JSON or a short human-readable summary.

## Commands

### recommend

```bash
goldilocks-core recommend structure.cif [options]
```

Runs Load → Analyze → Advise → Kmesh → Select. Outputs a recommendation without generated files.

### generate

```bash
goldilocks-core generate structure.cif [options]
```

Runs Load → Analyze → Advise → Kmesh → Select → Generate. Outputs a recommendation with generated input files.

### bundle

```bash
goldilocks-core bundle structure.cif --out run/ [options]
```

Runs the full pipeline and publishes a portable bundle directory. `--out` is required and must not already exist; bundle mode has no overwrite option.

### serve

```bash
goldilocks-core serve [--host 127.0.0.1] [--port 8000] [options]
```

Runs the HTTP server transport (requires the optional `[http]` extra; `uv sync --extra http`). Sync, stateless: one runtime for the process lifetime, reused across requests, closed on shutdown. No auth, sessions, queues, or persistence. See [HTTP server](server/http.md).

| Flag | Type | Default | Purpose |
| --- | --- | --- | --- |
| `--host` | str | `127.0.0.1` | Bind host. Loopback by default; use `0.0.0.0` to expose. |
| `--port` | int | `8000` | Bind port. |
| `--pseudo-root` | path | None | Directory of UPF files loaded once at startup as default pseudo metadata. |
| `--structure-root` | path | None | Allowlist root for server-side structure paths. |
| `--bundle-root` | path | `goldilocks_output` | Root for bundle output directories. |
| `--model` | path | None | Local ML Kmesh model path. Replaces the default QRF backend. |
| `--heuristic-kpoints` | flag | False | Use advice-based k-point resolution instead of the default QRF model. |
| `--model-name` | str | `server-kmesh-model` with `--model` | Model name recorded in Kmesh provenance; requires `--model`. |
| `--model-version` | str | `unknown` with `--model` | Model version recorded in metadata; requires `--model`. |

`--model` and `--heuristic-kpoints` are mutually exclusive. Backend composition is process configuration, not request data. If the `[http]` extra is missing, `serve` raises a clear install hint before binding.

## Common options

| Flag | Type | Default | Maps to |
| --- | --- | --- | --- |
| `structure` | positional | — | `CoreJobRequest.structure` |
| `--code` | choice | `quantum_espresso` | `CalculationIntent.code` |
| `--task` | choice | `scf_single_point` | `CalculationIntent.task` |
| `--functional` | str | `PBE` | `CalculationIntent.functional` (canonicalized; e.g. `PBESOL` → `PBEsol`) |
| `--pseudo-mode` | str | `efficiency` | `CalculationIntent.pseudo_mode` |
| `--pseudo-type` | str | None | `CalculationHints.pseudo_type` |
| `--relativistic-mode` | str | None | `CalculationHints.relativistic_mode` |
| `--pseudo-root` | path | None | Loads UPF files recursively into `pseudo_metadata` |
| `--model` | path | None | Replaces the default with a local ML Kmesh backend |
| `--heuristic-kpoints` | flag | False | Disables ML and resolves k-points from advice |
| `--model-name` | str | `cli-kmesh-model` with `--model` | Model name recorded in Kmesh provenance; requires `--model` |
| `--model-version` | str | `unknown` with `--model` | Model version recorded in `ModelSpec`; requires `--model` |
| `--k-spacing` | float | None | `CalculationHints.k_spacing` |
| `--k-grid` | 3 ints | None | `CalculationHints.k_grid` |
| `--smearing-type` | `fixed`, `gaussian`, `mp`, or `cold` | None | `CalculationHints.smearing_type` |
| `--smearing-width-ry` | float | None | `CalculationHints.smearing_width_ry` |
| `--spin-polarized` | `true`/`false` | None | `CalculationHints.spin_polarized` |
| `--spin-orbit-coupling` | `true`/`false` | None | `CalculationHints.spin_orbit_coupling` |
| `--use-vdw` | `true`/`false` | None | `CalculationHints.use_vdw` |
| `--vdw-method` | str | None | `CalculationHints.vdw_method` (`d3`, `d3bj`, `ts`, or `mbd`) |
| `--conv-thr` | float | None | `CalculationHints.conv_thr` |
| `--mixing-beta` | float | None | `CalculationHints.mixing_beta` |
| `--electron-maxstep` | int | None | `CalculationHints.electron_maxstep` |
| `--json` | flag | False | Print full JSON output |

## Python/CLI control parity

Every `CalculationIntent` field maps directly to a CLI option. Every
`CalculationHints` field also maps directly except `CalculationHints.pseudo_mode`:
the CLI sets `CalculationIntent.pseudo_mode` with `--pseudo-mode` instead of
exposing a second override for the same effective pseudopotential-family choice.

`accuracy_level` and `--accuracy-level` were intentionally removed because no
stage implemented different scientific behavior for the advertised levels.

## Boolean options

`--spin-polarized`, `--spin-orbit-coupling`, and `--use-vdw` accept `true` or
`false` as strings, not as bare flags. Their underlying hint fields are
`bool | None`:

- **Omitted**: let Core decide (value is `None`).
- `--use-vdw true`: force dispersion correction on (value is `True`).
- `--use-vdw false`: force dispersion correction off (value is `False`).

`--vdw-method` selects a preferred code-agnostic method. It can be supplied with
`--use-vdw true`, or without `--use-vdw` so structure analysis still decides
whether vdW applies. Combining a method with `--use-vdw false` is contradictory
and is rejected by the shared `CalculationHints` contract before job execution.

## Output formats

### JSON (`--json`)

Full JSON envelope: `{"request": request.to_dict(), **result.to_dict()}` printed with `indent=2, sort_keys=True`. Suitable for piping to `jq` or HTTP services.

### Human-readable (default)

Compact summary:

```text
formula: Si
code: quantum_espresso
task: scf_single_point
k-grid: 8 8 8
generated files:
  inputs/qe.in
bundle: run/
warnings:
  - Electronic character is unknown from structure facts alone...
```

## Pseudo loading

`--pseudo-root` recursively searches the given directory for `.upf` and `.UPF` files, parses each one with `parse_upf_metadata()`, and passes the resulting `PseudoMetadata` list to the selection stage. CLI functional intent and parsed UPF functional metadata use the same canonical labels. Supported PBEsol spellings match; unrecognized labels remain distinct rather than falling back to PBE or another functional.

## Kmesh backend selection

A bare invocation constructs a one-shot `CoreRuntime` with the same default
composition used by the Python API. That backend lazily resolves the configured
QRF model and falls back to heuristic advice with a provenance warning if model
loading or inference fails. Explicit `--k-grid` and `--k-spacing` hints bypass
model resolution entirely. The CLI closes its runtime before exit; long-lived
HTTP/MCP hosts instead keep one runtime for their full application lifetime.

Use `--heuristic-kpoints` to disable model resolution explicitly:

```bash
goldilocks-core recommend structure.cif --heuristic-kpoints --json
```

`--model` instead replaces the default with a local CSLR model:

```bash
goldilocks-core recommend structure.cif --model model.joblib --json
```

The CLI builds a `ModelSpec`, creates `ml_kmesh_advisor(spec)`, replaces the default Kmesh backend in `Pipeline`, and owns that composition with:

```python
with CoreRuntime(pipeline=pipeline) as runtime:
    result = runtime.run(request)
```

The model path is not added to `CoreJobRequest`. Backend selection is executable configuration, not request data. `--model-name` and `--model-version` are local-model metadata and are rejected unless `--model` selects that backend.

Hint precedence still applies:

```bash
goldilocks-core recommend structure.cif --model model.joblib --k-grid 4 4 4
```

This uses the explicit grid and records `provenance.source="user_hint"`; the model is not consulted for k-points.

When no k-point hint is set, the model supplies the grid and the resulting `KPointSelection` records `provenance.source="model"`.

`--model` and `--heuristic-kpoints` are mutually exclusive. Default remote
locations and full 40-character commit revisions come from the model registry. Set
`GOLDILOCKS_MODEL_REGISTRY` to an alternate TOML registry to replace them. Hub
artifacts use the `huggingface_hub` cache; because joblib artifacts can execute
code while loading, only select registries and revisions you trust.

## Standalone kmesh CLI

The `goldilocks-kmesh` command continues to expose the ML advisor directly:

```bash
goldilocks-kmesh structure.cif --model model.joblib
```

It returns only a k-point recommendation. Use `goldilocks-core ... --model` when the prediction should be part of the staged Core pipeline.