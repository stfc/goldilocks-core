# CLI reference

The `goldilocks` command exposes the same capabilities, structure inspection,
and compute operations as the Python `Service`.

## Scientific commands

### capabilities

```bash
uv run goldilocks capabilities [--json]
```

Lists tasks, presets, selectable records, target codes, models,
pseudopotential sets, and defaults. `--json` prints the canonical
capabilities document.

### inspect

```bash
uv run goldilocks inspect structure.cif [--json]
```

Normalizes a local CIF or POSCAR and reports its facts. `--json` prints the
canonical inspection document (`source`, `structure`, `canonical_cif`):

```text
"structure": {
    "formula": "Si8",
    "reduced_formula": "Si",
    "site_count": 8,
    "periodicity": [true, true, true],
    ...
}
```

### compute

```bash
uv run goldilocks compute structure.cif (--preset ID | --outputs IDS) [options]
```

`--preset recommend` requests the analysis, advice, k-points, and selection
records. `--preset generate` additionally requests the generated files and
the complete ready-to-run bundle. `--outputs` accepts comma-separated stable
record IDs instead of a preset:
`analysis`, `advice`, `k_points`, `selection`, `generated_files`,
`dft_input_data`.

Selection options are mutually exclusive. Recommendation and generation are
preset IDs only; there are no `recommend` or `generate` commands.

## Compute output

Choose at most one output option:

- `--out DIRECTORY` publishes a new ready-to-run directory;
- `--archive FILE.zip` publishes a new ready-to-run archive;
- `--no-out` keeps the result in memory;
- omission automatically publishes a directory only when the result contains
  the complete bundle.

The core never overwrites an existing destination. With `--json`, the result
prints as the canonical computation document, including publication metadata.
Human output reports the structure, formula, target code, task, warnings, and
publication path:

```text
generated files:
  inputs/qe.in
published directory: /home/you/run
```

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
k-index model. `--model-name` and `--model-version` require `--model`.
Explicit `--k-grid` or `--k-spacing` bypasses model inference.

`--fetch-missing` installs only an exact missing asset reported by the core,
then retries. It does not replace corrupt assets.

## Asset administration

```bash
uv run goldilocks assets install [PROFILE|ASSET_ID|TABLE_ID]
uv run goldilocks assets status [PROFILE|ASSET_ID|TABLE_ID]
uv run goldilocks assets verify [PROFILE|ASSET_ID|TABLE_ID]
```

The default asset root is `$XDG_DATA_HOME/goldilocks/assets`, falling back to
`~/.local/share/goldilocks/assets`. Override it with `GOLDILOCKS_ASSET_ROOT`.
See [Pseudopotential tables](pseudopotentials.md) for registered table
selection and local-source licensing requirements.

## Examples

```bash
uv run goldilocks examples path
uv run goldilocks inspect "$(uv run goldilocks examples path)/Si.cif" --json
```

## Optional transports

HTTP and MCP are optional extras exposing the same three operations:

```bash
uv sync --extra http
uv sync --extra mcp
uv run goldilocks serve http --host 127.0.0.1 --port 8000
uv run goldilocks serve mcp
```

HTTP exposes `GET /capabilities`, `POST /inspect`, `POST /compute`,
`GET /health`, and `GET /ready`. Compute returns one multipart response
containing the canonical result JSON and — when the preset or record
selection produced the complete bundle — the exact ZIP from that execution.
Local stdio MCP exposes `capabilities`, `inspect_structure`, and `compute`.

Because transports may face untrusted callers, they accept a deliberately
narrow surface. The trust boundary:

| Input | Python | CLI | HTTP | MCP |
| --- | --- | --- | --- | --- |
| structure by filesystem path | yes | yes | no | no |
| inline structure content | yes | no | yes | yes |
| pseudopotential table ID | yes | yes | yes | yes |
| local pseudopotential root | yes | yes | no | no |
| explicit pseudopotential metadata | yes | no | no | no |
| model location or specification | yes | yes | no | no |
| output directory or archive path | yes | yes | no | no |

HTTP compute always returns the archive as response bytes rather than writing
server-side files; MCP may publish to a server-chosen directory, and explicit
memory output suppresses that publication.