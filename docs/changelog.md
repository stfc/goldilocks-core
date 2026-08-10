# Changelog

All notable changes to goldilocks-core are documented here.

## Unreleased

### Added

- CLI `--use-vdw` and `--vdw-method` options matching the Python hint controls.
- Example structures (`Si`, `Fe_bcc`, `Pt_fcc`) installed with the package, reachable from `goldilocks_core.examples` and `goldilocks-core examples path`.
- `DimensionalityClassificationError` and `SymmetryAnalysisError` (in `goldilocks_core.analysis`); `SymmetryUnavailable` typed value (in `goldilocks_core.contracts`), recorded in symmetry fields when spglib cannot analyze.
- `allow_swallow` decorator (`goldilocks_core._lint`) and the `scripts/check_no_swallow.py` AST pre-commit hook enforcing export-only `__init__.py` and no silent `try/except` (the sole opt-in is `@allow_swallow`).
- A typed DAG executor with frozen stage, task, and preset registries. It resolves the minimal subgraph for requested record types and memoizes shared prerequisites within each run.
- The registered `scf_single_point` task, with `recommend` and `generate` presets over independent Analyze and Kmesh branches.
- `CoreRuntime` as the explicit lifecycle owner for the executor, run-context construction, reusable kmesh backends, and the optional metallicity model.
- `CoreRecords`, a type-keyed mapping returned by arbitrary record queries.
- `CoreJobRequest.outputs` and the `goldilocks-core compute --outputs ...` query surface.
- Optional HTTP transport with `POST /recommend`, `POST /generate`, `POST /compute`, and `GET /health`.
- Optional MCP stdio transport with `recommend`, `generate`, and `compute` tools.
- Shared `from_dict` request deserialization for HTTP and MCP.
- The Goldilocks Workbench, an independently built React application in `web/`, with Guided (load → recommend → override → ZIP) and backend-driven Graph views sharing one tab-lifetime workspace.
- Browser-safe HTTP endpoints `GET /tasks` (backend-owned Task Graph Descriptions) and `POST /structure/load` (canonical Structure Document); `POST /generate` returns in-memory generated input contents.
- HTTP transport rejects server-path fields (`output_dir`, `pseudo_root`, path-shaped `structure`, `pseudo_metadata.filepath`) as `invalid_request`; pseudopotentials are identified by filename/library.
- Bounded per-process computation concurrency (`GOLDILOCKS_COMPUTE_LIMIT`/`GOLDILOCKS_COMPUTE_WAIT_SECONDS`); a saturated gate surfaces a retryable `server_busy` 503 with `Retry-After`.
- Structured failure envelope (`{kind, message, status, details}`) with stable kinds including `unexpected` (500); full server tracebacks are logged for unexpected failures.
- Typed transport schemas producing OpenAPI, with committed generated TypeScript contracts (`openapi-typescript`/`openapi-fetch`) and a drift check (`npm run verify:api`).
- Static same-origin serving of the built Workbench from FastAPI after all API routes, and a multi-stage Dockerfile composing matching Core and Workbench builds into one non-root container.
- Server-owned deployment config seam (`server/config.py`) for computation capacity and injected pseudo metadata (`GOLDILOCKS_PSEUDO_METADATA` or `GOLDILOCKS_PSEUDO_ROOT`).

### Changed

- CLI model name/version metadata now requires the local `--model` backend.
- Loaded-model quantiles are checked before QRF confidence is reported.
- Job-level warnings now include de-duplicated scientific caveats from Advise as well as Analyze, Kmesh, and Select.
- Bundle output uses a straightforward no-overwrite directory writer.
- Default exchange-correlation functional changed from PBE to PBEsol. This changes generated inputs and the pseudopotentials selected on a default run; pass `--functional PBE` to restore the previous behaviour.
- `run_core_job` now delegates to `CoreRuntime`; `mode` selects a full-result preset and `outputs` selects a `CoreRecords` query. The runtime executes only the required SCF subgraph.
- HTTP and MCP servers retain one `CoreRuntime` per process so lazily loaded model state is reused across calls.
- K-points are resolved by `resolve_kpoints(structure, hints, backend)`; the `KMeshAdvisor` signature is `(Structure) -> KPointSelection`.
- CLI `--model` now sets `CoreJobRequest.kmesh_model` (a `ModelSpec` on the request) instead of swapping a `Pipeline` backend.
- Every `src/**/__init__.py` is now an export-only facade; logic moved to named sibling modules (`ml/qrf/inference`, `ml/kindex/inference`, `kmesh/resolve`, `advice/parameters`, `examples/structures`). Public import paths are preserved by re-exports.
- Dimensionality: CrystalNN/Larsen failures now raise `DimensionalityClassificationError` instead of silently degrading to `"unknown"`; disordered structures keep a conservative warned `"unknown"` default (a precondition, not an error swallow).
- Symmetry: spglib failures raise `SymmetryAnalysisError`, caught in `analyze_structure` and recorded as typed `SymmetryUnavailable(reason=...)`; the recommendation stays complete (symmetry is reporting-only).
- QRF composition featurizers: the catch-all `try/except TypeError` shim around `impute_nan` is replaced with explicit signature introspection (`impute_nan` is passed only where the constructor accepts it).
- `build_kmesh_entries` no longer swallows `ValueError` from `mesh_to_k_line_density_interval` into `k_line_density_interval=None`; the error propagates.
- CLI invalid-argument handling: `parser.error(...)` replaced with `parser.print_usage(...)` + `raise SystemExit(2)` (same exit code and message; the handler now re-raises).
- Metallicity classification is a runtime service supplied to Analyze. The runtime-owned CGCNN model is used when configured; otherwise the structure heuristic is used. `electronic_character_source` and `electronic_character_confidence` record the provenance and confidence.
- K-point selection is a sibling record: `SelectionRecord` contains pseudopotentials and warnings, while `CoreResult`, input generation, and the QE writer receive `k_points` separately.
- Preset responses remain `CoreResult`; query responses serialize only their requested records through `CoreRecords`.

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
- The standalone `bundle` job mode, CLI subcommand, and `write_bundle` convenience function; `generate(..., output_dir=...)` now handles publication.

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