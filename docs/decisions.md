# Design decisions

This records the non-obvious choices made during the staged Core refactor and why they were made. Decisions are durable; if you're questioning one, check here first.

## `slots=True` on all dataclasses

All new dataclasses use `slots=True`. Pre-existing dataclasses (`PseudoMetadata`, `PseudoPolicy`) were updated to use it during the refactor.

**Why:** slots prevent accidental attribute creation, reduce memory footprint, and make the attribute contract explicit. In a package with many small dataclasses, the safety benefit outweighs the minor inconvenience of not having `__dict__`.

## No compatibility shims

When `goldilocks_core.shared` was removed, no backward-compatible aliases were added. Same for top-level shortcuts on `CoreRecommendation`.

**Why:** compatibility shims accumulate into permanent maintenance burden. They create multiple import paths for the same concept, which confuses new users and makes refactoring harder. One canonical API is cheaper in the long run.

## Fixed graph, not a DAG

`run_core_job()` runs a fixed sequence of stages, not a dynamic DAG. The only branching is mode-based: `recommend` stops after Select, `generate` continues through Generate, `bundle` continues through Bundle.

**Why:** a DAG engine is complexity that Core doesn't need. The stage graph is known at design time. A fixed sequence is easier to understand, test, and debug. If future stages need conditional execution, the mode enum can be extended rather than introducing dynamic dispatch.

## SOC is never auto-enabled

Even when heavy elements are detected, `SpinOrbitAdvice.enabled` remains `False`. The advice sets `consider=True` and emits a warning.

**Why:** enabling SOC changes calculation cost (often 4× or more), convergence behavior, and pseudopotential requirements. Silently enabling it would surprise operators and potentially break their workflow. The operator must make an informed decision.

## Conservative electronic character

The heuristic returns `likely_metal`, not `metal`. It returns `unknown` for most mixed compositions.

**Why:** metallicity depends on electronic structure, not composition. A structure-only heuristic cannot confirm metallicity. Labeling it "likely" with a warning is honest about the uncertainty. Callers who need certainty should use their own classification or verify against DFT results.

## Pseudo ranking uses a 5-tuple deterministic key

Candidates are sorted by `(mode_rank, cutoff_rank, sssp_rank, source, filename)`. No randomness, no floating-point scores.

**Why:** deterministic ranking ensures reproducibility across runs and machines. Two operators with the same metadata and same advice should get the same selection. The lexicographic tiebreakers (`source`, `filename`) ensure stable ordering even when all other criteria match.

## Bundle does not copy pseudo files

The bundle directory contains generated input files and a manifest, but not pseudopotential files.

**Why:** Core may not have the pseudo files on disk (metadata can come from a remote registry), and copying large binary files into the bundle would change its semantics from "provenance record + input syntax" to "ready-to-run calculation directory." That's Runner's job, not Core's.

## Convergence hints use `or` for partial overrides

`_advise_convergence()` uses `hints.conv_thr or DEFAULT_CONV_THR` to fill gaps when only some convergence hints are provided.

**Why:** this lets operators override one convergence parameter without specifying all three. The alternative (requiring all-or-nothing) would be less convenient. Validation in `_validate_hints` prevents zero values from slipping through as "not set."

## `PseudoMetadata` is not frozen

Unlike the contract dataclasses, `PseudoMetadata` is mutable (`slots=True` but not `frozen=True`).

**Why:** test code frequently mutates `PseudoMetadata` fields (e.g. changing `relativistic` from `"scalar"` to `"full"`) when constructing synthetic fixtures. Making it frozen would require every test to use `dataclasses.replace()` instead of direct mutation, adding boilerplate for no safety benefit in test code.