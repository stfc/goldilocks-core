# goldilocks-core

Goldilocks turns a crystal structure into a ready-to-run Quantum ESPRESSO SCF
calculation. It recommends the parameters you would otherwise pick by hand —
k-point grid, smearing, convergence settings, pseudopotentials — records where
every choice came from, and publishes runnable inputs together with the exact
pseudopotential files and licences they depend on.

- structure analysis with scientific warnings;
- advice for k-points, smearing, magnetism, spin-orbit coupling, convergence,
  and dispersion, each carrying provenance;
- a default quantile-random-forest k-point model and a metallicity classifier;
- deterministic pseudopotential selection and Quantum ESPRESSO input
  generation;
- Python, CLI, HTTP, and local stdio MCP entry points over one service;
- the Goldilocks Workbench, a browser interface for the same operations.

## Install

This project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Sixty seconds to a runnable calculation

Install the default runtime assets once — two models and a PseudoDojo
pseudopotential table:

```bash
uv run goldilocks assets install default
uv run goldilocks assets verify default
```

Run a bundled example structure:

```bash
uv run goldilocks compute "$(uv run goldilocks examples path)/Si.cif" --preset generate --out run
```

`run/` now holds everything needed to execute the calculation:

```text
run/
inputs/qe.in                 the generated SCF input
pseudo/Si.upf                the exact pseudopotential selected
structure/canonical.cif      the normalized structure
source/Si.cif                the file you gave it
licences/  CITATIONS.md  goldilocks.json  checksums.sha256
```

The generated input (abridged) already reflects the recommendations:

```text
&SYSTEM
  ibrav = 0
  nat = 8
  ecutwfc = 48        from the PseudoDojo table
  ecutrho = 192
  occupations = 'smearing'
  smearing = 'cold'   the metallicity model classified Si as metallic
  degauss = 0.01
/
```

Every recommendation carries provenance naming its source — model, lookup, or
your own hint. [How recommendations are made](docs/science.md) explains each
choice and how to override it.

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
`RecordSelection` instead of `PresetSelection` to request specific records.
Pass `ArchiveOutput`, `DirectoryOutput`, or `None` to select archive,
directory, or memory-only output. The top-level `compute()` convenience uses
the same contracts.

See the [tutorial](docs/tutorial.md) for a guided Python walkthrough.

## CLI

```bash
uv run goldilocks capabilities --json
uv run goldilocks inspect structure.cif --json
uv run goldilocks compute structure.cif --preset recommend --no-out --json
uv run goldilocks compute structure.cif --preset generate --out run
```

Without an explicit pseudopotential source, the core chooses a compatible
registered table. Use `--pseudo-table` or `--pseudo-root` to override that
choice. The [CLI reference](docs/cli.md) lists every flag.

## Serving the Workbench

The HTTP process can serve the built browser interface after the Core routes:

```bash
uv sync --all-extras
uv run goldilocks serve http --host 127.0.0.1 --port 8000 --static-root web/dist
```

Or run the production image, which compiles the Workbench and installs the
complete asset profile:

```bash
docker build --tag goldilocks-workbench .
docker run --rm --publish 8000:8000 goldilocks-workbench
```

The server stores nothing between requests — no sessions, results, archives,
or run history.

## Transports and trust boundary

Python and the CLI are trusted local tools: they accept filesystem paths,
local pseudopotential roots, and publication destinations. HTTP and MCP are
untrusted boundaries: they accept inline structure content and registered
pseudopotential table IDs only — never paths, metadata payloads, model
locations, or publication destinations. The
[CLI reference](docs/cli.md#optional-transports) states the exact contract.

## Documentation

- [Quickstart](docs/quickstart.md) — from CIF to runnable inputs with real
  output at every step
- [Tutorial](docs/tutorial.md) — the Python API, guided
- [How recommendations are made](docs/science.md) — models, defaults, and
  provenance
- [CLI reference](docs/cli.md)
- [Scientific conventions](docs/conventions.md) — units, defaults, and
  physical policy
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

Code is licensed under the [BSD 3-Clause License](LICENSE).

Documentation under `docs/` and the example structures under
`src/goldilocks_core/examples/structures/` are licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Pseudopotential files are downloaded only by explicit asset installation and
retain their upstream licences; they are not bundled in the wheel or source
archive. See [Pseudopotential tables](docs/pseudopotentials.md).