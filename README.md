# goldilocks-core

Goldilocks recommends settings for density functional theory (DFT) calculations
and generates Quantum ESPRESSO input files (SCF, DOS, band structure,
relaxation, variable-cell relaxation, and phonons with their density of
states and dispersion) from a crystal structure.

## Installation

Goldilocks needs Python 3.12 or newer. The documentation is at
https://stfc.github.io/goldilocks-core/.

### Docker

Each release publishes an image that serves the Workbench, the browser
interface, with the prediction models and pseudopotential tables already
installed:

```bash
docker run --rm --publish 127.0.0.1:8000:8000 ghcr.io/stfc/goldilocks-core
```

Open **http://127.0.0.1:8000**, upload a CIF or POSCAR, review the
recommended settings, and download the generated inputs. Pin a release with
its version as the tag, such as `ghcr.io/stfc/goldilocks-core:0.3.0`. The
image is built for x86-64; Docker on Apple silicon runs it under emulation.
See [HTTP security](docs/cli.md#http-security) before exposing it beyond
localhost.

### pip

For the `goldilocks` command line:

```bash
pip install goldilocks-core
goldilocks assets install default
```

For the Workbench as well:

```bash
pip install "goldilocks-core[http]"
goldilocks assets install all
goldilocks serve http
```

Then open **http://127.0.0.1:8000**. The asset step downloads the prediction
models and pseudopotential tables; without it, Goldilocks refuses to generate
an input until the table it needs is installed.

Goldilocks runs its models on the CPU, but on Linux pip installs PyTorch's
CUDA build. Add `--extra-index-url https://download.pytorch.org/whl/cpu` to
`pip install` for the much smaller CPU-only build. Only mMACE can use a GPU,
when `GOLDILOCKS_MMACE_DEVICE=cuda` (see [mMACE setup](docs/mmace-setup.md)).

### From source

To work on Goldilocks itself, install
[uv](https://docs.astral.sh/uv/getting-started/installation/) and, for the
Workbench, Node.js 24 or newer. Then run:

```bash
git clone https://github.com/stfc/goldilocks-core.git
cd goldilocks-core
uv sync --extra http
npm --prefix web ci
uv run goldilocks assets install all
uv run --extra http poe workbench
```

Open **http://127.0.0.1:5173** for the development servers, or run
`uv run --extra http poe stage` for the built frontend on
**http://127.0.0.1:8000**. The [Workbench guide](web/README.md) covers the
development checks.

## Try it from the command line

Generate inputs for the bundled silicon structure (prefix each command with
`uv run` in a clone):

```bash
goldilocks run "$(goldilocks examples path)/Si.cif" --out si-run
```

`si-run/` holds `scf.in`, the pseudopotential and its table's licence, a
submission script, `goldilocks.json` (every setting with what decided it),
`CITATIONS.md` and a `README.md` on running the bundle on a cluster. Treat the
recommended settings as a starting point: review the warnings and check
convergence for your calculation. The [quickstart](docs/quickstart.md)
explains each file and how to run it.

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
