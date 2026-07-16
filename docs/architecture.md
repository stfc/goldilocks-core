# Architecture

`goldilocks-core` is the Core package for DFT input recommendation and input generation.

Core owns the deterministic recommendation path: load a structure, analyze it, advise parameters, resolve k-points, select pseudopotentials and cutoffs, generate target-code inputs, and optionally write a portable bundle.

Core does not own Runner/AiiDA workflows, schedulers, frontend/workspace state, auth, sessions, WebSockets, pods, structure database search, completed-output analysis, or HTTP backend registries.

## Principles

- Keep one canonical API. Do not add compatibility shims unless explicitly requested.
- Keep the graph fixed and inspectable: `Load → Analyze → Advise → Kmesh → Select → Generate → Bundle`.
- Keep `CoreJobRequest` data-only and serializable.
- Keep executable backend choice in `Pipeline`, not in request data.
- Keep loaded resources and lifecycle state in `CoreRuntime`, not requests or globals hidden from callers.
- Prefer composition over inheritance. Backends are plain functions.
- Keep CLIs thin: parse arguments, build request/pipeline objects, call Core.
- Keep future HTTP handlers thin: map JSON to `CoreJobRequest`, resolve service-level backend names outside Core, call Core.
- Keep generators mechanical. Scientific defaults belong in advice, Kmesh, or selection.
- Treat a target-code integration as one adapter spanning validation, target resource selection, target-specific data, and generation.
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
| `jobs.py` | `CoreRuntime`, `run_core_job()`, `Pipeline`, and public convenience functions. |
| `pipeline.py` | Removed. `recommend`, `generate`, `write_bundle` moved to `jobs.py`. |
| `analysis.py` | Structure facts only. No recommendations. |
| `advice.py` | Provenance-backed scientific and numerical advice. |
| `kmesh.py` | Concrete k-point grid resolution from advice or hints. |
| `selection.py` | Current QE UPF/SSSP selection, Ry cutoff extraction, selection warnings. |
| `generation.py` | Current QE SCF validation and input rendering from completed records. |
| `bundle.py` | Bundle directory output and manifest writing. |
| `advisors/` | Model-backed stage backend factories. |
| `cli/` | Thin command-line wrappers. |
| `io/` | Structure loading only. |
| `ml/` | Feature extraction, model loading, prediction helpers. |
| `pseudo/` | QE-oriented UPF/SSSP parsing, metadata registry, filtering, policies. |

## Dependency direction

`contracts.py` defines boundary records and callable signatures. Stage modules import contracts; contracts do not import stage modules.

`jobs.py` separates three concerns: immutable request data, executable
`Pipeline` composition, and long-lived `CoreRuntime` resource ownership. The
built-in composition uses default field values:

```python
@dataclass(frozen=True, slots=True)
class Pipeline:
    analyze: AnalyzeStage = analyze_structure
    advise: AdviseStage = advise_parameters
    kmesh: KMeshAdvisor = field(default_factory=default_kmesh_advisor)
    select: SelectStage = select_parameters
    generate: GenerateStage = generate_inputs
    bundle: BundleStage = write_bundle_directory
    resources: tuple[RuntimeResource, ...] = ()
```

`pipeline.py` was removed. `recommend`, `generate`, and `write_bundle` now live
in `jobs.py` as thin wrappers around `run_core_job()`. `CoreRuntime` owns one
pipeline and its lazily loaded default model resources across jobs. The default
Kmesh factory reads the complete replaceable QRF inference configuration from
`model_registry.toml`; upstream artifact locations are not embedded in stage
code. The extractor owns its feature schema/version, while
the registry owns artifact identities, exact runtime requirements, feature
settings, interval confidence/quantiles, and calibration. A deterministic
configuration digest and structured reconstruction record cross the Kmesh
boundary in provenance.

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

## Request, Pipeline, and runtime

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

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
```

`CoreRuntime` owns one pipeline's reusable resources. A stateful stage uses the
`RuntimeResource` contract (`reset()` and `close()`); `Pipeline` registers it
without wrapping the callable. Each resource identity has one exclusive runtime
owner, so a second runtime for the same stateful pipeline raises. Direct
`run_core_job(..., pipeline=...)` is only for a pipeline with no registered
resources; it rejects a stateful pipeline. Stateless callables need no lifecycle
methods.

```python
with CoreRuntime(pipeline=pipeline) as runtime:
    result = runtime.run(request)
```

The separation means:

- requests can cross JSON, HTTP, and MCP boundaries;
- pipelines can carry Python callables without lifecycle state in requests;
- runtimes can share models across jobs and close resources deterministically;
- Core does not need string-based backend registries;
- provenance still records whether a value came from a default, analysis, user hint, lookup, model, or fallback.

## Stage ownership summary

| Stage | Owner | Output | Rule |
| --- | --- | --- | --- |
| Load | `io/structures.py` | `Structure` | I/O only. |
| Analyze | `analysis.py` | `StructureAnalysisRecord` | Facts only. |
| Advise | `advice.py` | `ParameterAdvice` | Physics intent and provenance, not target syntax. |
| Kmesh | `kmesh.py`, `advisors/` | `KPointSelection` | Operator k-point hints win. |
| Select | `selection.py` | `SelectionRecord` | Currently QE UPF resources and Ry cutoffs; no k-point recalculation. |
| Generate | `generation.py` | `tuple[GeneratedFile, ...]` | Currently QE SCF validation and rendering. |
| Bundle | `bundle.py` | `BundleRecord` | Atomic no-replace publication of a fully staged directory on supported platforms. |

## Extension points

Replace a `Pipeline` field to change one stage backend. This is suitable for a different implementation of the same stage contract, such as alternate rendering of the current completed QE selection:

```python

pipeline = Pipeline(generate=my_qe_generator)
```

Adding another DFT target is not a Generate-only extension. The current request, units, resource metadata, Select output, and generator are QE-shaped. A target adapter must bind compatible validation, Select, and Generate behavior while leaving the graph fixed. See [target-code adapter boundary](target-code-adapters.md).

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

See [pipeline](pipeline.md) and [backends](backends.md) for current signatures and examples. See [target-code adapter boundary](target-code-adapters.md) for the multi-code design.

## Runtime ownership and external surfaces

Zero-configuration Python calls share a resettable process runtime. Explicit
`CoreRuntime` instances capture model registry and artifact override paths at
construction. `reset()` waits for active calls, resets every registered resource,
and retains their exclusive ownership; replacing the runtime captures changed
environment values. `close()` sets `is_closing` before waiting for active calls,
so new runs fail promptly. Concurrent close callers wait for resource closes and
hooks, then receive the same shutdown failure if one occurred. `is_closed` is
true only after shutdown completes; ownership releases only then. Reset or close
from the runtime's own active run raises rather than waiting for itself.

The one-shot CLI creates and closes one runtime inside `main()`. A future HTTP or
MCP host must create one runtime at application startup, reuse it for all
requests/tool calls, and close it during application shutdown. Handlers map
transport data to `CoreJobRequest`, resolve service-level backend names outside
Core, call `runtime.run(request)`, and serialize `CoreResult.to_dict()`. They must
not construct a runtime per request. HTTP/MCP transport, auth, uploads,
workspaces, persistence, and queues stay outside Core.
