# CLI reference

The `goldilocks` command is a thin wrapper over `CoreService`. Preset commands
build `PresetRequest`; `compute` builds `QueryRequest`.

## Commands

### recommend

```bash
goldilocks recommend structure.cif [options]
```

Runs Load → Analyze → Advise → Kmesh → Select. Outputs a recommendation without generated files.

### generate

```bash
goldilocks generate structure.cif [options]
```

Runs Load → Analyze → Advise → Kmesh → Select → Generate. Outputs a recommendation with generated input files. Pass `--out run/` to publish the files and manifest as a portable bundle; the destination must not already exist.

### compute

```bash
goldilocks compute structure.cif \
    --outputs analysis,k_points [options]
```

Runs the minimal task subgraph needed for the comma-separated stable record IDs
and always prints the selected records as JSON. Available IDs are `analysis`,
`advice`, `k_points`, `selection`, and `generated_files`.

### assets

```bash
goldilocks assets install [default|ASSET_ID]
goldilocks assets status [default|ASSET_ID]
goldilocks assets verify [default|ASSET_ID]
```

The default profile pins exact QRF, metallicity, and PseudoDojo table versions.
Installation downloads into a staging directory, verifies declared source
digests, normalizes provider files, inventories the result, and atomically
publishes a manifest-backed asset. `status` reports `installed`, `missing`, or
`corrupt`; `verify` checks every installed file.

The store root is `$GOLDILOCKS_ASSET_ROOT` when set. Otherwise it is
`$XDG_DATA_HOME/goldilocks/assets`, falling back to
`~/.local/share/goldilocks/assets`. Installed versions live at
`<root>/<asset-id>/<version>/`; staging archives are removed after installation.
See [Pseudopotential tables](pseudopotentials.md) for the installed table
layout, provider normalization, licensing, and citations.

### examples

```bash
goldilocks examples path
```

Prints the directory holding the example structures installed with the package. It takes none of the common options below.

Use it to run the pipeline without supplying a structure of your own:

```bash
goldilocks recommend "$(goldilocks examples path)/Si.cif" --json
```

The directory's `README.md` explains what each example exercises. From Python, use `goldilocks_core.examples.structure("Si.cif")` rather than building the path by hand.

### serve

```bash
goldilocks serve http [--host 127.0.0.1] [--port 8000]
goldilocks serve mcp
```

The HTTP and MCP transports require their optional dependencies:

```bash
uv sync --extra http
uv sync --extra mcp
```

HTTP exposes `/recommend`, `/generate`, `/compute`, `/tasks`, `/codes`,
`/models`, and `/health`. MCP exposes `recommend`, `generate`, `compute`,
`list_tasks`, `list_codes`, and `list_models` as stdio tools. Each server owns
one `CoreService` for its lifetime.

Transport requests carry only the calculation — inline CIF/POSCAR content,
`intent`, `hints`, and `outputs`. File paths, model overrides, and
pseudopotential sources are never request data: the server resolves models
and pseudopotentials from its own environment. Pass files by content, not by
path.

## Common options

| Flag | Type | Default | Maps to |
| --- | --- | --- | --- |
| `structure` | positional | — | `PresetRequest.structure` or `QueryRequest.structure` |
| `--code` | choice | `quantum_espresso` | `CalculationIntent.code` |
| `--task` | choice | `scf_single_point` | `CalculationIntent.task` |
| `--functional` | str | `PBEsol` | `CalculationIntent.functional` (canonicalized; e.g. `PBESOL` → `PBEsol`) |
| `--pseudo-mode` | str | `efficiency` | `CalculationIntent.pseudo_mode` |
| `--pseudo-type` | str | None | `CalculationHints.pseudo_type` |
| `--relativistic-mode` | str | None | `CalculationHints.relativistic_mode` |
| `--pseudo-root` | path | None | Loads UPF files recursively into `pseudo_metadata` |
| `--fetch-missing` | flag | False | Explicitly install the complete default runtime profile before running |
| `--model` | path | None | request `kmesh_model` (local k-index model) |
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

`recommend` and `generate` print
`{"request": request.to_dict(), **result.to_dict()}` with stable keys.
`compute` always prints the selected `CoreRecords` JSON and does not use a
request envelope.

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

Without `--pseudo-root`, the CLI verifies and loads the installed default
PseudoDojo table manifest. A missing or corrupt table fails with an asset
diagnostic; the CLI does not download unless `--fetch-missing` is present.
`--pseudo-root` instead recursively loads `.upf` and `.UPF` files from an
explicit local directory and searches nearby JSON metadata for complete
cutoffs. CLI intent and parsed UPF metadata use the same canonical functional
labels. Unrecognized labels remain distinct rather than silently falling back.

## Kmesh backend selection

A bare invocation delegates to the built-in QRF k-distance model, the same
default used by the Python API. That backend lazily resolves the configured
model and reports model loading or inference errors directly. Explicit
`--k-grid` and `--k-spacing` hints bypass model resolution entirely.

`--model` selects a local CSLR k-index model instead of the default:

```bash
goldilocks recommend structure.cif --model model.joblib --json
```

The CLI builds a `ModelSpec` from `--model`, `--model-name`, and
`--model-version`, puts it on the request's `kmesh_model`, and dispatches
through the shared service surface. The model spec serializes with the rest of
the request. `--model-name` and `--model-version` are local-model metadata and
are rejected unless `--model` is set.

Hint precedence still applies:

```bash
goldilocks recommend structure.cif --model model.joblib --k-grid 4 4 4
```

This uses the explicit grid and records `provenance.source="user_hint"`; the model is not consulted for k-points.

When no k-point hint is set, the model supplies the grid and the resulting `KPointSelection` records `provenance.source="model"`.

Default model files are resolved from the verified asset store. Set
`GOLDILOCKS_MODEL_REGISTRY` only to use an explicit complete model registry;
model loading itself never performs network access.