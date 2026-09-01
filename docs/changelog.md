# Changelog

All notable changes to goldilocks-core are documented here.

## Unreleased

### Added

- CLI `--use-vdw` and `--vdw-method` options matching the Python hint controls.
- Example structures (`Si`, `Fe_bcc`, `Pt_fcc`) installed with the package, reachable from `goldilocks_core.examples` and `goldilocks-core examples path`.
- `DimensionalityClassificationError` and `SymmetryAnalysisError` (in `goldilocks_core.analysis`); `SymmetryUnavailable` typed value (in `goldilocks_core.contracts`), recorded in symmetry fields when spglib cannot analyze.
- A typed DAG executor with frozen stage/task/preset specifications, registered SCF presets, and `CoreRecords` query results.
- `CoreRuntime` as the explicit lifecycle owner for reusable kmesh and metallicity models.
- `query_records(request)` for explicit record queries; `run_core_job` runs presets only.
- HTTP and MCP transports behind optional `[http]` and `[mcp]` extras: `POST /recommend`, `/generate`, `/compute` endpoints and matching MCP tools, plus `/tasks`, `/codes`, `/models` discovery. HTTP reports request/domain failures as deliberate 4xx responses while unexpected exceptions remain 500 errors.
- `CoreService` as the unified backend runtime composing `CoreRuntime` (model lifecycle) and `TaskDispatcher` (dispatch); the CLI, HTTP, and MCP are thin entrypoints over it.
- Shared `from_dict` deserializer (`server/request.py`) turning a JSON body into a `PresetRequest` or `QueryRequest`, including round-trip support for serialized `pymatgen.Structure` values.
- Stable backend-owned record ids (`record_type_id`, `RECORD_TYPE_IDS`, `resolve_output_types`, `OUTPUT_RECORD_TYPES`) so the wire format never leaks Python class names.
- `describe_task` and `TaskGraphDescription` for transport-safe task descriptions; `TaskSpec`/`StageSpec` carry their own transport metadata.
- CLI `serve http`/`serve mcp` subcommands.
- `QrfKpointsConfig.metallicity_model` (a `ModelSpec`) so the metallicity classifier is discoverable.

### Changed

