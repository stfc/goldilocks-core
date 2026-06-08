# goldilocks-core

`goldilocks-core` recommends DFT calculation inputs from crystal structures, optional user hints, model output, and pseudopotential metadata.

The current public API is Python-first. The full staged pipeline is available in Python. The CLI currently exposes the ML-backed k-mesh path only.

## Current scope

Implemented:

- structure loading from `pymatgen.Structure` or structure files readable by pymatgen
- structure analysis facts: formula, elements, heavy elements, magnetic candidates, disorder warnings
- provenance-backed advice for k-points, smearing, magnetism, SOC, pseudopotential intent, and convergence
- selection of concrete k-point grids
- deterministic pseudopotential selection from provided metadata
- UPF parsing and local pseudopotential registry loading
- ML-backed k-index to k-grid selection
- JSON-safe recommendation manifests

Not implemented yet:

- code-specific input file generation
- portable output bundle directories
- full staged CLI
- Runner, AiiDA, scheduling, web app, auth, or workspace concerns

## Pipeline

```mermaid
flowchart LR
    structure["Structure input"] --> load["Load"]
    load --> analyze["Analyze"]
    analyze --> advise["Advise"]
    advise --> select["Select"]
    select --> result["CoreRecommendation"]

    intent["CalculationIntent"] -.-> advise
    hints["CalculationHints"] -.-> advise
    metadata["PseudoMetadata list"] -.-> select
```

Stage boundaries:

- **Load**: parse structure input. No decisions.
- **Analyze**: report structure facts. No recommendations.
- **Advise**: choose scientific and numerical intent. Record provenance.
- **Select**: resolve concrete grids, pseudopotentials, cutoffs, and warnings.
- **Generate**: not implemented yet. Future generators must only translate existing advice and selection records.
- **Bundle**: currently `CoreRecommendation.to_dict()`. Directory output is not implemented yet.

## Install

```bash
uv sync
```

For development:

```bash
uv sync --group dev
```

## Python API

### Full recommendation

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
print(result.advice.spin_orbit.consider)
print(result.selection.k_points.grid)
print(result.selection.pseudopotentials)
print(result.to_dict())
```

### Stage-by-stage use

Use this when notebooks, scripts, or agents need to inspect or override intermediate records.

```python
from goldilocks_core import CalculationHints
from goldilocks_core.pipeline import analyze, advise, load, select
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

structure = load("path/to/structure.cif")
analysis = analyze(structure)

advice = advise(
    analysis,
    hints=CalculationHints(k_grid=(4, 4, 4)),
)

pseudo_metadata = load_pseudo_metadata("path/to/pseudopotentials")
selection = select(structure, advice, pseudo_metadata)

print(analysis.elements)
print(advice.k_points.provenance)
print(selection.k_points.grid)
```

Stage outputs:

```text
load(...)      -> pymatgen.core.Structure
analyze(...)   -> StructureAnalysisRecord
advise(...)    -> ParameterAdvice
select(...)    -> SelectionRecord
recommend(...) -> CoreRecommendation
```

### K-mesh ML advisor

```python
from goldilocks_core.advisors import advise_kpoints
from goldilocks_core.contracts import ModelSpec
from goldilocks_core.io.structures import load_structure

structure = load_structure("path/to/structure.cif")

spec = ModelSpec(
    name="local-kmesh-model",
    version="v0",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="path/to/model.joblib",
)

selection = advise_kpoints(structure, spec)
print(selection.grid)
print(selection.provenance)
```

### Pseudopotentials

```python
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata
from goldilocks_core.pseudo.pp_registry import filter_by_element, load_pseudo_metadata

metadata = parse_upf_metadata("path/to/Si.UPF")
print(metadata.element)
print(metadata.functional)

metadata_list = load_pseudo_metadata("path/to/pseudopotentials")
si_metadata = filter_by_element(metadata_list, "Si")
print(len(si_metadata))
```

## Result shape

```text
CoreRecommendation
├── intent: CalculationIntent
├── analysis: StructureAnalysisRecord
├── advice: ParameterAdvice
├── selection: SelectionRecord
├── generated_files: tuple[GeneratedFile, ...]
└── warnings: tuple[str, ...]
```

Nested records are dataclasses with `to_dict()` methods. Tuples and paths are converted to JSON-safe values.

## CLI

The current CLI is only for ML-backed k-mesh selection.

```bash
uv run goldilocks-kmesh path/to/structure.cif --model path/to/model.joblib
```

Output:

```text
recommended mesh: (n1, n2, n3)
```

CLI flow:

```mermaid
flowchart LR
    args["CLI args"] --> structure["Load structure"]
    structure --> model["Load model"]
    model --> predict["Predict k-index"]
    predict --> select["Select k-grid"]
    select --> print["Print mesh"]
```

A full `goldilocks recommend` CLI is not implemented yet.

## Package layout

```text
src/goldilocks_core/
├── __init__.py
├── contracts.py
├── pipeline.py
├── analysis.py
├── advice.py
├── selection.py
├── kmesh.py
├── advisors/
├── cli/
├── io/
├── ml/
└── pseudo/
```

Responsibilities:

- `contracts.py`: public boundary dataclasses and JSON-safe serialization
- `pipeline.py`: Load → Analyze → Advise → Select orchestration
- `analysis.py`: structure facts only
- `advice.py`: provenance-backed recommendations
- `selection.py`: concrete grids, pseudopotentials, cutoffs, warnings
- `kmesh.py`: reciprocal-space mesh mechanics
- `advisors/`: model-backed recommendation paths
- `cli/`: thin command entry points
- `io/`: file and structure loading
- `ml/`: feature extraction, model loading, prediction
- `pseudo/`: UPF parsing, registry, filtering, policy

There is no compatibility layer for old import paths. Use one canonical API.

## Development

Run tests:

```bash
uv run pytest
```

Run lint and format checks:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

Run the full local gate:

```bash
uv run pre-commit run --all-files
```

## Test data rules

Committed tests must not depend on `local_data/`, private pseudopotential libraries, notebooks, or machine-specific paths.

Use:

- synthetic pymatgen structures
- temporary files under `tmp_path`
- small UPF snippets in tests
- constructed dataclass instances
- fake models with `.predict()`

Real pseudopotential libraries are useful for local exploration. Convert findings into portable tests before committing.
