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

Runs Load → Analyze → Advise → Kmesh → Select → Generate. Outputs a recommendation with generated input files.

### bundle

```bash
goldilocks-core bundle structure.cif --out run/ [options]
```

Runs the full pipeline and writes a portable bundle directory. `--out` is required for bundle mode.

## Common options

| Flag | Type | Default | Maps to |
| --- | --- | --- | --- |
| `structure` | positional | — | `CoreJobRequest.structure` |
| `--code` | choice | `quantum_espresso` | `CalculationIntent.code` |
| `--task` | choice | `scf_single_point` | `CalculationIntent.task` |
| `--functional` | str | `PBE` | `CalculationIntent.functional` |
| `--accuracy-level` | choice | `standard` | `CalculationIntent.accuracy_level` |
| `--pseudo-mode` | str | `efficiency` | `CalculationIntent.pseudo_mode` |
| `--pseudo-type` | str | None | `CalculationHints.pseudo_type` |
| `--relativistic-mode` | str | None | `CalculationHints.relativistic_mode` |
| `--pseudo-root` | path | None | Loads UPF files recursively into `pseudo_metadata` |
| `--model` | path | None | Builds an ML Kmesh backend in `Pipeline` |
| `--model-name` | str | `cli-kmesh-model` | Model name recorded in Kmesh provenance |
| `--model-version` | str | `unknown` | Model version recorded in `ModelSpec` |
| `--k-spacing` | float | None | `CalculationHints.k_spacing` |
| `--k-grid` | 3 ints | None | `CalculationHints.k_grid` |
| `--smearing-type` | str | None | `CalculationHints.smearing_type` |
| `--smearing-width-ry` | float | None | `CalculationHints.smearing_width_ry` |
| `--spin-polarized` | `true`/`false` | None | `CalculationHints.spin_polarized` |
| `--spin-orbit-coupling` | `true`/`false` | None | `CalculationHints.spin_orbit_coupling` |
| `--conv-thr` | float | None | `CalculationHints.conv_thr` |
| `--mixing-beta` | float | None | `CalculationHints.mixing_beta` |
| `--electron-maxstep` | int | None | `CalculationHints.electron_maxstep` |
| `--json` | flag | False | Print full JSON output |

## Boolean options

`--spin-polarized` and `--spin-orbit-coupling` accept `true` or `false` as strings, not as bare flags. This is because the underlying hint field is `bool | None`:

- **Omitted**: let Core decide (value is `None`).
- `--spin-polarized true`: force spin-polarized (value is `True`).
- `--spin-polarized false`: force non-magnetic (value is `False`).

## Output formats

### JSON (`--json`)

Full `CoreResult.to_dict()` output (with the request echoed alongside as `request`) using `indent=2, sort_keys=True`. Suitable for piping to `jq` or HTTP services.

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

`--pseudo-root` recursively searches the given directory for `.upf` and `.UPF` files, parses each one with `parse_upf_metadata()`, and passes the resulting `PseudoMetadata` list to the selection stage.

## ML Kmesh backend

`--model` integrates the ML k-mesh advisor into the staged pipeline:

```bash
goldilocks-core recommend structure.cif --model model.joblib --json
```

The CLI builds a `ModelSpec`, creates `ml_kmesh_advisor(spec)`, replaces the default Kmesh backend in `Pipeline`, and calls:

```python
run_core_job(request, pipeline=pipeline)
```

The model path is not added to `CoreJobRequest`. Backend selection is executable configuration, not request data.

Hint precedence still applies:

```bash
goldilocks-core recommend structure.cif --model model.joblib --k-grid 4 4 4
```

This uses the explicit grid and records `provenance.source="user_hint"`; the model is not consulted for k-points.

When no k-point hint is set, the model supplies the grid and the resulting `KPointSelection` records `provenance.source="model"`.

## Standalone kmesh CLI

The `goldilocks-kmesh` command continues to expose the ML advisor directly:

```bash
goldilocks-kmesh structure.cif --model model.joblib
```

It returns only a k-point recommendation. Use `goldilocks-core ... --model` when the prediction should be part of the staged Core pipeline.