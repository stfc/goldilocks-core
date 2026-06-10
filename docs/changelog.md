# Changelog

All notable changes to goldilocks-core are documented here.

## [0.1.0] - 2026-06-10

### Added

- Staged Core pipeline: Load → Analyze → Advise → Kmesh → Select → Generate → Bundle.
- `CoreJobRequest`, `CoreJobResult`, `StageRecord` for shared Python/CLI/HTTP job surface.
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
- Top-level shortcut aliases on `CoreRecommendation` (`grid`, `contains_*`, etc.). Access nested fields directly.
- `io.structures.analyze_structure()` moved to `analysis.analyze_structure()`.
- Unused `PseudoSelection` type removed.