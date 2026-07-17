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

Use `CoreJobRequest` with `run_core_job()` when you need a single request model. Use `Pipeline` to replace a stage backend.

The default k-point backend loads the configured QRF model lazily. Model errors are reported directly; use `--heuristic-kpoints` to select the model-free backend explicitly. Explicit `k_grid` and `k_spacing` hints bypass model loading.

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
