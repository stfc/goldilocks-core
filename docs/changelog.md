# Changelog

All notable changes to goldilocks-core are documented here.

## Unreleased

### Added

- `goldilocks assets install`, `status`, and `verify` commands for runtime
  models and pseudopotential tables.
- Registry table IDs are accepted by the assets commands without the
  `pseudopotentials/` storage prefix (`goldilocks assets install
  pseudodojo-pbesol-efficiency-sr`).
- Installed example structures for silicon, iron, and platinum.
- Canonical Capabilities, Structure Inspection, and Compute operations for
  Python, CLI, HTTP, and local stdio MCP.
- CLI controls for van der Waals advice.
- Exact pseudopotential-table selection on Python, CLI, HTTP, and MCP requests.
- Provider-normalized PseudoDojo and SSSP installation into verified manifests.
- Canonical HTTP OpenAPI and generated TypeScript contracts, including
  in-memory ZIP Compute responses.
- A stateless production image containing matching Core and Workbench builds
  plus the complete verified runtime asset profile.

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
  an operator root, an exact installed table ID, or Core's compatible-table
  selection policy.
  `--fetch-missing` installs only the exact missing dependencies reported by
  Core.
- `recommend` and `generate` are now Preset IDs selected through one Compute
  operation across Python, CLI, HTTP, and MCP.
- CLI record queries use the stable output names `analysis`, `advice`,
  `k_points`, `selection`, `generated_files`, and `dft_input_data`.
- CLI and local MCP use shared automatic, directory, archive, and memory output
  semantics. HTTP archives are never stored on the server.
- Invalid requests and incomplete Quantum ESPRESSO inputs now fail with
  specific errors.
- Pseudopotential selection now consumes one normalized metadata interface;
  registry access, provider parsing, and filesystem discovery live behind the
  source-resolution stage.
- Installed runtime assets record a source-and-preparer fingerprint so changes
  to normalized contents invalidate stale installations. PseudoDojo and SSSP
  tables retain provider licence material, and model assets retain their pinned
  CC BY 4.0 model cards. Ready-to-run publications include selected UPFs, every
  applicable licence notice, provenance, and checksums.

### Removed

- The `goldilocks-core` and `goldilocks-kmesh` console commands. Use
  `goldilocks`.
- Public recommend/generate methods, commands, HTTP routes, and MCP tools. Use
  Compute with `PresetSelection("recommend")` or `PresetSelection("generate")`.
- Separate task, code, and model discovery operations. Use Capabilities.
- Browser-specific scientific HTTP routes and response contracts.
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