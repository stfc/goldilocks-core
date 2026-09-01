# Changelog

All notable changes to goldilocks-core are documented here.

## Unreleased

### Added

- `goldilocks assets install`, `status`, and `verify` commands for runtime
  models and pseudopotential tables.
- Installed example structures for silicon, iron, and platinum.
- HTTP and MCP operations for recommendations, input generation, record
  queries, and capability discovery.
- CLI controls for van der Waals advice.
- Exact pseudopotential-table selection on Python, CLI, HTTP, and MCP requests.
- Provider-normalized PseudoDojo and SSSP installation into verified manifests.

### Fixed

- Installed pseudopotential manifests validate against the table's asset id
  (`pseudopotentials/<table>`), matching what `write_table_manifest` records.
  Fresh installs of every registered table now load through the strict reader;
  new lifecycle tests install and reload each shipped table.
- Stores installed before asset-id namespacing (bare table directories with
  `schema_version: 1` manifests) are incompatible with this release. Reinstall
  them: `goldilocks assets install default`.

### Changed

- The only console command is now `goldilocks`.
- The default functional is now PBEsol. Use `--functional PBE` for PBE.
- Runtime models and pseudopotential tables must be installed before the paths
  that use them. Pseudopotential sources resolve lazily from explicit metadata,
  an operator root, an exact installed table ID, or the registered default.
  `--fetch-missing` installs only the exact missing dependencies reported by
  Core.
- `recommend`, `generate`, and `compute` use one `CoreService` interface across
  Python, CLI, HTTP, and MCP.
- Transports accept only the calculation: inline structure content, `intent`,
  `hints`, and `outputs`. File paths, model overrides, pseudopotential
  sources, and output locations are deployment configuration resolved by the
  server, never request data.
- CLI record queries use the stable output names `analysis`, `advice`,
  `k_points`, `selection`, and `generated_files`.
- Invalid requests and incomplete Quantum ESPRESSO inputs now fail with
  specific errors.
- Pseudopotential selection now consumes one normalized metadata interface;
  registry access, provider parsing, and filesystem discovery live behind the
  source-resolution stage.

### Removed

- The `goldilocks-core` and `goldilocks-kmesh` console commands. Use
  `goldilocks`.
- Top-level Python `recommend` and `generate` functions. Use
  `CoreService.recommend`, `CoreService.generate`, or `run_core_job`.
- Automatic heuristic k-point spacing. Install the default model or supply
  `--k-grid` or `--k-spacing`.
- `CalculationIntent.accuracy_level` and `--accuracy-level`, which did not
  change scientific behaviour.
- `CalculationIntent.pseudo_mode` and `--pseudo-mode`. Use the validated
  efficiency/precision control `pseudo_accuracy` or `--pseudo-accuracy`.

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