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
uv run goldilocks compute src/goldilocks_core/examples/structures/Si.cif --preset generate --out si-run
```

Open `si-run/inputs/qe.in` to see the input. The directory also contains the
pseudopotentials, structures, and supporting data.

Treat the recommended settings as a starting point: review warnings and check
convergence for your calculation. The [quickstart](docs/quickstart.md) explains
the output and how to run it.

## Run the Workbench from a container

CI publishes the built Workbench image to GitHub Container Registry on every
version tag and nightly:

```bash
docker pull ghcr.io/stfc/goldilocks-workbench:0.1.0
```

Choose a tag: version numbers (`0.1.0`, rolling `0.1`, `0`, `latest`) track
GitHub releases, `nightly` tracks `main` (rebuilds at 03:00 UTC daily), and
`nightly-<date>` or `sha-<ref>` pins an exact build. The image is private;
authenticate before pulling:

```bash
docker login ghcr.io -u <github-username> -p <token-with-read-packages>
docker run --publish 8000:8000 ghcr.io/stfc/goldilocks-workbench:0.1.0
```

Then open **http://127.0.0.1:8000**. The image bundles the models and
pseudopotential tables, so `assets install` is not needed. The Python package
is not published to PyPI; download the sdist or wheel from the repository's
GitHub Releases page.

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
