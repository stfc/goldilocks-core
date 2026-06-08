# goldilocks-core

`goldilocks-core` is a research-grade Python package for organizing and recommending DFT calculation inputs from structures, machine-learning models, and parsed pseudopotentials.

The project is designed around domain-focused modules such as k-mesh construction, pseudopotential parsing, recommendation advisors, and thin CLI entry points.

## What It Does

`goldilocks-core` currently focuses on three connected workflows:

- recommending k-mesh settings from structure-aware logic and ML-predicted `k_index`
- parsing UPF pseudopotential files and building local pseudopotential registries
- running an explicit staged recommendation pipeline: Load → Analyze → Advise → Select

The package is growing toward code- and task-aware input recommendation, where structure, pseudopotential choice, and calculation settings can be coordinated in a clean and testable way. Generate and Bundle are represented by the structured manifest boundary first; code-specific file writers can then stay mechanical.

## Current Capabilities

### K-mesh stack

- generate candidate k-distance values from reciprocal lattice geometry
- interpret `k_distance` as a VASP-style `KSPACING` value in Å⁻¹
- convert k-distance values into Monkhorst-Pack-style meshes using solid-state reciprocal lengths with the `2π` factor
- build indexed `KMeshEntry` objects
- compute mesh-related metadata such as k-point density intervals and reduced-k-point counts
- map ML-predicted `k_index` values onto concrete k-mesh recommendations
- expose a minimal CLI entry point for k-mesh recommendation

### Pseudopotential stack

- parse UPF files into structured metadata
- support both attribute-style and text-style `PP_HEADER`
- supplement header parsing with `PP_INFO` when needed
- normalize key fields such as:
  - `element`
  - `pseudo_type`
  - `functional`
  - `relativistic`
  - `z_valence`
- scan a local pseudo library into a list of `PseudoMetadata`
- filter registry entries by element
- select one deterministic pseudopotential candidate per structure element when metadata is available

### Staged Core pipeline

- load structures through a pure I/O stage
- analyze structure facts without recommending parameters
- advise k-points, smearing, magnetism, SOC, pseudo intent, and convergence with provenance
- select concrete k-point grids, pseudopotentials, and cutoffs from advice
- bundle the structured result as a JSON-safe manifest for downstream tools

## Installation

This project uses `uv` for environment and dependency management.

Clone the repository and sync the environment:

```bash
uv sync
```

If you want development tools as well:

```bash
uv sync --group dev
```

## Quick Start

### Load a structure and get k-mesh advice

```python
from pathlib import Path

from goldilocks_core.advisors import advise_kpoints
from goldilocks_core.io.structures import load_structure
from goldilocks_core.contracts import ModelSpec

structure = load_structure("path/to/structure.cif")

spec = ModelSpec(
    name="local-kmesh-model",
    version="v0",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="path/to/model.joblib",
    revision=None,
)

advice = advise_kpoints(structure, spec)
print(advice.grid)
```

### Parse one UPF file

```python
from goldilocks_core.pseudo.parse_upf import parse_upf_metadata

metadata = parse_upf_metadata("path/to/pseudo.UPF")
print(metadata)
```

### Build a local pseudo registry

```python
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata, filter_by_element

metadata_list = load_pseudo_metadata("path/to/pseudopotentials")
si_pseudos = filter_by_element(metadata_list, "Si")

print(len(metadata_list))
print(len(si_pseudos))
```

### Run the staged recommendation pipeline

```python
from goldilocks_core import CalculationHints, recommend
from goldilocks_core.pseudo.pp_registry import load_pseudo_metadata

metadata_list = load_pseudo_metadata("path/to/pseudopotentials")
result = recommend(
    "path/to/structure.cif",
    hints=CalculationHints(k_spacing=0.2, pseudo_type="NC"),
    pseudo_metadata=metadata_list,
)

print(result.analysis.reduced_formula)
print(result.selection.k_points.grid)
print(result.to_dict())
```

## Python API

The current Python-facing entry points are:

### Staged recommendation

- `goldilocks_core.recommend`
- `goldilocks_core.bundle_recommendation`
- `goldilocks_core.CalculationIntent`
- `goldilocks_core.CalculationHints`

### K-mesh and advice

- `goldilocks_core.advisors.advise_kpoints`
- `goldilocks_core.kmesh`
- `goldilocks_core.io.structures.load_structure`

### Pseudopotentials

- `goldilocks_core.pseudo.parse_upf.parse_upf_metadata`
- `goldilocks_core.pseudo.pp_registry.load_pseudo_metadata`
- `goldilocks_core.pseudo.pp_registry.filter_by_element`

### Contracts

- `goldilocks_core.contracts`

This package is intended to be notebook-friendly, but the package modules and tests should remain the source of truth rather than notebook-only logic.

## CLI

A minimal k-mesh CLI entry point is available.

Show help:

```bash
uv run goldilocks-kmesh --help
```

Current usage pattern:

```bash
uv run goldilocks-kmesh path/to/structure.cif --model path/to/model.joblib
```

At this stage, the CLI is intentionally small and thin. The main logic lives in the Python package APIs.

## Project Structure

```text
src/goldilocks_core/
├── advisors/
├── analysis.py
├── advice.py
├── cli/
├── contracts.py
├── io/
├── kmesh.py
├── ml/
├── pipeline.py
├── pseudo/
└── selection.py
```

### High-level responsibilities

- `advisors/`
  Coordinates recommendation workflows and policy decisions.

- `analysis.py`, `advice.py`, `selection.py`, `pipeline.py`
  Implement the staged Core recommendation flow.

- `contracts.py`
  Contains JSON-serializable records for provenance, hints, analysis, advice, selection, and recommendations.

- `cli/`
  Exposes thin command-line entry points.

- `io/`
  Handles structure loading and normalization.

- `kmesh.py`
  Contains k-mesh construction and interval logic.

- `ml/`
  Contains feature extraction, model loading, and inference utilities.

- `pseudo/`
  Contains UPF parsing and local pseudopotential registry logic.

For a fuller explanation, see [docs/architecture.md](docs/architecture.md).

## Development

Run the test suite:

```bash
uv run pytest
```

Run formatting and checks:

```bash
uv run pre-commit run --all-files
```

A typical development loop is:

```bash
uv run pytest
uv run pre-commit run --all-files
```

## Testing Philosophy

The committed test suite must pass from a clean checkout with only the declared dependencies. Tests should not depend on `local_data/`, private pseudopotential libraries, notebooks, or machine-specific paths.

Use portable fixtures:

- synthetic pymatgen structures
- temporary files under `tmp_path`
- small UPF snippets written inside tests
- constructed dataclass instances for selector and policy tests

Local exploratory validation against real pseudopotential libraries is still useful, but once a behavior is understood it should be converted into a focused portable regression test.

## Current Status

This project is under active design and development.

The current codebase already has:

- a working ML-driven k-mesh recommendation path
- real UPF parsing across multiple pseudo-library styles
- a local pseudo registry foundation
- an evolving domain-oriented package structure

The next major steps are expected to include:

- keeping baseline tests green while expanding the staged pipeline
- adding mechanical code-specific generators that consume advice and selection records
- writing portable bundle directories once the manifest schema settles
- expanding pseudopotential selection logic based on structure, code, and task
- clearer user-facing workflows for local pseudo management
