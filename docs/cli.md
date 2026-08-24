# CLI reference

The `goldilocks` command exposes the same Capabilities, Structure Inspection,
and Compute operations as `Service`.

## Scientific commands

### capabilities

```bash
uv run goldilocks capabilities [--json]
```

Lists task, Preset, Record, target-code, model, pseudopotential-set, and default
control capabilities. `--json` prints the canonical `Capabilities` document.

### inspect

```bash
uv run goldilocks inspect structure.cif [--json]
```

Normalizes a local CIF or POSCAR and reports its source name, reduced formula,
and site count. `--json` prints the canonical `StructureInspection` document.

### compute

```bash
uv run goldilocks compute structure.cif (--preset ID | --outputs IDS) [options]
```

`--preset recommend` requests Analyze, Advise, Kmesh, and Select Records.
`--preset generate` additionally requests Generated Files and complete DFT Input
Data. `--outputs` accepts comma-separated stable Record IDs:
`analysis`, `advice`, `k_points`, `selection`, `generated_files`, and
`dft_input_data`.

Selection options are mutually exclusive. Recommendation and generation are
Preset IDs only; there are no `recommend` or `generate` commands.

## Compute output

Choose at most one output option:

- `--out DIRECTORY` publishes a new ready-to-run directory;
- `--archive FILE.zip` publishes a new ready-to-run archive;
- `--no-out` keeps the Result in memory;
- omission automatically publishes a directory only when the Result contains
  complete DFT Input Data.

Core never overwrites an existing destination. `--json` prints the canonical
`ComputationResult`, including publication metadata. Human output reports the
structure, formula when available, target code, task, important selected
Records, warnings, and publication kind and absolute path.

## Scientific controls

| Flag | Default | Core contract |
| --- | --- | --- |
| `structure` | required | `PathStructureSource` |
| `--code` | `quantum_espresso` | `CalculationIntent.code` |
| `--task` | `scf_single_point` | `CalculationIntent.task` |
| `--functional` | `PBEsol` | `CalculationIntent.functional` |
| `--pseudo-accuracy` | `efficiency` | `CalculationIntent.pseudo_accuracy` |
| `--pseudo-type` | None | `CalculationHints.pseudo_type` |
| `--relativistic-mode` | None | `CalculationHints.relativistic_mode` |
| `--pseudo-root` | None | local pseudopotential source |
| `--pseudo-table` | None | stable registered table ID |
| `--k-spacing` | None | `CalculationHints.k_spacing` |
| `--k-grid NK1 NK2 NK3` | None | `CalculationHints.k_grid` |
| `--smearing-type` | None | `CalculationHints.smearing_type` |
| `--smearing-width-ry` | None | `CalculationHints.smearing_width_ry` |
| `--spin-polarized true|false` | None | `CalculationHints.spin_polarized` |
| `--spin-orbit-coupling true|false` | None | `CalculationHints.spin_orbit_coupling` |
| `--use-vdw true|false` | None | `CalculationHints.use_vdw` |
| `--vdw-method` | None | `CalculationHints.vdw_method` |
| `--conv-thr` | None | `CalculationHints.conv_thr` |
| `--mixing-beta` | None | `CalculationHints.mixing_beta` |
| `--electron-maxstep` | None | `CalculationHints.electron_maxstep` |

`--model`, `--model-name`, and `--model-version` select and identify a local
k-index model. `--model-name` and `--model-version` require `--model`. Explicit
`--k-grid` or `--k-spacing` bypasses model inference.

`--fetch-missing` installs only an exact missing asset reported by Core, then
retries. It does not replace corrupt assets.

## Asset administration

```bash
uv run goldilocks assets install [default|ASSET_ID]
uv run goldilocks assets status [default|ASSET_ID]
uv run goldilocks assets verify [default|ASSET_ID]
```

The default asset root is `$XDG_DATA_HOME/goldilocks/assets`, falling back to
`~/.local/share/goldilocks/assets`. Override it with
`GOLDILOCKS_ASSET_ROOT`. See [Pseudopotential tables](pseudopotentials.md) for
registered table selection and local-source licensing requirements.

## Examples

```bash
uv run goldilocks examples path
uv run goldilocks inspect "$(uv run goldilocks examples path)/Si.cif" --json
```

## Optional transports

```bash
uv sync --extra http
uv sync --extra mcp
uv run goldilocks serve http --host 127.0.0.1 --port 8000
uv run goldilocks serve mcp
```

HTTP exposes `GET /capabilities`, `POST /inspect`, `POST /compute`,
`GET /health`, and `GET /ready`. HTTP accepts inline structure content only.
Compute output is either canonical JSON or an unstored ZIP response.

Local stdio MCP exposes exactly `capabilities`, `inspect_structure`, and
`compute`. MCP accepts local paths or inline sources. Omitted Compute output
automatically publishes complete DFT Input Data; explicit memory, directory,
and archive output variants are also available.
