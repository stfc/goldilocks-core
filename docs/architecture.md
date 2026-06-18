# Architecture

`goldilocks-core` is the Core package for DFT input recommendation and input generation.

Core owns the deterministic recommendation path: load a structure, analyze it, advise parameters, resolve k-points, select pseudopotentials and cutoffs, generate target-code inputs, and optionally write a portable bundle.

Core does not own Runner/AiiDA workflows, schedulers, frontend/workspace state, auth, sessions, WebSockets, pods, structure database search, completed-output analysis, or HTTP backend registries.

## Principles

- Keep one canonical API. Do not add compatibility shims unless explicitly requested.
- Keep the graph fixed and inspectable: `Load → Analyze → Advise → Kmesh → Select → Generate → Bundle`.
- Keep `CoreJobRequest` data-only and serializable.
- Keep executable backend choice in `Pipeline`, not in request data.
- Prefer composition over inheritance. Backends are plain functions.
- Keep CLIs thin: parse arguments, build request/pipeline objects, call Core.
- Keep future HTTP handlers thin: map JSON to `CoreJobRequest`, resolve service-level backend names outside Core, call Core.
- Keep generators mechanical. Scientific defaults belong in advice, Kmesh, or selection.
- Keep tests portable. Do not require `local_data/` or private pseudo libraries.

## Package layout

```text
src/goldilocks_core/
├── contracts.py
├── jobs.py
├── analysis.py
├── advice.py
├── kmesh.py
├── selection.py
├── generation.py
├── bundle.py
├── advisors/
├── cli/
├── io/
├── ml/
└── pseudo/
```

Responsibilities:

| Module | Owns |
| --- | --- |
| `contracts.py` | Public records, type aliases, stage callable contracts, JSON-safe serialization. |
| `jobs.py` | `Pipeline` composition, `run_core_job()`, and the `recommend`/`generate`/`write_bundle` entry points. |
| `analysis.py` | Structure facts only. No recommendations. |
| `advice.py` | Provenance-backed scientific and numerical advice. |
| `kmesh.py` | Concrete k-point grid resolution from advice or hints. |
| `selection.py` | Pseudopotential selection, cutoff extraction, selection warnings. |
| `generation.py` | Target-code input text from completed records. |
| `bundle.py` | Bundle directory output and manifest writing. |
| `advisors/` | Model-backed stage backend factories. |
| `cli/` | Thin command-line wrappers. |
| `io/` | Structure loading only. |
| `ml/` | Feature extraction, model loading, prediction helpers. |
| `pseudo/` | UPF parsing, metadata registry, filtering, policies. |

## Dependency direction

`contracts.py` defines boundary records and callable signatures. Stage modules import contracts; contracts do not import stage modules.

`jobs.py` composes stage implementations through `Pipeline`. `Pipeline` is a frozen
dataclass whose fields default to the built-in backends, so the default
composition is `Pipeline()` and a single-stage swap is
`Pipeline(kmesh=ml_kmesh_advisor(spec))`. `contracts.py` defines boundary
records and callable signatures; stage modules import contracts, and
contracts does not import stage modules. `Pipeline` lives in `jobs.py`
(behavior with behavior) to avoid a circular import between `contracts` and
the stage modules.

The `recommend`/`generate`/`write_bundle` entry points in `jobs.py` are thin
wrappers around the same job runner. They do not carry a second
implementation of the recommendation logic.

## Fixed graph

The full graph is:

```text
Load → Analyze → Advise → Kmesh → Select → Generate → Bundle
```

Mode controls how far the graph runs:

```text
recommend -> Load → Analyze → Advise → Kmesh → Select
generate  -> Load → Analyze → Advise → Kmesh → Select → Generate
bundle    -> Load → Analyze → Advise → Kmesh → Select → Generate → Bundle
```

The graph is not a DAG engine and has no scheduler. Each computational stage behind the graph is injectable through `Pipeline`.

Detailed behavior lives in the stage docs:

- [Analyze](stages/analyze.md)
- [Advise](stages/advise.md)
- [Kmesh](stages/kmesh.md)
- [Select](stages/select.md)
- [Generate](stages/generate.md)
- [Bundle](stages/bundle.md)

## Request versus Pipeline

`CoreJobRequest` is serializable job data:

```python
CoreJobRequest(
    structure="Si.cif",
    intent=CalculationIntent(functional="PBE"),
    hints=CalculationHints(k_spacing=0.2),
    pseudo_metadata=tuple(metadata),
    mode="recommend",
)
```

`Pipeline` is executable composition:

```python
from goldilocks_core import Pipeline

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
result = run_core_job(request, pipeline=pipeline)
```

The separation means:

- requests can cross JSON and HTTP boundaries;
- pipelines can carry Python callables;
- Core does not need string-based backend registries;
- provenance still records whether a value came from a default, analysis, user hint, lookup, model, or fallback.

## Stage ownership summary

| Stage | Owner | Output | Rule |
| --- | --- | --- | --- |
| Load | `io/structures.py` | `Structure` | I/O only. |
| Analyze | `analysis.py` | `StructureAnalysisRecord` | Facts only. |
| Advise | `advice.py` | `ParameterAdvice` | Intent and provenance, not final syntax. |
| Kmesh | `kmesh.py`, `advisors/` | `KPointSelection` | Operator k-point hints win. |
| Select | `selection.py` | `SelectionRecord` | Pseudos and cutoffs; no k-point recalculation. |
| Generate | `generation.py` | `tuple[GeneratedFile, ...]` | Mechanical target-code translation. |
| Bundle | `bundle.py` | `BundleRecord` and files | Deterministic, path-safe directory output. |

## Extension points

Replace a `Pipeline` field at construction to change one stage backend:

```python
from goldilocks_core import Pipeline

pipeline = Pipeline(generate=my_generator)
```

Current fields:

```python
Pipeline(
    analyze=...,
    advise=...,
    kmesh=...,
    select=...,
    generate=...,
    bundle=...,
)
```

See [pipeline](pipeline.md) and [backends](backends.md) for signatures and examples.

## External surfaces

The Python API and CLI both call `run_core_job()`.

A future HTTP API should do the same: deserialize request JSON into `CoreJobRequest`, resolve any service-level backend choices outside Core, call `run_core_job()`, and serialize `CoreResult.to_dict()` (echoing the request in the response envelope if desired). HTTP concerns such as auth, uploads, workspaces, and response transport stay outside Core.
