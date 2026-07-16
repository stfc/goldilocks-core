# Composable Core pipeline

The Core pipeline is a fixed graph with injectable stage backends.

```text
Load -> Analyze -> Advise -> Kmesh -> Select -> Generate -> Bundle
```

The graph order is fixed. The implementation behind each stage is configurable through a `Pipeline` object.

## Why this exists

Core separates three concerns:

- **What to compute**: structure, intent, hints, mode, pseudo metadata, output directory.
- **How to compute it**: stage implementations for analysis, advice, k-point resolution, selection, generation, and bundle writing.
- **How long resources live**: loaded models, retry/reset state, and deterministic shutdown.

`CoreJobRequest` carries the first concern. It is data-only and JSON-safe.

`Pipeline` carries the second concern. It is immutable composition and is not serialized as part of the request.

`CoreRuntime` carries the third concern. It owns one pipeline's reusable resources across jobs.

This split keeps transport boundaries clean while making Python callers able to swap backends and own process lifetimes directly.

### Lifecycle resources

A stateful backend implements the typed `RuntimeResource` contract:

```python
class RuntimeResource(Protocol):
    def reset(self) -> None: ...
    def close(self) -> None: ...
```

`Pipeline` automatically registers any stage backend implementing this contract
and also accepts independent resources through `resources=`. A resource identity
can belong to one `CoreRuntime` only; a second runtime for it raises.
`CoreRuntime.reset()` waits for active jobs and calls each resource's `reset()`
without releasing ownership. `close()` calls each resource's `close()` in reverse
order and releases ownership only after all close hooks finish. Plain stateless
callables require no resource methods and continue to work unchanged.

`ml_kmesh_advisor(spec)` returns a callable `RuntimeResource`. Its model loads
once on first hint-free use, concurrent first calls share that load, and a load
failure is cached until `runtime.reset()`. `close()` releases its model reference.

## Core objects

```python
from goldilocks_core import CoreJobRequest, CoreRuntime, Pipeline, run_core_job
```

`Pipeline` is a frozen dataclass with one callable per stage:

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

The built-in composition is returned by `Pipeline()`:

```python
pipeline = Pipeline()
```

`run_core_job()` accepts one-call stateless composition or a long-lived runtime:

```python
stateless_pipeline = Pipeline(kmesh=my_stateless_kmesh)
result = run_core_job(request, pipeline=stateless_pipeline)

with CoreRuntime(pipeline=pipeline) as runtime:
    result = run_core_job(request, runtime=runtime)
```

A direct `pipeline=` call rejects registered `RuntimeResource` values because it
would bypass their owner. When neither is passed, `run_core_job()` uses the resettable process-level
runtime also shared by `recommend()`, `generate()`, and `write_bundle()`. The
default Kmesh backend lazily loads the QRF configuration and models; explicit
k-point hints bypass model loading. Use
`Pipeline(kmesh=resolve_kpoints_from_advice)` for an explicitly heuristic path.

## Stage contracts

### Analyze

```python
AnalyzeStage = Callable[[Structure], StructureAnalysisRecord]
```

Input:

- loaded `pymatgen.core.Structure`

Output:

- `StructureAnalysisRecord`

Responsibility:

- report structure facts only
- no parameter recommendations
- no generated file logic

### Advise

```python
AdviseStage = Callable[
    [StructureAnalysisRecord, CalculationIntent, CalculationHints],
    ParameterAdvice,
]
```

Inputs:

- analysis facts
- operator intent
- operator hints

Output:

- `ParameterAdvice`

Responsibility:

- choose scientific/numerical intent
- record provenance on every advice record
- preserve uncertainty as warnings

Advise does not produce concrete k-point grids. It produces `KPointAdvice`, which is intent: explicit grid or spacing plus mesh type and provenance.

### Kmesh

```python
KMeshAdvisor = Callable[[Structure, CalculationHints, KPointAdvice], KPointSelection]
```

Inputs:

- loaded structure
- operator hints
- `KPointAdvice` from Advise

Output:

- `KPointSelection`

Responsibility:

- resolve concrete k-point grid and shift
- preserve hint precedence
- record whether the grid came from a hint, default/advice path, or model

Kmesh is a separate stage because k-point resolution is the natural backend
seam. The configured default predicts a grid from a QRF model when no hint is
set and falls back to advice-based resolution when ML is unavailable. A custom
backend can replace either strategy.

### Select

```python
SelectStage = Callable[
    [Structure, ParameterAdvice, KPointSelection, Sequence[PseudoMetadata]],
    SelectionRecord,
]
```

Inputs:

- loaded structure
- full parameter advice
- concrete k-point selection from Kmesh
- pseudopotential metadata

Output:

- `SelectionRecord`

Responsibility:

- carry the Kmesh result into the final selection record
- select pseudopotentials and cutoffs
- aggregate selection warnings

Select does not resolve k-points. That belongs to Kmesh.

### Generate

```python
GenerateStage = Callable[
    [Structure, CalculationIntent, ParameterAdvice, SelectionRecord],
    tuple[GeneratedFile, ...],
]
```

Inputs:

- loaded structure
- intent
- advice
- selection

Output:

- generated files

Responsibility:

- validate and render the current completed QE selection
- never choose resources or scientific defaults

The callable seam permits another renderer for the same selection contract. It is not, by itself, the boundary for adding a DFT code: current request resources, Select output, units, and generation are QE-shaped. See [target-code adapter boundary](target-code-adapters.md).

