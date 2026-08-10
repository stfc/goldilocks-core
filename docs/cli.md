# CLI reference

`goldilocks-core` is a thin transport over `CoreJobRequest` and `run_core_job()`. Preset commands return a `CoreResult`; `compute` returns `CoreRecords`.

## recommend

```bash
goldilocks-core recommend STRUCTURE [options]
```

Runs the `recommend` preset and returns analysis, advice, k-points, and pseudopotential selection as a complete `CoreResult`.

```bash
goldilocks-core recommend structure.cif --k-grid 4 4 4 --json
```

Without `--json`, the command prints a short summary.

## generate

```bash
goldilocks-core generate STRUCTURE [--out DIR] [options]
```

Runs the `generate` preset and returns a `CoreResult` containing generated input files. `--out DIR` publishes those files and `manifest.json`; the destination must not already exist.

```bash
goldilocks-core generate structure.cif \
    --pseudo-root path/to/pseudos \
    --k-grid 4 4 4 \
    --out run/ \
    --json
```

Publication is part of the generate entrypoint. There is no separate bundle command or mode.

## compute

```bash
goldilocks-core compute STRUCTURE --outputs Type1,Type2 [options]
```

Runs a query for an arbitrary subset of public record types. The executor resolves the minimal required subgraph and the command always prints a JSON `CoreRecords` object keyed by type name.

```bash
goldilocks-core compute structure.cif \
    --outputs StructureAnalysisRecord,KPointSelection \
    --k-grid 4 4 4
```

Example output shape:

```json
{
  "KPointSelection": {
    "grid": [4, 4, 4],
    "mesh_type": "monkhorst-pack",
    "provenance": {},
    "shift": [0, 0, 0]
  },
  "StructureAnalysisRecord": {}
}
```

Supported output names are:

- `StructureAnalysisRecord`
- `ParameterAdvice`
- `KPointSelection`
- `SelectionRecord`
- `GeneratedFiles`

An empty list or unknown name is rejected before execution. `--json` is accepted as a common option but is unnecessary because compute output is always JSON.

## examples

```bash
goldilocks-core examples path
```

Prints the directory holding the example structures installed with the package. It takes none of the common options.

```bash
goldilocks-core recommend "$(goldilocks-core examples path)/Si.cif" --json
```

The directory's `README.md` explains what each example exercises. From Python, use `goldilocks_core.examples.structure("Si.cif")`.

## Common options

These options apply to `recommend`, `generate`, and `compute`.

| Flag | Type | Default | Request field |
| --- | --- | --- | --- |
| `STRUCTURE` | positional path | — | `structure` |
| `--code` | choice | `quantum_espresso` | `intent.code` |
| `--task` | choice | `scf_single_point` | `intent.task` |
| `--functional` | string | `PBEsol` | `intent.functional` |
| `--pseudo-mode` | string | `efficiency` | `intent.pseudo_mode` |
| `--pseudo-type` | string | None | `hints.pseudo_type` |
| `--relativistic-mode` | string | None | `hints.relativistic_mode` |
| `--pseudo-root` | path | None | loaded `pseudo_metadata` |
| `--model` | path | None | local `kmesh_model` |
| `--model-name` | string | `cli-kmesh-model` with `--model` | `kmesh_model.name` |
| `--model-version` | string | `unknown` with `--model` | `kmesh_model.version` |
| `--k-spacing` | float | None | `hints.k_spacing` |
| `--k-grid` | 3 integers | None | `hints.k_grid` |
| `--smearing-type` | `fixed`, `gaussian`, `mp`, `cold` | None | `hints.smearing_type` |
| `--smearing-width-ry` | float | None | `hints.smearing_width_ry` |
| `--spin-polarized` | `true` or `false` | None | `hints.spin_polarized` |
| `--spin-orbit-coupling` | `true` or `false` | None | `hints.spin_orbit_coupling` |
| `--use-vdw` | `true` or `false` | None | `hints.use_vdw` |
| `--vdw-method` | string | None | `hints.vdw_method` |
| `--conv-thr` | float | None | `hints.conv_thr` |
| `--mixing-beta` | float | None | `hints.mixing_beta` |
| `--electron-maxstep` | integer | None | `hints.electron_maxstep` |
| `--json` | flag | false | preset output formatting |

`--out` is valid only for `generate`. `--outputs` is required only for `compute`.

Functional labels are canonicalized; for example, `PBESOL` becomes `PBEsol`. `accuracy_level` and `--accuracy-level` were removed because no stage implemented different behavior for them.

## Boolean options

`--spin-polarized`, `--spin-orbit-coupling`, and `--use-vdw` take explicit `true` or `false` strings:

- omitted: leave the hint as `None` and let Core decide;
- `true`: force the behavior on;
- `false`: force it off.

`--vdw-method` can accompany `--use-vdw true`, or can be supplied without `--use-vdw` so analysis decides whether vdW applies. Combining it with `--use-vdw false` is rejected.

## Output formats

### Preset JSON

For `recommend --json` and `generate --json`, the CLI prints:

```text
{"request": request.to_dict(), **result.to_dict()}
```

The JSON is indented and key-sorted. Generated file contents are included in generate output.

### Query JSON

`compute` prints `CoreRecords.to_dict()` directly. Only requested type names are present; the request is not echoed.

### Human-readable presets

Without `--json`, preset commands print formula, code, task, k-grid, generated file paths, publication path when present, and warnings.

## Pseudopotential loading

`--pseudo-root` recursively searches for `.upf` and `.UPF` files, parses each with `parse_upf_metadata()`, and supplies the resulting metadata to Select. Generate requires complete selections for every element.

## Kmesh backend

Without a k-point hint, commands use the built-in QRF k-distance model. Model loading and inference errors propagate. Explicit `--k-grid` and `--k-spacing` hints bypass model resolution.

`--model` selects a local CSLR k-index model:

```bash
goldilocks-core recommend structure.cif --model model.joblib --json
```

`--model-name` and `--model-version` describe that local model and are rejected without `--model`. Explicit hints still take precedence over the selected model.

Default remote artifacts and immutable revisions come from the model registry. Set `GOLDILOCKS_MODEL_REGISTRY` to use another registry. Only load trusted joblib artifacts.

## Transport servers

Optional server commands are:

```bash
goldilocks-core serve http --host 127.0.0.1 --port 8000
goldilocks-core serve mcp
```

Install the corresponding `http` or `mcp` extra first. See [transport.md](transport.md).

## Standalone kmesh CLI

`goldilocks-kmesh` exposes the ML advisor directly:

```bash
goldilocks-kmesh structure.cif --model model.joblib
```

It returns only a k-point recommendation. Use `goldilocks-core recommend`, `generate`, or `compute` when the prediction should participate in the Core DAG.
