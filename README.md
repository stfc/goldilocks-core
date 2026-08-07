# goldilocks-core

`goldilocks-core` recommends DFT parameters and generates Quantum ESPRESSO SCF inputs from crystal structures, calculation intent, operator hints, and pseudopotential metadata.

It provides:

- structure analysis and scientific warnings;
- advice for k-points, smearing, magnetism, SOC, convergence, vdW, and pseudopotentials;
- a default Quantile Random Forest k-point model;
- deterministic pseudopotential selection and QE input generation;
- Python and CLI entry points over the same staged pipeline.

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

```python
from goldilocks_core import CalculationHints, generate
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

result = generate(
    "path/to/structure.cif",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_metadata=load_pseudo_metadata("path/to/pseudopotentials"),
)

for generated_file in result.generated_files:
    print(generated_file.path)
    print(generated_file.content)

print(result.warnings)
```

The public workflows are:

- `recommend(...)` — return analysis, advice, and concrete selections;
- `generate(...)` — also return generated QE input files;
- `write_bundle(...)` — write generated files and `manifest.json` to a new directory.

Use `CoreJobRequest` with `run_core_job()` when you need a single request model. `run_core_job` dispatches `intent.task` to a path function (the built-in SCF path is `run_scf`).

The default k-point backend loads the configured QRF model lazily. Model errors are reported directly. Explicit `k_grid` and `k_spacing` hints bypass model loading; use `--model` (or `CoreJobRequest.kmesh_model`) to select a local k-index model instead.

See the [tutorial](docs/tutorial.md) and [pipeline reference](docs/pipeline.md) for complete examples.

## CLI

```bash
uv run goldilocks-core recommend structure.cif --json
uv run goldilocks-core generate structure.cif \
    --pseudo-root path/to/pseudos --k-grid 4 4 4 --json
uv run goldilocks-core bundle structure.cif \
    --pseudo-root path/to/pseudos --k-grid 4 4 4 --out run/ --json
```

Bundle output requires a new destination directory. See the [CLI reference](docs/cli.md) for all controls.

Example structures are installed with the package, so there is something to run straight away:

```bash
uv run goldilocks-core recommend "$(uv run goldilocks-core examples path)/Si.cif" --json
```

The standalone model-oriented entry point remains available:

```bash
uv run goldilocks-kmesh structure.cif --model path/to/model.joblib
```

## Documentation

- [Tutorial](docs/tutorial.md)
- [Pipeline and stage behavior](docs/pipeline.md)
- [Scientific conventions](docs/conventions.md)
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

Documentation under `docs/` and the example structures under `examples/` are
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Bundled and user-supplied pseudopotentials carry their own upstream licences —
see [docs/pseudopotentials.md](docs/pseudopotentials.md).