### Bundle

```python
BundleStage = Callable[[CoreResult, str | Path], BundleRecord]
```

Inputs:

- completed recommendation with generated files
- output directory

Output:

- `BundleRecord` with the bundle path and manifest dictionary

Responsibility:

- preflight generated paths and manifest metadata
- stage the complete directory and publish to an absent destination
- refuse overwrite and reject path traversal
- stay independent of Runner/AiiDA/frontend assumptions

## Execution by mode

```text
recommend -> Load -> Analyze -> Advise -> Kmesh -> Select
generate  -> Load -> Analyze -> Advise -> Kmesh -> Select -> Generate
bundle    -> Load -> Analyze -> Advise -> Kmesh -> Select -> Generate -> Bundle
```

`Load` is not a field on `Pipeline`. Structure loading is stable I/O at the request boundary. The swappable computational stages start after loading.

## Runtime lifecycle

Default recommendation uses a process-level runtime:

```python
from goldilocks_core import CoreJobRequest, run_core_job

first = run_core_job(CoreJobRequest(structure="Si.cif"))
second = run_core_job(CoreJobRequest(structure="Ge.cif"))
```

The calls share loaded default models. The process runtime is resettable:

```python
from goldilocks_core import reset_default_runtime

reset_default_runtime()  # closes it; the next call creates a replacement
```

Long-lived callers should make ownership explicit:

```python
from goldilocks_core import CoreRuntime

with CoreRuntime() as runtime:
    first = runtime.run(CoreJobRequest(structure="Si.cif"))
    second = runtime.run(CoreJobRequest(structure="Ge.cif"))
```

Concurrent calls through one runtime share race-safe first initialization.
Initialization failures are cached to avoid retrying on every request. Call
`runtime.reset()` to wait for active jobs, reset every registered resource, and
retry lazily. A runtime captures model registry and supporting-artifact
environment paths at construction. Reset rereads files at those paths; construct
a replacement runtime to capture changed environment values.

An explicitly composed pipeline can also be runtime-owned:

```python
runtime = CoreRuntime(pipeline=Pipeline(kmesh=my_kmesh))
```

Stateless custom callables make reset a no-op. Stateful custom backends implement
`RuntimeResource` directly or are listed in `Pipeline(resources=(resource,))`.
`close()` sets `is_closing` and rejects new runs while it waits for active jobs,
closes resources, and runs hooks once. Other close callers wait for that work;
all receive the recorded shutdown error, if any. `is_closed` becomes true only
when it finishes. A hook's worker call to `run()` therefore fails promptly.
Calling `reset()` or `close()` from that runtime's own active job raises
`RuntimeError`; it never waits for itself.

## Replacing one backend

Construct ``Pipeline`` with the field you want to swap; the remaining stages keep their default backends:

```python

from goldilocks_core import CoreJobRequest, Pipeline, run_core_job
from goldilocks_core.advisors import ml_kmesh_advisor
from goldilocks_core.contracts import ModelSpec

spec = ModelSpec(
    name="local-kmesh-model",
    version="v1",
    model_type="random_forest",
    target="k_index",
    feature_set="cslr",
    source="local",
    location="models/kmesh.joblib",
)

pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
with CoreRuntime(pipeline=pipeline) as runtime:
    result = runtime.run(CoreJobRequest(structure="Si.cif"))

print(result.selection.k_points.provenance.source)  # "model"
```

The request contains no model field. The request says what to compute. The pipeline says how to compute it.

## Replacing multiple backends

```python

pipeline = Pipeline(
    kmesh=ml_kmesh_advisor(spec),
    generate=generate_alternate_qe_inputs,
)
```

A backend is just a function with the right signature. No base class, registry, plugin loader, or string resolution is required inside Core.

A second target needs a coherent adapter that supplies compatible validation, target resource selection, target numerical data, and generation. The future composition layer must bind its Select and Generate behavior together rather than relying on unrelated stage overrides. The fixed graph and data-only request boundary remain unchanged.

## Provenance expectations

Backends must return the standard contract objects with correct provenance:

- hint-derived values use `source="user_hint"`
- model-derived values use `source="model"`
- metadata lookups use `source="lookup"`
- package defaults use `source="default"`
- analysis-derived choices use `source="analysis"`
- fallback/incomplete selections use `source="fallback"`

Provenance is part of the backend contract. A backend that returns a bare tuple or string is not a Core backend.

## CLI, HTTP, and MCP mapping

Core does not resolve backend names. It accepts callables.

The one-shot CLI resolves its options to a `Pipeline`, creates one `CoreRuntime`
for the command process, runs the request, and closes the runtime. The HTTP
server transport (`goldilocks-core serve`, optional `[http]` extra) does the
same for a long-lived process: it creates one `CoreRuntime` during application
startup and reuses it for every request, closing it on shutdown. An MCP process
is a sibling concern, not implemented here yet, but would follow the same
lifetime — create one runtime at startup and reuse it for every tool call:

```python
pipeline = Pipeline(kmesh=ml_kmesh_advisor(spec))
runtime = CoreRuntime(pipeline=pipeline)  # application startup

result = runtime.run(request)             # each request or tool call
runtime.close()                           # application shutdown
```

Do not create a runtime or default pipeline inside each HTTP or MCP handler.
The transports own JSON parsing, error mapping, and service-level backend-name
resolution; Core sees the callable returned by `ml_kmesh_advisor(spec)`, never
a string such as `"cslr"`.
