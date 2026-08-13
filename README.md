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

`CoreService` is the reusable application interface. It owns model state,
serializes access to that state, and exposes preset runs, record queries, and
discovery:

```python
from goldilocks_core import CalculationHints, CoreService, PresetRequest
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

request = PresetRequest(
    structure="path/to/structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_metadata=tuple(load_pseudo_metadata("path/to/pseudopotentials")),
)

with CoreService() as core:
    result = core.generate(request)

for generated_file in result.generated_files:
    print(generated_file.path)
    print(generated_file.content)
```

The public operations are:

- `CoreService.recommend(PresetRequest(...))` — return the complete
  recommendation record set;
- `CoreService.generate(PresetRequest(...), output_dir=...)` — also generate
  inputs and optionally publish a manifest-backed directory;
- `CoreService.compute(QueryRequest(...))` — return only selected record types;
- `describe_tasks()`, `describe_codes()`, and `describe_models()` — discover
  backend capabilities.

`run_core_job(PresetRequest(...))` and `query_records(QueryRequest(...))` are
one-call conveniences. Use `CoreService` for repeated work so model resources
are reused. Explicit `k_grid` and `k_spacing` hints bypass model loading;
`PresetRequest.kmesh_model` and `QueryRequest.kmesh_model` select a local
k-index model instead of the configured QRF default.

See the [tutorial](docs/tutorial.md) and
[pipeline reference](docs/pipeline.md) for complete examples.

## CLI and transports

Install the exact default runtime profile once, then run offline:

```bash
uv run goldilocks assets install default
uv run goldilocks assets verify default
uv run goldilocks recommend structure.cif --json
uv run goldilocks generate structure.cif \
    --pseudo-root path/to/pseudos --k-grid 4 4 4 --out run/ --json
uv run goldilocks compute structure.cif \
    --outputs analysis,k_points --k-grid 4 4 4
```

`GOLDILOCKS_ASSET_ROOT` overrides the default
`$XDG_DATA_HOME/goldilocks/assets` store. Normal commands never download.
Pass `--fetch-missing` to explicitly install the complete default profile
before one command. Bundle output requires a new destination directory. See
the [CLI reference](docs/cli.md) for all controls.

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
