# goldilocks-core

`goldilocks-core` recommends DFT parameters and generates Quantum ESPRESSO SCF inputs from crystal structures, calculation intent, operator hints, and pseudopotential metadata.

It provides:

- structure analysis and scientific warnings;
- advice for k-points, smearing, magnetism, SOC, convergence, vdW, and pseudopotentials;
- a default Quantile Random Forest k-point model;
- deterministic pseudopotential selection and QE input generation;
- Python, CLI, HTTP, and local stdio MCP entry points over one process-owned
  service.

## Install

This project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

For development dependencies:

```bash
uv sync --group dev
```

## Python API

`Service` is the reusable Python interface. It exposes Capabilities, Structure
Inspection, and Compute. `recommend` and `generate` are preset IDs, not
operations.

```python
from goldilocks_core.calculation import CalculationHints
from goldilocks_core.io.structures import PathStructureSource
from goldilocks_core.publication import DirectoryOutput
from goldilocks_core.request import CalculationDraft, ComputeRequest, PresetSelection
from goldilocks_core.runtime.service import Service

request = ComputeRequest(
    draft=CalculationDraft(
        structure=PathStructureSource("path/to/structure.cif"),
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

Use `RecordSelection` instead of `PresetSelection` to request specific Records.
Pass `ArchiveOutput`, `DirectoryOutput`, or `None` to select archive, directory,
or memory-only output. The top-level `compute()` convenience uses the same
Compute contract.

See the [tutorial](docs/tutorial.md) and
[pipeline reference](docs/pipeline.md) for complete examples.

## CLI and transports

Install the default runtime assets once:

```bash
uv run goldilocks assets install default
uv run goldilocks assets verify default
```
Inspect a structure, query Records, or run a named Preset. Without an explicit
pseudopotential source, Core chooses a compatible registered table. Use
`--pseudo-table` or `--pseudo-root` to override that choice:

```bash
uv run goldilocks capabilities --json
uv run goldilocks inspect structure.cif --json
uv run goldilocks compute structure.cif --outputs analysis,k_points --no-out --json
uv run goldilocks compute structure.cif --preset generate --pseudo-table pseudodojo-pbesol-efficiency-sr --out run --json
```

The default asset store is `$XDG_DATA_HOME/goldilocks/assets`, or
`~/.local/share/goldilocks/assets` when `XDG_DATA_HOME` is not set. Set
`GOLDILOCKS_ASSET_ROOT` to use a different location. See the
[CLI reference](docs/cli.md) for all controls.

Example structures are installed with the package:

```bash
uv run goldilocks inspect "$(uv run goldilocks examples path)/Si.cif" --json
```

HTTP and MCP are optional:

```bash
uv sync --all-extras
uv run goldilocks serve http --host 127.0.0.1 --port 8000
uv run goldilocks serve mcp
```

HTTP publishes `/capabilities`, `/inspect`, `/compute`, `/health`, and `/ready`.
Compute returns one multipart response containing canonical Result JSON and,
when complete DFT Input Data was requested, its exact in-memory ZIP. It never
creates a server output directory. MCP publishes `capabilities`,
`inspect_structure`, and `compute` as local stdio tools.

HTTP and MCP accept inline structures and may select one registered
pseudopotential table by stable ID. They do not accept structure paths,
pseudopotential roots or metadata payloads, model locations, or publication
paths. Python and CLI retain trusted local path and publication controls.

## Ready-to-run Output

A Ready-to-run Output uses one directory/ZIP layout:

```text
source/  structure/  inputs/  pseudo/  licences/
CITATIONS.md  README.md  goldilocks.json
```

## Documentation

- [Tutorial](docs/tutorial.md)
- [Pipeline and stage behavior](docs/pipeline.md)
- [Scientific conventions](docs/conventions.md)
- [Pseudopotential tables, storage, and licensing](docs/pseudopotentials.md)
- [CLI reference](docs/cli.md)
- [Architecture and extension points](docs/architecture.md)

## Development

```bash
uv run pytest
uv run pytest -m integration
uv run pytest -m physics
uv run pytest --cov --cov-report=term-missing
uv run mutmut run --max-children 4
uv run ruff check src tests
uv run ruff format --check src tests
uv build --no-sources
uv run python scripts/validate_distribution.py dist
uv run pre-commit run --all-files
```

Tests use synthetic structures, temporary files, small UPF snippets, and fake models. They must not depend on private datasets or machine-specific paths.

## Licence

Code is licensed under the [BSD 3-Clause License](LICENSE).

Documentation under `docs/` and the example structures under
`src/goldilocks_core/examples/structures/` are licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Pseudopotential files are downloaded only by explicit asset installation and
retain their upstream licences; they are not bundled in the wheel or source
archive. See [Pseudopotential tables](docs/pseudopotentials.md).
