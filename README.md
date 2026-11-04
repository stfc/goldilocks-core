# goldilocks-core

Goldilocks recommends settings for density functional theory (DFT) calculations
and generates Quantum ESPRESSO input files (SCF, DOS, band structure,
relaxation, variable-cell relaxation, and phonons with their density of
states and dispersion) from a crystal structure.

## Installation

Published on PyPI. For just the `goldilocks` CLI:

```bash
pip install goldilocks-core
```

For the CLI plus the built Workbench, ready to serve with no separate
frontend build:

```bash
pip install "goldilocks-core[http]"
goldilocks serve http
```

Open **http://127.0.0.1:8000** -- the Workbench frontend is bundled into
the package itself as of this release.

To work on the Workbench or the codebase itself, clone the repository
instead. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
first:

```bash
git clone https://github.com/stfc/goldilocks-core.git
cd goldilocks-core
uv sync
```

## Try it

### Start the Workbench

With Node.js 24 or newer installed, run:

```bash
uv sync --extra http
npm --prefix web ci
uv run goldilocks assets install workbench
uv run --extra http poe workbench
```

The asset step installs the models and pseudopotential tables. Open
**http://127.0.0.1:5173**, upload a CIF or POSCAR, review the recommended
settings, and download the generated inputs.

For a built frontend instead, stop the development servers and run:

```bash
uv run --extra http poe stage
```

Then open **http://127.0.0.1:8000**. See the [Workbench guide](web/README.md)
for Docker and development checks.

### Generate inputs from the command line

Download the prediction models and default pseudopotential table, then generate
inputs for the bundled silicon structure:

```bash
uv run goldilocks assets install default
uv run goldilocks run src/goldilocks_core/examples/structures/Si.cif --out si-run
```

Open `si-run/scf.in` to see the input. The directory also contains the
pseudopotential file with its table's licence, a submission script,
`goldilocks.json` (the request it answers: code, task, HPC profile, your
overrides, the structure's sha256 and the goldilocks-core version; every
setting with its source, and for a setting a model chose, the model with what
it returned) and `CITATIONS.md` (the pseudopotential table and every model
used).

Treat the recommended settings as a starting point: review warnings and check
convergence for your calculation. The [quickstart](docs/quickstart.md) explains
the output and how to run it.

## Guides and reference

- [First calculation](docs/quickstart.md) — generate, check, and run an input.
- [Python API](docs/tutorial.md) — use Goldilocks in a script.
- [Recommendations](docs/science.md) — understand the choices and their limits.
- [Pseudopotentials](docs/pseudopotentials.md) — choose a table and understand
  automatic selection.
- [CLI reference](docs/cli.md) — commands and options.
- [mMACE](docs/mmace-setup.md) — check that the magnetism features use the
  ML model, or use another checkpoint.
- [Scientific conventions](docs/conventions.md) — units and numerical
  definitions.
- [Contributing](docs/architecture.md) — code layout and development checks.

## Licence

Code: [BSD 3-Clause](LICENSE). Documentation under `docs/` and example
structures: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Downloaded pseudopotentials retain their
[upstream licences](docs/pseudopotentials.md#licences-and-citations).
