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
- JSON-safe `CoreJobRequest` and `CoreResult` records.

`CalculationIntent.accuracy_level` was intentionally removed because no stage
implemented distinct accuracy/cost semantics. Serialized requests no longer
contain it, and the CLI does not expose `--accuracy-level`.

## Install

```bash
uv sync
```

The HTTP server transport is an optional extra (`uv sync --extra http`); `import goldilocks_core` does not require it.

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
print(result.bundle.manifest)
```

`run/` must not already exist. Bundle publication stages the complete directory on the destination filesystem, refuses all existing destinations, and does not provide an overwrite mode. Manifest entries include the UTF-8 byte count and SHA-256 hash of each generated file.

Bundle layout:

```text
run/
├── manifest.json
└── inputs/
    └── qe.in
```

See [bundle stage](docs/stages/bundle.md) and [manifest](docs/manifest.md).

## Job runner

Use `CoreJobRequest` and `run_core_job()` when a caller needs one request/result model for Python, CLI, or HTTP. `CoreJobRequest.from_dict` / `CalculationIntent.from_dict` / `CalculationHints.from_dict` deserialize the JSON form shared with the HTTP transport.

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

For a service, worker, notebook session, or other long-lived caller, own one
runtime and reuse it across jobs:

```python
from goldilocks_core import CoreJobRequest, CoreRuntime

with CoreRuntime() as runtime:
    first = runtime.run(CoreJobRequest(structure="Si.cif"))
    second = runtime.run(CoreJobRequest(structure="Ge.cif"))
```

The runtime lazily loads each default model once and supports concurrent calls.
A stateful `RuntimeResource` has exactly one `CoreRuntime` owner by identity;
sharing its `Pipeline` with another runtime raises. `runtime.reset()` retains
that ownership, discards cached initialization failure, and retries on the next
model-backed job. `close()` first sets `is_closing`, so new runs fail promptly;
concurrent close callers wait for resource closes and hooks. `is_closed` becomes
true only when shutdown completes, including a completed shutdown with an error.
All close callers receive the same shutdown error. Reset or close from that
runtime's own active job raises instead of waiting for itself.

Modes:

```text
recommend -> Load → Analyze → Advise → Kmesh → Select
generate  -> Load → Analyze → Advise → Kmesh → Select → Generate
bundle    -> Load → Analyze → Advise → Kmesh → Select → Generate → Bundle
```

### Default k-point model

`CoreRuntime()` owns a `Pipeline()` with the configured QRF k-distance model and
heuristic fallback. Model loading is lazy: constructing either object and
resolving explicit `k_grid` or `k_spacing` hints performs no model download or
inference. Reusing the runtime reuses loaded QRF and metallicity artifacts.

Zero-configuration `recommend()` and `run_core_job()` calls share a resettable
process-level runtime. Call `reset_default_runtime()` to close and discard it;
the next convenience call captures current environment configuration and creates
a replacement. Prefer an explicit `CoreRuntime` when lifetime ownership matters.

The extractor owns the explicit 483-value feature schema. Model and supporting
artifact identities, exact inference-stack versions, feature settings, interval
confidence, quantiles, and calibration live in
`goldilocks_core/model_registry.toml`. Package dependencies that affect this
contract are pinned to those versions. The advisor checks the declared schema
and runtime before loading artifacts, then verifies that the loaded model's own
quantiles match the declared confidence interval. Set
`GOLDILOCKS_MODEL_REGISTRY=/path/to/models.toml` to replace the complete default
configuration without changing package source. A runtime captures registry and
artifact override paths at construction. It does not observe later environment
changes. `runtime.reset()` reloads files at the captured paths; construct a new
runtime, or reset the process default, to capture replacement environment values.

Successful QRF selections serialize the deterministic registry digest, full
configuration, Core/extractor identity, required and installed runtime versions,
and artifact identities in `provenance.details.qrf_inference`. Local model,
checkpoint, and atom-table files are identified by SHA-256 content hashes.

Hugging Face artifacts are cached by `huggingface_hub`; alternate remote
registries must specify full 40-character commit revisions rather than branches
or tags. The configured QRF is a
joblib/pickle artifact, so only use registries and revisions you trust. To avoid
remote model loading entirely, provide explicit k-point hints or compose the
heuristic backend:

```python
from goldilocks_core import Pipeline
from goldilocks_core.kmesh import resolve_kpoints_from_advice

