# First calculation

Generate a Quantum ESPRESSO SCF input for silicon, check the result, and run it.
For Python, see the [Python guide](tutorial.md).

Already generated `si-run` from the README? Continue with
[checking the settings](#3-check-the-settings).

## 1. Install

Follow the [repository setup](../README.md#try-it), then run these commands from
the repository directory:

```bash
uv run goldilocks assets install default
uv run goldilocks assets verify default
```

This downloads and checks the k-point model, the metallicity classifier, and the
PseudoDojo PBEsol efficiency pseudopotential table. The first installation needs
an internet connection.

## 2. Generate an input

```bash
uv run goldilocks compute src/goldilocks_core/examples/structures/Si.cif --preset generate --out si-run
```

Replace the bundled silicon path with your own CIF or POSCAR when you are ready.
Choose a new output directory each time; Goldilocks will not overwrite an
existing one.

The main files in `si-run/` are:

| Path                        | Contents                                     |
| --------------------------- | -------------------------------------------- |
| `inputs/qe.in`              | Quantum ESPRESSO input                       |
| `pseudo/`                   | The selected UPF pseudopotential files       |
| `source/`, `structure/`     | Original and normalized structures           |
| `goldilocks.json`           | Settings, provenance, and file hashes        |
| `CITATIONS.md`, `licences/` | Citation and licence information             |

## 3. Check the settings

Read any warnings printed by the command and open `si-run/inputs/qe.in`. Check
the k-point grid, energy cutoffs, occupations, and spin settings against what
you know about your material.

Model predictions and table cutoffs are starting points, not convergence tests.
See [Recommendations](science.md) for how each choice is made and
[Scientific conventions](conventions.md) for units.

To choose a grid yourself, generate a second input with `--k-grid`:

```bash
uv run goldilocks compute src/goldilocks_core/examples/structures/Si.cif --preset generate --k-grid 4 4 4 --out si-grid-4
```

The `4 × 4 × 4` grid demonstrates an override; it is not a converged value for
silicon. Other controls are in the [CLI reference](cli.md#scientific-controls).

## 4. Run Quantum ESPRESSO

With Quantum ESPRESSO installed, run `pw.x` **from inside the output directory**
so it can find `./pseudo`:

```bash
cd si-run
pw.x -in inputs/qe.in > qe.out
```

Review `qe.out` to check that the SCF calculation converged.

## Next

- [Python API](tutorial.md) — inspect structures and generate inputs in a
  script.
- [Pseudopotentials](pseudopotentials.md) — change functional, table, or UPF
  files.
- [Workbench](../web/README.md) — prepare and review inputs in a browser.
