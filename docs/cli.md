# CLI reference

The `goldilocks-core` command is a thin wrapper around `CoreJobRequest` and `run_core_job()`. It parses arguments, runs the staged pipeline, and prints JSON or a short human-readable summary.

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

Runs Load → Analyze → Advise → Kmesh → Select → Generate. Outputs a recommendation with generated input files. Pass `--out <dir>` to write a portable bundle directory instead of returning in-memory files; the directory must not already exist.

### Raw stage subcommands

```bash
goldilocks-core analyze structure.cif [options]
goldilocks-core kmesh structure.cif [options]
goldilocks-core advise structure.cif [options]
goldilocks-core select structure.cif [options]
```

Each runs only the sub-graph it needs and prints the corresponding record. `analyze` runs Load → Analyse; `kmesh` resolves k-points using the owned backend; `advise` runs Load → Analyse → Advise; `select` runs Load → Analyse → Advise → Select (without invoking kmesh).

### examples

```bash
goldilocks-core examples path
```

Prints the directory holding the example structures installed with the package. It takes none of the common options below.

Use it to run the pipeline without supplying a structure of your own:

```bash
goldilocks-core recommend "$(goldilocks-core examples path)/Si.cif" --json
```

The directory's `README.md` explains what each example exercises. From Python, use `goldilocks_core.examples.structure("Si.cif")` rather than building the path by hand.

## Common options

| Flag | Type | Default | Maps to |
| --- | --- | --- | --- |
| `structure` | positional | — | `CoreJobRequest.structure` |
| `--code` | choice | `quantum_espresso` | `CalculationIntent.code` |
| `--task` | choice | `scf_single_point` | `CalculationIntent.task` |
| `--functional` | str | `PBEsol` | `CalculationIntent.functional` (canonicalized; e.g. `PBESOL` → `PBEsol`) |
| `--pseudo-mode` | str | `efficiency` | `CalculationIntent.pseudo_mode` |
| `--pseudo-type` | str | None | `CalculationHints.pseudo_type` |
| `--relativistic-mode` | str | None | `CalculationHints.relativistic_mode` |
| `--pseudo-root` | path | None | Loads UPF files recursively into `pseudo_metadata` |
| `--model` | path | None | `CoreJobRequest.kmesh_model` (local k-index model) |
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
| `--out` | path | None | `generate` only: write a portable bundle directory |

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

A bare invocation delegates to the built-in QRF k-distance model, the same
default used by the Python API. That backend lazily resolves the configured
model and reports model loading or inference errors directly. Explicit
`--k-grid` and `--k-spacing` hints bypass model resolution entirely.

`--model` selects a local CSLR k-index model instead of the default:

```bash
goldilocks-core recommend structure.cif --model model.joblib --json
```

The CLI builds a `ModelSpec` from `--model`, `--model-name`, and
`--model-version`, puts it on `CoreJobRequest.kmesh_model`, and calls
`run_core_job(request)`. The model spec is request data, so it serializes with
the rest of the job. `--model-name` and `--model-version` are local-model
metadata and are rejected unless `--model` is set.

Hint precedence still applies:

```bash
goldilocks-core recommend structure.cif --model model.joblib --k-grid 4 4 4
```

This uses the explicit grid and records `provenance.source="user_hint"`; the model is not consulted for k-points.

When no k-point hint is set, the model supplies the grid and the resulting `KPointSelection` records `provenance.source="model"`.

Default remote locations and full 40-character commit revisions come from the
model registry. Set `GOLDILOCKS_MODEL_REGISTRY` to an alternate TOML registry to
replace them. Hub artifacts use the `huggingface_hub` cache; because joblib
artifacts can execute code while loading, only select registries and revisions
you trust.

## Standalone kmesh CLI

The `goldilocks-kmesh` command continues to expose the ML advisor directly:

```bash
goldilocks-kmesh structure.cif --model model.joblib
```

It returns only a k-point recommendation. Use `goldilocks-core ... --model` when the prediction should be part of the staged Core pipeline.