pipeline = Pipeline(kmesh=resolve_kpoints_from_advice)
```

Normal tests never resolve real remote artifacts. Run the explicit compatibility
check only when network access is intended:

```bash
uv run python scripts/validate_qrf_artifacts.py --allow-network
```

## Custom backends

`Pipeline` holds Python callables for stage backends. `CoreJobRequest` remains data-only.
Pass a stateless pipeline directly for one call. A pipeline containing a
`RuntimeResource` must be owned by exactly one `CoreRuntime`; direct
`pipeline=` execution is rejected:

```python

from goldilocks_core import CoreRuntime, Pipeline, recommend
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

with CoreRuntime(pipeline=pipeline) as runtime:
    result = recommend("path/to/structure.cif", runtime=runtime)
```

`ml_kmesh_advisor(spec)` is a lifecycle-aware backend: its runtime loads it
once, caches a load failure until `runtime.reset()`, and releases ownership only
after close hooks finish. Stateless custom callables still work with direct
`pipeline=` execution. Stateful custom backends implement `RuntimeResource`
(`reset()` and `close()`); `Pipeline` registers them with the runtime.

See [backends](docs/backends.md) for backend contracts and examples.

## CLI

```bash
uv run goldilocks-core recommend path/to/structure.cif --json
uv run goldilocks-core recommend path/to/structure.cif --model path/to/model.joblib --json
uv run goldilocks-core recommend path/to/structure.cif --heuristic-kpoints --json
uv run goldilocks-core generate path/to/structure.cif --pseudo-root path/to/pseudos --k-grid 4 4 4 --use-vdw true --vdw-method d3bj --json
uv run goldilocks-core bundle path/to/structure.cif --pseudo-root path/to/pseudos --k-grid 4 4 4 --out run/ --json
uv run goldilocks-core serve --heuristic-kpoints --port 8000   # requires `uv sync --extra http`
```

The legacy kmesh-focused entry point is still available:

```bash
uv run goldilocks-kmesh path/to/structure.cif --model path/to/model.joblib
```

The CLI owns one `CoreRuntime` for its one-shot process and closes it before
exit. It does not use or persist the Python convenience runtime.

See [CLI reference](docs/cli.md).

## Long-lived HTTP and MCP hosts

The HTTP server transport is implemented behind the optional `[http]` extra.
Run it with `goldilocks-core serve` (loopback by default); it owns one
`CoreRuntime` for the process lifetime, reuses it for every request, and closes
it on shutdown. See [HTTP server](docs/server/http.md).

```python
runtime = CoreRuntime()

# startup: retain runtime
# request/tool call: runtime.run(core_request)
# shutdown: runtime.close()
```

Do not construct `CoreRuntime` or `Pipeline()` inside each handler. Transport,
auth, persistence, queues, and service-level backend-name resolution remain
outside Core. An MCP transport is a sibling concern, not implemented here yet.

## Package layout

```text
src/goldilocks_core/
├── contracts.py   # public records, type aliases, serialization
├── jobs.py        # fixed runner, Pipeline, CoreRuntime, and convenience API
├── analysis.py    # structure facts
├── advice.py      # provenance-backed parameter advice
├── kmesh.py       # k-point grid resolution
├── selection.py   # current QE UPF/SSSP selection and Ry cutoffs
├── generation.py  # current QE SCF validation and rendering
├── bundle.py      # bundle directory and manifest writing
├── advisors/      # model-backed stage backends
├── cli/           # thin command wrappers
├── io/            # loading only
├── ml/            # feature extraction, model loading, prediction
├── model_registry.toml  # replaceable default model and artifact metadata
└── pseudo/        # UPF parsing, registry, filtering, policy
```

See [architecture](docs/architecture.md) for boundaries and dependency direction.

## Documentation

- [Architecture](docs/architecture.md)
- [Target-code adapter design](docs/target-code-adapters.md)
- [Pipeline](docs/pipeline.md)
- [Backends](docs/backends.md)
- [Contracts](docs/contracts.md)
- [Serialization](docs/serialization.md)
- [Manifest](docs/manifest.md)
- [Conventions](docs/conventions.md)
- [Provenance](docs/provenance.md)
- [CLI](docs/cli.md)
- [HTTP server](docs/server/http.md)
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
