# Changelog

All notable changes to goldilocks-core are documented here.

## [Unreleased]

### Changed

- Result surface unified into a single `CoreResult` accumulator. `recommend`, `generate`, `write_bundle`, and `run_core_job` all return `CoreResult`. Bundle's output is now a `BundleRecord` stage record on the result (`result.bundle.path`, `result.bundle.manifest`) rather than a separate envelope.
- `Pipeline` is now a frozen dataclass with default backends as field values, in `jobs.py`. Compose via `Pipeline(kmesh=...)`; `Pipeline()` is the default composition.
- `CoreJobRequest` validates `mode` and `output_dir` at construction (`__post_init__`).
- `KPointAdvice` enforces exactly-one-of `spacing`/`explicit_grid` at construction.
- CLI JSON output echoes the request itself: `{"request": ..., **result.to_dict()}`.
- `write_bundle_directory` returns `BundleRecord` (previously a manifest dict).
- `build_bundle_manifest` takes `CoreResult`.

### Removed

- `CoreRecommendation` and `CoreJobResult`. Use `CoreResult`.
- `default_pipeline()`. Use `Pipeline()`.
- `bundle_recommendation()`. Use `result.to_dict()`.
- `goldilocks_core.pipeline` module. Entry points moved to `goldilocks_core.jobs`; stage standalones (`load`, `analyze`, `advise`, `select`) removed — use `Pipeline` fields and `load_structure`.
- `dataclasses.replace`-based swap idiom removed from the public surface (the escape hatch still works but is not taught).
- Dead `to_jsonable` branch removed.
- No compatibility aliases or shims were added for any removed name.

## [0.1.0] - 2026-06-10

### Added

- Staged Core pipeline: Load → Analyze → Advise → Kmesh → Select → Generate → Bundle.
- `CoreJobRequest`, `CoreResult`, `StageRecord` for shared Python/CLI/HTTP job surface.
- `run_core_job()` as the fixed stage runner with `recommend`, `generate`, and `bundle` modes.
- `StructureAnalysisRecord` with composition, element classification, symmetry, disorder warnings, and conservative electronic-character heuristic.
- `ParameterAdvice` with provenance-backed advice for k-points, smearing, magnetism, SOC, pseudopotentials, and convergence.
- Kmesh-stage concrete k-point resolution with swappable default and ML backends.
- `Pipeline` composition object for swappable stage backends.
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
- Top-level shortcut aliases on the recommendation result (`grid`, `contains_*`, etc.). Access nested fields directly.
- `io.structures.analyze_structure()` moved to `analysis.analyze_structure()`.
- Unused `PseudoSelection` type removed.