- Transports accept only the calculation: `from_dict` parses inline structure content, `intent`, `hints`, and `outputs`, and rejects `output_dir`, `pseudo_metadata`, `pseudo_root`, and `kmesh_model` as unknown fields. Path-form structures are rejected too — the wire carries inline CIF/POSCAR content, never server paths. Model selection, pseudopotential sources, and output locations are deployment configuration resolved by the server process (pinned model registry, asset store); per-request overrides remain available on the CLI and Python API, which run inside the operator's trust boundary.
- CLI model name/version metadata now requires the local `--model` backend.
- Loaded-model quantiles are checked before QRF confidence is reported.
- Job-level warnings now include de-duplicated scientific caveats from Advise as well as Analyze, Kmesh, and Select.
- Bundle output uses a straightforward no-overwrite directory writer.
- MCP tool schemas reject unknown root arguments, and CI installs all optional extras before running the transport tests.
- Default exchange-correlation functional changed from PBE to PBEsol. This changes generated inputs and the pseudopotentials selected on a default run; pass `--functional PBE` to restore the previous behaviour.
- `run_core_job` and `query_records` delegate through a short-lived `CoreService`; reusable applications and both servers keep one service alive for model lifecycle and task dispatch.
- K-points are resolved by `resolve_kpoints(structure, hints, backend)`; the `KMeshAdvisor` signature is `(Structure) -> KPointSelection`.
- CLI `--model` now sets the request's `kmesh_model` (a `ModelSpec` on `PresetRequest`/`QueryRequest`) instead of swapping a `Pipeline` backend.
- Every `src/**/__init__.py` is now an export-only facade; logic moved to named sibling modules (`ml/qrf/inference`, `ml/kindex/inference`, `kmesh/resolve`, `advice/parameters`, `examples/structures`). Public import paths are preserved by re-exports.
- Dimensionality: CrystalNN/Larsen failures now raise `DimensionalityClassificationError` instead of silently degrading to `"unknown"`; disordered structures keep a conservative warned `"unknown"` default (a precondition, not an error swallow).
- Symmetry: spglib failures raise `SymmetryAnalysisError`, caught in `analyze_structure` and recorded as typed `SymmetryUnavailable(reason=...)`; the recommendation stays complete (symmetry is reporting-only).
- QRF composition featurizers: the catch-all `try/except TypeError` shim around `impute_nan` is replaced with explicit signature introspection (`impute_nan` is passed only where the constructor accepts it).
- `build_kmesh_entries` no longer swallows `ValueError` from `mesh_to_k_line_density_interval` into `k_line_density_interval=None`; the error propagates.
- CLI invalid-argument handling: `parser.error(...)` replaced with `parser.print_usage(...)` + `raise SystemExit(2)` (same exit code and message; the handler now re-raises).
- Analyze uses the runtime-owned CGCNN metallicity model when configured and records provenance and confidence; the structure heuristic remains the fallback.
- K-point selection is a sibling record: `SelectionRecord` contains pseudopotentials and warnings, while `CoreResult`, input generation, and the QE writer receive `k_points` separately.
- Orchestration moved to `goldilocks_core.runtime`: stage-agnostic `runtime/graph.py`, the SCF task in `runtime/scf.py`, `CoreRuntime` (model lifecycle only) and `TaskDispatcher` (task registry + dispatch) in `runtime/core.py` + `runtime/dispatch.py`, entrypoints in `runtime/jobs.py`. Tasks register a `TaskHandler` (graph + context builder + result assembler) and dispatch by `intent.task`.
- The `runtime` package facade is task-agnostic: `SCF_TASK`, `ScfContext`, and `assemble_core_result` are imported from `goldilocks_core.runtime.scf`, not re-exported by `goldilocks_core.runtime`.
- The SCF task is registered as the default lazily on first dispatch, so `import goldilocks_core.runtime` no longer eagerly loads the stage implementations (29 vs 50 `goldilocks_core` submodules at import).
- `CoreJobRequest` split into `PresetRequest` (preset run: `mode`/`output_dir`) and `QueryRequest` (explicit query: `outputs` required at construction). `run_core_job` takes `PresetRequest`; `query_records` takes `QueryRequest`. The old cross-field runtime validation is gone — each request type carries only its own selector, so the invariant is structural.
- `CoreRecords.to_dict` and `QueryRequest.to_dict` now key outputs by stable record ids (`analysis`, `advice`, `k_points`, `selection`, `generated_files`) instead of Python class names.
- CLI `compute --outputs` now takes stable record type ids; `run_core_job`/`query_records` route through a short-lived `CoreService`.
- `TaskSpec` gains `name`/`description`/`revision`/`selectable_outputs`; `StageSpec` gains `id`/`name`/`description`, read by `describe_task`.
- `TaskDispatcher.describe_tasks()` and `CoreRuntime.describe_models()` expose the discovery surfaces `CoreService` aggregates.
- `model_registry.toml` `[defaults.kpoints.metallicity]` gains `name`/`version`/`model_type`/`target`/`feature_set` for the metallicity model spec.


### Fixed

- Python requests reject unsupported target codes and calculation tasks before running QE-oriented stages.
- QE generation rejects unsupported smearing labels, unsafe pseudopotential filenames, and duplicate, missing, or extraneous pseudopotential selections.

### Removed

- Operational stage traces from `CoreResult`.
- Bundle content hashes, byte counts, atomic publication machinery, and platform-specific path simulation.
- Exact runtime reconstruction and local artifact hashing from QRF provenance.

