# goldilocks-core

`goldilocks-core` recommends inputs for DFT (density functional theory)
simulations of materials and generates Quantum ESPRESSO SCF input files from
crystal structures, calculation intent, operator hints, and pseudopotential
metadata.

It provides:

- structure analysis and scientific warnings;
- provenance-backed advice for k-points, smearing, magnetism, SOC, convergence,
  vdW, and pseudopotentials;
- a default Quantile Random Forest k-point model;
- deterministic pseudopotential selection and QE input generation;
- Python and CLI entry points over the same staged pipeline;
- optional HTTP and MCP server transports.

## Install

This project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

For development dependencies:

```bash
uv sync --group dev
```

The HTTP and MCP transports are optional extras:

```bash
uv sync --extra http --extra mcp
```

## Quick start

Example structures are installed with the package, so there is something to run
straight away:

```bash
uv run goldilocks-core recommend "$(uv run goldilocks-core examples path)/Si.cif" --json
```

Python API:

```python
from goldilocks_core import CalculationHints, generate, recommend
from goldilocks_core.examples import structure
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

# Recommendation only (analysis, advice, k-points, pseudopotential selection)
result = recommend(structure("Si.cif"))
print(result.k_points.grid)

# Generate QE SCF input files
result = generate(
    structure("Si.cif"),
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_metadata=load_pseudo_metadata("path/to/pseudopotentials"),
)
for generated_file in result.generated_files:
    print(generated_file.path, generated_file.content)
```

## Two API layers

**Pure stage functions** — import and compose stages directly:

```python
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.advice import advise_parameters
from goldilocks_core.kmesh import resolve_kpoints
from goldilocks_core.advisors import default_kmesh_advisor
from goldilocks_core.selection import select_parameters
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure

structure = load_structure("Fe.cif")
analysis = analyze_structure(structure)
advice = advise_parameters(analysis, intent, hints)
k_points = resolve_kpoints(structure, hints, default_kmesh_advisor())
selection = select_parameters(structure, advice, pseudo_metadata)
files = generate_inputs(structure, intent, advice, selection, k_points)
```

**`CoreRuntime`** — composed entrypoints owning model lifecycle. Every
transport (CLI, HTTP, MCP, library) delegates to it. Model resources load
lazily and are reused across jobs on the same instance; `reset()` discards
cached state and `close()` releases it. There is no module-global default
runtime.

```python
from goldilocks_core import CoreRuntime, CoreJobRequest, CalculationHints

with CoreRuntime() as runtime:
    a = runtime.recommend(CoreJobRequest(structure="Fe.cif"))
    b = runtime.recommend(CoreJobRequest(structure="Fe.cif", hints=CalculationHints(k_grid=(4, 4, 4))))
    # both calls share one loaded model backend
```

`run_core_job(request)` dispatches `intent.task` to a path function (the
built-in SCF path is `run_scf`) and creates a fresh `CoreRuntime` per call when
one is not supplied. `recommend(...)` and `generate(...)` build a
`CoreJobRequest` and call `run_core_job`.

The default k-point backend loads the configured QRF model lazily. Explicit
`k_grid` and `k_spacing` hints bypass model loading; use `--model` (or
`CoreJobRequest.kmesh_model`) to select a local k-index model instead.

## CLI

```bash
uv run goldilocks-core recommend structure.cif --json
uv run goldilocks-core generate structure.cif \
    --pseudo-root path/to/pseudos --k-grid 4 4 4 --json
uv run goldilocks-core generate structure.cif \
    --pseudo-root path/to/pseudos --k-grid 4 4 4 --out run/ --json
```

Raw stage subcommands run only their sub-graph: `analyze`, `advise`, `kmesh`,
`select`. `serve http` and `serve mcp` start the transport servers. See the
[CLI reference](docs/cli.md) for all controls.

The standalone model-oriented entry point remains available:

```bash
uv run goldilocks-kmesh structure.cif --model path/to/model.joblib
```

## Documentation

- [Tutorial](docs/tutorial.md) — from-scratch walkthrough.
- [Pipeline and stage behavior](docs/pipeline.md) — stage signatures and records.
- [Architecture and extension points](docs/architecture.md) — DAG, layers, modules.
- [Transports (HTTP, MCP)](docs/transport.md) — servers, endpoints, tools, errors.
- [Scientific conventions](docs/conventions.md) — units, defaults, policies.
- [CLI reference](docs/cli.md) — all subcommands and options.
- [Changelog](docs/changelog.md).

## Development

```bash
uv run pytest
uv run pytest -m integration
uv run pytest -m physics
uv run pytest --cov --cov-report=term-missing
uv run mutmut run --max-children 4
uv run pre-commit run --all-files
```

Tests use synthetic structures, temporary files, small UPF snippets, and fake
models. They must not depend on private datasets or machine-specific paths.

## Licence

Code is licensed under the [BSD 3-Clause License](LICENSE).

Documentation under `docs/` and the example structures under `examples/` are
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Bundled and user-supplied pseudopotentials carry their own upstream licences.