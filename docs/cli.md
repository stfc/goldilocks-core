# CLI reference

For installation and a first calculation, follow the
[quickstart](quickstart.md).

## Common commands

Replace `structure.cif` with your CIF or POSCAR:

```bash
uv run goldilocks inspect structure.cif --json
uv run goldilocks compute structure.cif --preset recommend --json
uv run goldilocks compute structure.cif --preset generate --out silicon-run
```

These inspect the structure, recommend settings, and write inputs, respectively.
Use `uv run goldilocks --help` or a subcommand's `--help` for syntax.

## Choose results

Every `compute` requires one of:

| Option               | Results                                                             |
| -------------------- | ------------------------------------------------------------------- |
| `--preset recommend` | Analysis, parameter advice, k-points, and pseudopotential selection |
| `--preset generate`  | Recommendations and complete calculation inputs                     |
| `--outputs IDS`      | Selected records, such as `analysis,k_points`                       |

`uv run goldilocks capabilities --json` lists available tasks, presets, record
IDs, models, tables, and defaults. `uv run goldilocks examples path` locates the
bundled structures.

## Save output or print JSON

| Option               | Output                                                   |
| -------------------- | -------------------------------------------------------- |
| `--out DIRECTORY`    | A new calculation directory                              |
| `--archive FILE.zip` | The same contents in a ZIP                               |
| `--no-out`           | Recommendations or inputs in memory, without publication |

Choose at most one of these flags. Explicit destinations must not exist. Writing
a directory or archive requires complete input data: use `--preset generate` or
`--outputs dft_input_data`.

Without an output flag, complete input data is written to `goldilocks_out`, then
`goldilocks_out_1`, and so on. Recommendations alone do not create a directory.

`--json` prints structured results and warnings. Use `--no-out --json` when you
want JSON without writing a calculation directory.

## Scientific controls

Defaults are Quantum ESPRESSO single-point SCF, PBEsol, and efficiency-tier
pseudopotentials. See [scientific conventions](conventions.md) for numerical
defaults and override rules.

| Flag                                                     | Values or meaning                                           |
| -------------------------------------------------------- | ----------------------------------------------------------- |
| `--code`, `--task`                                       | Built-in values: `quantum_espresso`, `scf_single_point`     |
| `--functional`                                           | Exchange-correlation functional                             |
| `--pseudo-accuracy`                                      | `efficiency` or `precision`                                 |
| `--pseudo-table ID`                                      | Choose a registered table                                   |
| `--pseudo-root DIRECTORY`                                | Use local UPF files                                         |
| `--pseudo-type`                                          | `NC`, `USPP`, or `PAW`                                      |
| `--relativistic-mode`                                    | `scalar`, `full`, or `non-relativistic`                     |
| `--k-grid NK1 NK2 NK3`                                   | Three positive integers                                     |
| `--k-spacing`                                            | Positive spacing in Å⁻¹, using the VASP KSPACING convention |
| `--smearing-type`                                        | `fixed`, `gaussian`, `mp`, or `cold`                        |
| `--smearing-width-ry`                                    | Smearing width in Ry                                        |
| `--spin-polarized`, `--spin-orbit-coupling`, `--use-vdw` | `true` or `false`                                           |
| `--vdw-method`                                           | `d3`, `d3bj`, `ts`, or `mbd`                                |
| `--conv-thr`                                             | Positive SCF threshold in Ry                                |
| `--mixing-beta`                                          | Positive density-mixing factor                              |
| `--electron-maxstep`                                     | Positive maximum number of SCF iterations                   |

Grid, smearing, spin, dispersion, and convergence overrides are optional. For
table compatibility and local-file requirements, see
[Pseudopotentials](pseudopotentials.md).

`--model PATH` loads a local k-index model; `--model-name` and `--model-version`
optionally label its provenance.

## Install and check assets

```bash
uv run goldilocks assets install default
uv run goldilocks assets status default
uv run goldilocks assets verify default
```

Use a profile, asset ID, or table ID. `default` installs the two prediction
models and a PBEsol efficiency PseudoDojo table; `workbench` installs all
registered models and tables. `install` also repairs corrupt installations.

`compute --fetch-missing` installs missing required dependencies and retries.
See [asset storage](pseudopotentials.md#find-stored-assets) for locations.

## Serve HTTP

```bash
uv run goldilocks assets install workbench
uv run --extra http goldilocks serve http
```

The server defaults to **http://127.0.0.1:8000**. `--host` and `--port` change
the address. `--static-root DIRECTORY` also serves a built Workbench.

| Endpoint            | Purpose                                                      |
| ------------------- | ------------------------------------------------------------ |
| `GET /capabilities` | Available tasks, records, models, and tables                 |
| `POST /inspect`     | Structure inspection                                         |
| `POST /compute`     | Multipart result JSON and, for complete inputs, a ZIP        |
| `GET /health`       | Process health                                               |
| `GET /ready`        | Workbench asset readiness; 503 for missing or corrupt assets |
| `GET /openapi.json` | Request and response schemas                                 |

Interactive API documentation is at `/docs`.

### HTTP security

Keep the default localhost binding for local use. The server has no built-in
authentication; restrict network access with a firewall or authenticated reverse
proxy before exposing it. Configure TLS and request limits there.

HTTP and MCP accept inline structures and registered table IDs, not local
structure paths, model locations, pseudopotential roots, or publication paths.
Server operators control installed assets. HTTP returns ZIP bytes without
writing calculation directories.

## Serve local MCP

Configure your MCP client to launch this command from the repository root:

```bash
uv run --extra mcp goldilocks serve mcp
```

The stdio tools are `capabilities`, `inspect_structure`, and `compute`. By
default, complete inputs are written to an automatically named `goldilocks_out`
directory in the server's working directory. Send `"output": {"kind": "memory"}`
to keep results in memory. Choose the working directory and OS account
carefully: clients can trigger these writes.