- `CalculationIntent.accuracy_level` and CLI `--accuracy-level`; the advertised levels had no implemented scientific effect. This is an intentional API and serialized-schema change with no compatibility alias.
- Heuristic k-points: `KPointAdvice` record, `ParameterAdvice.k_points` field, `advise_k_points`, `DEFAULT_K_SPACING`, `resolve_kpoints_from_advice`, and CLI `--heuristic-kpoints`. The model-free default-spacing fallback is gone; use explicit hints or the QRF model.
- `Pipeline` dataclass and the `AnalyzeStage`/`AdviseStage`/`SelectStage`/`GenerateStage`/`BundleStage` Callable aliases.
- `AdvicePolicies` injectable container and its policy type aliases; `advise_parameters` calls the policy functions directly.
- `register_writer` and the mutable writer dispatch table; the table is now a static tuple.
- Dead `parse_upf` dataframe layer (`metadata_to_row`/`metadata_list_to_rows`/`metadata_list_to_dataframe`) and the helpers only it used.
- `advisors/__init__.py` `__getattr__` lazy facade; direct re-exports replace it (the facade was already defeated by `jobs.py`'s module-level advisor imports).
- The `_lint` no-swallow framework (`allow_swallow`, `check_no_swallow.py`, the pre-commit hook).
- The standalone `bundle` job mode and `write_bundle` convenience function; `generate(..., output_dir=...)` now handles publication.
- `CoreJobRequest` (split into `PresetRequest`/`QueryRequest`).
- The `recommend` and `generate` free-function wrappers (use `run_core_job(PresetRequest(mode=...))`).

## [0.1.0] - 2026-06-10

### Added

- Staged Core pipeline: Load → Analyze → Advise → Kmesh → Select → Generate → Bundle.
- `CoreJobRequest` and `CoreResult` for shared Python/CLI/HTTP job surface. `CoreResult` is a single accumulator that includes the optional `BundleRecord`.
- `run_core_job()` as the fixed stage runner with `recommend`, `generate`, and `bundle` modes.
- `StructureAnalysisRecord` with composition, element classification, symmetry, disorder warnings, and conservative electronic-character heuristic.
- `ParameterAdvice` with provenance-backed advice for k-points, smearing, magnetism, SOC, pseudopotentials, and convergence.
- Kmesh-stage concrete k-point resolution with swappable default and ML backends.
- `Pipeline` composition object for swappable stage backends, now a frozen dataclass in `jobs.py` with default field values.
- `SelectionRecord` with Kmesh-provided k-point grids, pseudopotential selections, and cutoff extraction.
- Quantum ESPRESSO SCF input generation from completed advice/selection records.
- Portable bundle directory output with `manifest.json`.
- `goldilocks-core` CLI with `recommend`, `generate`, and `bundle` subcommands, including `--model` for ML Kmesh backend selection.
- Deterministic pseudopotential ranking by mode match, cutoff completeness, SSSP status, source, and filename.
- JSON-safe serialization via `to_dict()` / `to_jsonable()`.
- Future HTTP API mapping documented without adding HTTP dependencies.
- Expanded structure analysis: symmetry, crystal system, conservative electronic character.
- Expanded advice: analysis-backed smearing, SOC consideration, convergence settings.
- Comprehensive docstrings with per-field documentation on all contract dataclasses.

### Changed

- Heavy-element heuristic changed from `Z >= 57` to period-5+ (`row >= 5` in pymatgen).
- K-point grid resolution moved from Select into the Kmesh stage.

### Removed

- `goldilocks_core.shared` package and `shared/types.py`. Use `goldilocks_core.contracts` instead.
- `KPointAdviceRecord` renamed to `KPointAdvice`.
- Top-level shortcut aliases on `CoreRecommendation` (`grid`, `contains_*`, etc.). Access nested fields directly. `CoreRecommendation` and `CoreJobResult` were merged into `CoreResult`.
- `io.structures.analyze_structure()` moved to `analysis.analyze_structure()`.
- `goldilocks_core.pipeline` module, `default_pipeline()`, and `bundle_recommendation()` removed. `recommend`, `generate`, and `write_bundle` now live in `jobs.py`.
- Unused `PseudoSelection` type removed.