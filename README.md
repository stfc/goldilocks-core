# goldilocks-core

`goldilocks-core` recommends and generates DFT calculation inputs from crystal structures, calculation intent, operator hints, and pseudopotential metadata.

The public API is Python-first. The staged CLI calls the same internal job runner. Core does not own Runner/AiiDA workflows, frontend state, auth, scheduling, structure database search, or completed-output analysis.

## What is implemented

- Structure loading from `pymatgen.Structure` or files readable by pymatgen.
- Structure analysis facts: formula, elements, symmetry, heavy elements, magnetic candidates, conservative electronic character, and disorder warnings.
- Provenance-backed advice for k-points, smearing, magnetism, SOC, pseudopotential intent, and convergence.
- Kmesh-stage resolution of concrete k-point grids, including an ML-backed backend.
- Deterministic pseudopotential ranking and cutoff extraction from provided metadata.
- Quantum ESPRESSO SCF input generation.
- Bundle directory output with `manifest.json`.
- JSON-safe `CoreJobRequest`, `CoreResult`, and `CoreResult` records.

## Install

```bash
uv sync
```

For development:

```bash
uv sync --group dev
```

## Quick start: Python recommendation

```python
from goldilocks_core import CalculationHints, CalculationIntent, recommend
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

pseudo_metadata = load_pseudo_metadata("path/to/pseudopotentials")

result = recommend(
    "path/to/structure.cif",
    intent=CalculationIntent(functional="PBE"),
    hints=CalculationHints(k_spacing=0.2, pseudo_type="NC"),
    pseudo_metadata=pseudo_metadata,
)

print(result.analysis.reduced_formula)
print(result.selection.k_points.grid)
print(result.to_dict())
```

See [tutorial](docs/tutorial.md), [pipeline](docs/pipeline.md), and [contract reference](docs/contracts.md) for the full API.

## Quick start: generate files

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
```

## Quick start: write a bundle

```python
from goldilocks_core import CalculationHints, write_bundle
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

result = write_bundle(
    "path/to/structure.cif",
    "run/",
    hints=CalculationHints(k_grid=(4, 4, 4), pseudo_type="NC"),
    pseudo_metadata=load_pseudo_metadata("path/to/pseudopotentials"),
)

print(result.bundle.path)
print(result.manifest)
```

Bundle layout:

```text
run/
├── manifest.json
└── inputs/
    └── qe.in
```

See [bundle stage](docs/stages/bundle.md) and [manifest](docs/manifest.md).

## Job runner

Use `CoreJobRequest` and `run_core_job()` when a caller needs one request/result model for Python, CLI, or a future HTTP wrapper.

```python
from goldilocks_core import CoreJobRequest, run_core_job
from goldilocks_core.contracts import CalculationHints

result = run_core_job(
    CoreJobRequest(
        structure="path/to/structure.cif",
        hints=CalculationHints(k_spacing=0.2),
        mode="recommend",
    )
)

print(result.to_dict())
```

Modes:

```text
recommend -> Load → Analyze → Advise → Kmesh → Select
generate  -> Load → Analyze → Advise → Kmesh → Select → Generate
bundle    -> Load → Analyze → Advise → Kmesh → Select → Generate → Bundle
```

## Custom backends

`Pipeline` holds Python callables for stage backends. `CoreJobRequest` remains data-only.

```python

from goldilocks_core import Pipeline, recommend
from goldilocks_core.advisors import ml_kmesh_advisor
from goldilocks_core.contracts import ModelSpec

spec = ModelSpec(
    name="local-kmesh-model",
    version="v0",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="path/to/model.joblib",
)

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
result = recommend("path/to/structure.cif", pipeline=pipeline)
```

See [backends](docs/backends.md) for backend contracts and examples.

## CLI

```bash
uv run goldilocks-core recommend path/to/structure.cif --json
uv run goldilocks-core recommend path/to/structure.cif --model path/to/model.joblib --json
uv run goldilocks-core generate path/to/structure.cif --pseudo-root path/to/pseudos --k-grid 4 4 4 --json
uv run goldilocks-core bundle path/to/structure.cif --pseudo-root path/to/pseudos --k-grid 4 4 4 --out run/ --json
```

The legacy kmesh-focused entry point is still available:

```bash
uv run goldilocks-kmesh path/to/structure.cif --model path/to/model.joblib
```

See [CLI reference](docs/cli.md).

## Package layout

```text
src/goldilocks_core/
├── contracts.py   # public records, type aliases, serialization
├── jobs.py        # fixed job runner and default Pipeline composition
├── pipeline.py    # ergonomic Python API and stage wrappers
├── analysis.py    # structure facts
├── advice.py      # provenance-backed parameter advice
├── kmesh.py       # k-point grid resolution
├── selection.py   # pseudos, cutoffs, concrete selections
├── generation.py  # target-code input text
├── bundle.py      # bundle directory and manifest writing
├── advisors/      # model-backed stage backends
├── cli/           # thin command wrappers
├── io/            # loading only
├── ml/            # feature extraction, model loading, prediction
└── pseudo/        # UPF parsing, registry, filtering, policy
```

See [architecture](docs/architecture.md) for boundaries and dependency direction.

## Documentation

- [Architecture](docs/architecture.md)
- [Pipeline](docs/pipeline.md)
- [Backends](docs/backends.md)
- [Contracts](docs/contracts.md)
- [Serialization](docs/serialization.md)
- [Manifest](docs/manifest.md)
- [Conventions](docs/conventions.md)
- [Provenance](docs/provenance.md)
- [CLI](docs/cli.md)
- [Tutorial](docs/tutorial.md)
- [Extension guide](docs/extension.md)
- [Migration guide](docs/migration.md)
- [Design decisions](docs/decisions.md)
- [Changelog](docs/changelog.md)

## Development

```bash
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv run pre-commit run --all-files
```

Committed tests must not depend on `local_data/`, private pseudopotential libraries, notebooks, or machine-specific paths. Use synthetic structures, temporary files, small UPF snippets, constructed dataclasses, and fake models.
