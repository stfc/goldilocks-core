# Changelog

All notable changes to goldilocks-core are documented here.

## Unreleased

### Added

- Capabilities, Structure Inspection, and Compute operations across Python,
  CLI, HTTP, and local stdio MCP.
- Validating Calculation Draft and Computation Selection constructors, with
  plain dict stage documents keyed by stable Record marker classes.
- Complete DFT Input Data publication as a directory or deterministic ZIP,
  including source and canonical structures, generated inputs, exact
  pseudopotentials, licences, citations, provenance, and manifest file hashes.
  Publication uses private staging and atomic no-overwrite installation; it
  assumes an operator-controlled destination parent.
  DFT Input Data captures file contents during assembly; publication no longer
  resolves Asset references or revalidates internal Records. Runtime provenance
  retains model identities and preparation fingerprints without file inventories.
- Transactional runtime asset installation and verification for models and
  registered PseudoDojo and SSSP Pseudopotential Sets.
- Asset lifecycle commands accept bare registry table IDs such as
  `pseudodojo-pbesol-efficiency-sr` as well as namespaced asset IDs and shipped
  profiles.

### Fixed

- Installed pseudopotential manifests validate against the table's asset id
  (`pseudopotentials/<table>`), matching what `write_table_manifest` records.
  Fresh installs of every registered table now load through the strict reader;
  new lifecycle tests install and reload each shipped table.
- Runtime asset stores with `schema_version: 1` asset manifests are
  incompatible with this release, including both bare and namespaced table
  directories. Reinstall them: `goldilocks assets install default`.

### Changed

- `recommend` and `generate` are Preset IDs selected through Compute.
- The unified `goldilocks` command provides scientific operations, asset
  lifecycle commands, examples, and optional HTTP/MCP serving.
- CLI supports automatic, directory, archive, and memory output. Local MCP
  supports server-chosen automatic publication or memory output; it does not
  accept publication paths. HTTP pairs reviewed Result JSON with its exact
  optional unstored ZIP in one multipart response.
- Installed metallicity assets drive electronic-character analysis. Model
  configuration is cached per backend; reset reloads model resources without
  rereading configuration.
- HTTP Compute requests execute concurrently over one process-owned Runtime
  instead of a process-wide computation slot.
- Generated request contracts expose the supported scientific enum values.
- Pseudopotential selection consumes one normalized metadata interface and
  resolves compatible registered tables in Core. HTTP and MCP may select a
  registered table by stable ID, but accept no structure paths, pseudopotential
  roots or metadata payloads, model locations, or publication paths.
- The default functional is PBEsol.

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
