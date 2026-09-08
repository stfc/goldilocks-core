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
from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    DirectoryOutput,
    PathStructureSource,
    PresetSelection,
    Service,
)

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
Pass `DirectoryOutput(path)` with a complete `generate` selection to write a
generated-input bundle, or `None` for memory-only output. The top-level
`compute()` convenience uses the same Compute contract.

See the [tutorial](docs/tutorial.md) and
[pipeline reference](docs/pipeline.md) for complete examples.

## CLI and transports

Install the default runtime assets once:

```bash
uv run goldilocks assets install default
uv run goldilocks assets verify default
uv run goldilocks assets install pseudodojo-pbesol-efficiency-sr
```
Query Records or run a recommendation or generation command. Without an explicit
pseudopotential source, Core chooses a compatible registered table. Use
`--pseudo-table` or `--pseudo-root` to override that choice:

```bash
uv run goldilocks recommend structure.cif --k-grid 4 4 4 --json
uv run goldilocks compute structure.cif --outputs analysis,k_points --k-grid 4 4 4
uv run goldilocks generate structure.cif --pseudo-table sssp-pbesol-efficiency-sr --out run --json
```

The default asset store is `$XDG_DATA_HOME/goldilocks/assets`, or
`~/.local/share/goldilocks/assets` when `XDG_DATA_HOME` is not set. Set
`GOLDILOCKS_ASSET_ROOT` to use a different location. See the
[CLI reference](docs/cli.md) for all controls.

Example structures are installed with the package:

```bash
uv run goldilocks compute "$(uv run goldilocks examples path)/Si.cif" --outputs analysis
```

HTTP and MCP are optional:

```bash
uv sync --all-extras
uv run goldilocks serve http --host 127.0.0.1 --port 8000
uv run goldilocks serve mcp
```

HTTP publishes `/recommend`, `/generate`, `/compute`, `/tasks`, `/codes`,
`/models`, and `/health`. MCP exposes `recommend`, `generate`, `compute`,
`list_tasks`, `list_codes`, and `list_models` as local stdio tools.

Both transports accept flat requests containing inline structure content,
intent, and hints. They resolve pseudopotentials and models on the server,
return JSON, and never create output directories. Python and CLI retain
trusted local filesystem controls.

## Generated-input bundles

`DirectoryOutput(path)` writes generated inputs and `manifest.json` into a new
directory. For Quantum ESPRESSO the generated input is `qe.in`.

The bundle does not copy pseudopotentials or run calculations. Supply the
selected UPFs under the input's `pseudo_dir` before running Quantum ESPRESSO.

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
