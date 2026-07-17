# Changelog

All notable changes to goldilocks-core are documented here.

## Unreleased

### Added

- CLI `--use-vdw` and `--vdw-method` options matching the Python hint controls.

### Changed

- CLI model name/version metadata now requires the local `--model` backend.
- Loaded-model quantiles are checked before QRF confidence is reported.
- Job-level warnings now include de-duplicated scientific caveats from Advise as well as Analyze, Kmesh, and Select.
- Bundle output uses a straightforward no-overwrite directory writer.

### Fixed

- Python requests reject unsupported target codes and calculation tasks before running QE-oriented stages.
- QE generation rejects unsupported smearing labels, unsafe pseudopotential filenames, and duplicate, missing, or extraneous pseudopotential selections.

### Removed

- Operational stage traces from `CoreResult`.
- Bundle content hashes, byte counts, atomic publication machinery, and platform-specific path simulation.
- Exact runtime reconstruction and local artifact hashing from QRF provenance.

- `CalculationIntent.accuracy_level` and CLI `--accuracy-level`; the advertised levels had no implemented scientific effect. This is an intentional API and serialized-schema change with no compatibility alias.

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