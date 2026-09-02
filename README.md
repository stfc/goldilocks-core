# goldilocks-core

Goldilocks recommends DFT parameters for a crystal structure — k-point grid,
smearing, convergence settings, pseudopotentials — and generates ready-to-run
Quantum ESPRESSO SCF inputs. Every recommendation carries provenance naming
its source, and publication includes the exact pseudopotential files and
licences the inputs depend on.

- structure analysis with scientific warnings;
- provenance-backed advice for k-points, smearing, magnetism, spin-orbit
  coupling, convergence, and dispersion;
- a quantile-random-forest k-point model and a metallicity classifier;
- deterministic pseudopotential selection and input generation;
- Python, CLI, HTTP, and local stdio MCP transports over one service;
- the Goldilocks Workbench, a browser interface for the same operations.

## Install

This project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Run an example

Install the default runtime assets once — two models and a PseudoDojo
pseudopotential table:

```bash
uv run goldilocks assets install default
uv run goldilocks assets verify default
```

Generate SCF inputs for a bundled structure:

```bash
STRUCTURES="$(uv run goldilocks examples path)"
uv run goldilocks compute "$STRUCTURES/Si.cif" --preset generate --out run
```

`run/` holds the generated input, the exact selected pseudopotential,
structures, licences, citations, and checksums; run `pw.x` from its root.
The [quickstart](docs/quickstart.md) shows the full output and
[how recommendations are made](docs/science.md) explains where each value
came from.

## Python API

`Service` is the reusable Python interface with three operations:
`capabilities`, `inspect_structure`, and `compute`.

```python
from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    DirectoryOutput,
    PathStructureSource,
    PresetSelection,
    Service,
)
from goldilocks_core.examples.structures import structures_path

request = ComputeRequest(
    draft=CalculationDraft(
        structure=PathStructureSource(structures_path() / "Si.cif"),
        hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
        pseudo_table="pseudodojo-pbesol-efficiency-sr",
    ),
    selection=PresetSelection("generate"),
)

with Service() as core:
    capabilities = core.capabilities()
    inspection = core.inspect_structure(request.draft.structure)
    result = core.compute(request, output=DirectoryOutput("run"))
```

`recommend` and `generate` are preset IDs, not operations. Use
`RecordSelection` to request specific records, and `ArchiveOutput`,
`DirectoryOutput`, or `None` for archive, directory, or memory-only output.
The top-level `compute()` convenience uses the same contracts. See the
[tutorial](docs/tutorial.md) for a guided walkthrough.

## CLI

```bash
uv run goldilocks capabilities --json
uv run goldilocks inspect structure.cif --json
uv run goldilocks compute structure.cif --preset recommend --no-out --json
uv run goldilocks compute structure.cif --preset generate --out run
```

Without an explicit pseudopotential source, the core chooses a compatible
registered table; override with `--pseudo-table` or `--pseudo-root`. The
[CLI reference](docs/cli.md) lists every flag and states the transport trust
boundary.

## Serve the Workbench

```bash
uv sync --all-extras
uv run goldilocks serve http --host 127.0.0.1 --port 8000 --static-root web/dist
```

The production image compiles the Workbench and installs the complete asset
profile:

```bash
docker build --tag goldilocks-workbench .
docker run --rm --publish 8000:8000 goldilocks-workbench
```

The server stores nothing between requests.

## Documentation

- [Quickstart](docs/quickstart.md)
- [Tutorial](docs/tutorial.md)
- [How recommendations are made](docs/science.md)
- [CLI reference](docs/cli.md)
- [Scientific conventions](docs/conventions.md)
- [Pseudopotential tables, storage, and licensing](docs/pseudopotentials.md)
- [Architecture and extension points](docs/architecture.md)

## Development

```bash
uv run pytest
uv run pytest -m integration
uv run pytest -m physics
uv run pytest --cov --cov-report=term-missing
uv run mutmut run --max-children 4
cd web && npm ci && npm run check && cd ..
uv build --no-sources
uv run python scripts/validate_distribution.py dist
uv run pre-commit run --all-files
```

Tests use synthetic structures, temporary files, small UPF snippets, and fake
models. They must not depend on private datasets or machine-specific paths.

## Licence

Code is licensed under the [BSD 3-Clause License](LICENSE). Documentation
under `docs/` and the example structures are licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Pseudopotential
files are downloaded only by explicit asset installation and retain their
upstream licences; see [Pseudopotential tables](docs/pseudopotentials.md).