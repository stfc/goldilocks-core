# goldilocks-core

Goldilocks recommends settings for density functional theory (DFT) calculations
and generates Quantum ESPRESSO self-consistent field (SCF) input files from a
crystal structure.

## Try it

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then
clone the repository:

```bash
git clone https://github.com/stfc/goldilocks-core.git
cd goldilocks-core
uv sync
```

Download the prediction models and default pseudopotential table, then generate
inputs for the bundled silicon structure:

```bash
uv run goldilocks assets install default
uv run goldilocks compute src/goldilocks_core/examples/structures/Si.cif --preset generate --out si-run
```

Open `si-run/inputs/qe.in` to see the input. The directory also contains the
pseudopotentials, structures, and supporting data.

Treat the recommended settings as a starting point: review warnings and check
convergence for your calculation. The [quickstart](docs/quickstart.md) explains
the output and how to run it.

Prefer a browser? Use the [Workbench](web/README.md).

## Guides and reference

- [First calculation](docs/quickstart.md) — generate, check, and run an input.
- [Python API](docs/tutorial.md) — use Goldilocks in a script.
- [Recommendations](docs/science.md) — understand the choices and their limits.
- [Pseudopotentials](docs/pseudopotentials.md) — choose a table or use your own
  files.
- [CLI reference](docs/cli.md) — commands and options.
- [Scientific conventions](docs/conventions.md) — units and numerical
  definitions.
- [Contributing](docs/architecture.md) — code layout and development checks.

## Licence

Code: [BSD 3-Clause](LICENSE). Documentation under `docs/` and example
structures: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Downloaded pseudopotentials retain their
[upstream licences](docs/pseudopotentials.md#licences-and-citations).
