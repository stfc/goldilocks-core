## Review: refactor/staged-core-pipeline

**Files changed against main:** 57
**Verdict:** ready

### Scope reviewed

- Uncommitted working tree: none at review start.
- Branch-only commits in `main..HEAD`, including staged pipeline contracts, analysis/advice/select stages, job runner, Generate, Bundle, staged CLI, pseudo ranking, docs, and tests.
- Focus areas requested by Willow: code quality, feature completeness against the consolidated #8 plan, and absence of compatibility shims.

### Verification

- `uv run pytest -q` → 67 passed
- `uv run ruff check src tests` → passed
- `uv run ruff format --check src tests` → passed
- `uv run pre-commit run --all-files` → passed

### Findings

| Severity | File | Issue | Recommendation |
|----------|------|-------|----------------|
| none | — | No critical, high, medium, or low blocking issues found after review fixes. | Ready for PR review. |

### Review fixes applied before final verdict

Two issues were found during manual review and fixed before this report was finalized:

1. **QE SOC syntax interaction** — `generation.py` could emit `nspin = 2` together with `noncolin = .true.` / `lspinorb = .true.` when both spin polarization and SOC were advised. This was corrected so SOC uses noncollinear flags without collinear `nspin = 2` syntax. Regression test added.
2. **NumPy JSON serialization** — `to_jsonable()` did not convert `numpy.ndarray` or NumPy scalar values, so `StructureFeatureVector` serialization was not fully JSON-safe. This was corrected and `StructureFeatureVector.to_dict()` was added. Regression test added.

### Feature alignment with #8 consolidated plan

Implemented and verified:

- Shared Core job surface: `CoreJobRequest`, `StageRecord`, `CoreJobResult`, `run_core_job()`.
- Fixed job graph modes: `recommend`, `generate`, `bundle`.
- Generate stage: Quantum ESPRESSO SCF input writer in `generation.py`.
- Bundle stage: deterministic directory writer and manifest in `bundle.py`.
- Thin staged CLI: `goldilocks-core` command in `cli/core.py`, plus existing `goldilocks-kmesh` preserved.
- Future HTTP mapping: documented as JSON-to-`CoreJobRequest` and `CoreJobResult.to_dict()`; no HTTP framework dependency added.
- Scientific expansion: symmetry/crystal-system facts, conservative electronic-character heuristic, analysis-backed smearing, expanded convergence advice.
- Pseudopotential selection: deterministic ranking by mode, cutoff completeness, SSSP status, source, filename; warnings remain visible.
- Pseudo dataclass cleanup: `PseudoMetadata` and `PseudoPolicy` now use `slots=True`.
- Dependency policy: no new external dependencies added.

### Compatibility shim audit

No compatibility shims were added.

Confirmed:

- No `goldilocks_core.shared` reintroduction.
- No legacy alias modules.
- No duplicate import paths for staged contracts.
- Existing `goldilocks-kmesh` remains as its own current CLI path, not as a compatibility wrapper around removed API.
- New `goldilocks-core` CLI delegates to `run_core_job()` and contains no scientific decision logic.

### Notes

- Bundle output records selected pseudopotential metadata but does not copy pseudopotential files. This matches the documented initial contract and avoids hidden file/download behavior.
- Dimensionality remains `unknown`; this is intentional until a reliable implementation is chosen.
- Electronic character is conservative: all-metal compositions become `likely_metal`, other structures remain `unknown` with warnings.

### No significant issues

No significant issues remain after the two review fixes above.

---
Written by an agent on behalf of Willow.
