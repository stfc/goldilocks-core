# goldilocks-core

`goldilocks-core` recommends DFT parameters and generates Quantum ESPRESSO SCF inputs from crystal structures, calculation intent, operator hints, and pseudopotential metadata.

It provides:

- structure analysis and scientific warnings;
- advice for k-points, smearing, magnetism, SOC, convergence, vdW, and pseudopotentials;
- a default Quantile Random Forest k-point model;
- deterministic pseudopotential selection and QE input generation;
- Python, CLI, HTTP, and MCP entry points over one process-owned service.

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

`CoreService` is the main Python interface. Use `recommend()` to inspect a
complete recommendation, `generate()` to create input files, and `compute()` to
request selected records.

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest

request = PresetRequest(
    structure="path/to/structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_table="pseudodojo-pbesol-efficiency-sr",
)

with CoreService() as core:
    result = core.generate(request)

for generated_file in result.generated_files:
    print(generated_file.path)
    print(generated_file.content)
```

The public operations are:

- `CoreService.recommend(PresetRequest(...))` returns a complete recommendation.
- `CoreService.generate(PresetRequest(...), output_dir=...)` also creates input
  files and can write them to a new directory.
- `CoreService.compute(QueryRequest(...))` returns only the requested records.

`recommend` and `generate` also exist as CLI commands and as HTTP and MCP
operations. They are not top-level Python functions. For a single Python call,
use `run_core_job(PresetRequest(...))`.

See the [tutorial](docs/tutorial.md) and
[pipeline reference](docs/pipeline.md) for complete examples.

## CLI and transports

Install the default runtime assets once:

```bash
uv run goldilocks assets install default
uv run goldilocks assets verify default
```

Run a recommendation or create input files. Requests use the installed default
pseudopotential table unless `--pseudo-table` or `--pseudo-root` selects another
source:

```bash
uv run goldilocks recommend structure.cif --json
uv run goldilocks generate structure.cif --pseudo-table sssp-pbesol-efficiency-sr --out run/ --json
uv run goldilocks compute structure.cif --outputs analysis,k_points --k-grid 4 4 4
```

The default asset store is `$XDG_DATA_HOME/goldilocks/assets`, or
`~/.local/share/goldilocks/assets` when `XDG_DATA_HOME` is not set. Set
`GOLDILOCKS_ASSET_ROOT` to use a different location. See the
[CLI reference](docs/cli.md) for all controls.

Example structures are installed with the package:

```bash
uv run goldilocks recommend "$(uv run goldilocks examples path)/Si.cif" --json
```

HTTP and MCP are optional:

```bash
uv sync --all-extras
uv run goldilocks serve http --host 127.0.0.1 --port 8000
uv run goldilocks serve mcp
```

HTTP publishes `/recommend`, `/generate`, `/compute`, `/tasks`, `/codes`,
`/models`, and `/health`. MCP publishes the same three operations and three
discovery calls as tools over stdio.

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
