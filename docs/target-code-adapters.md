# Target-code adapter boundary

Status: design only. The adapter and target-neutral contract changes described here are not implemented yet. Quantum ESPRESSO SCF remains the only supported target.

## Why Generate is not the whole boundary

The fixed pipeline makes `Pipeline.generate` replaceable, but its input is already shaped by earlier Quantum ESPRESSO decisions. A second target cannot be added correctly by installing another text writer alone.

Today the target affects:

- accepted `CalculationIntent.code` and task combinations;
- the resource metadata accepted by `CoreJobRequest`;
- resource filtering, ranking, and compatibility checks in Select;
- cutoff and convergence quantities, units, and semantics;
- mapping of shared physics choices to target-supported methods;
- generated files and target syntax.

A target-code adapter therefore spans target validation, target-aware Select work, and Generate. It does not add stages or move target syntax into Analyze or Advise.

## Current contract inventory

### Genuinely shared records

These records contain structure facts, physical intent, or pipeline results that do not depend on Quantum ESPRESSO syntax:

- `StructureAnalysisRecord` and the loaded `Structure`;
- `Provenance` and `StageRecord`;
- the task, functional, and accuracy concepts in `CalculationIntent` (apart from its QE-only `code` literal and pseudo-family default);
- `KPointAdvice.spacing` and `KPointSelection.grid` as numerical reciprocal-space sampling, with the documented solid-state reciprocal-lattice convention;
- `MagnetismAdvice`, `SpinOrbitAdvice`, and `VdwAdvice` as physics-level choices;
- `GeneratedFile`, `BundleRecord`, and the fixed mode/stage trace.

Even shared k-point data needs adapter validation: mesh names, shift flags, symmetry handling, and file representation are target-specific.

### Shared ideas with a QE-shaped representation

These concepts can be shared only after their representation is made target-neutral:

- `SmearingAdvice` expresses an occupation policy, but `width_ry` and current labels are QE-oriented.
- `ConvergenceAdvice` expresses SCF convergence intent, but `conv_thr` is in Ry and `mixing_beta`/`electron_maxstep` have target-specific semantics and names.
- `PseudopotentialAdvice` expresses functional and relativistic intent useful to plane-wave pseudopotential codes, but `pseudo_mode="efficiency"` is an SSSP policy and pseudopotentials are not a universal resource model.
- `CalculationHints.smearing_width_ry` and `conv_thr` expose current QE numerical conventions at the request boundary.

A target-neutral revision must use documented canonical physical units or explicit unit-bearing values for genuinely shared quantities. A target adapter converts those values and records target-native units; target keyword names and target-only controls do not belong in Analyze or Advise.

### Quantum ESPRESSO-specific records and behavior

The following are currently QE-specific rather than reusable adapter inputs:

- `CodeName = Literal["quantum_espresso"]` and the CLI's single `--code` choice;
- `CoreJobRequest.pseudo_metadata: tuple[PseudoMetadata, ...]`;
- `PseudoMetadata`, which describes UPF headers and SSSP fields such as `is_sssp`, `source_pseudopotential`, and `sssp_recommended_cutoff`;
- Select's UPF/SSSP filtering and five-part ranking policy;
- `PseudopotentialSelection.filename`, `filepath`, `ecutwfc_ry`, and `ecutrho_ry`;
- `SelectionRecord.pseudopotentials`, which makes the nominally general record a QE plane-wave selection;
- Ry-valued smearing and SCF convergence fields in hints/advice;
- generation's QE SCF guards, namelists/cards, `degauss`, `ecutwfc`, `ecutrho`, `nspin`, `noncolin`, `lspinorb`, and vdW keyword mapping;
- generation's fixed QE layout values, including `calculation='scf'`, `pseudo_dir='./pseudo'`, `outdir='./out'`, `ibrav=0`, force/stress printing, and the `inputs/qe.in` path.

The `pseudo/` package is therefore the built-in QE resource implementation, not a universal resource layer.

## Adapter responsibilities

A second target must provide one coherent adapter implementation with four responsibilities.

### 1. Validate the target

The adapter accepts exactly the target identifier it implements and validates supported calculation tasks and feature combinations. Validation must happen no later than the start of Select so `recommend` mode rejects an unsupported target too. Generate repeats compatibility checks defensively against the completed target selection.

Validation includes target constraints such as supported smearing or vdW methods, spin/SOC combinations, k-point representation, ordered-structure requirements, and required resource types. Failures are explicit; unsupported physics is not silently dropped.

### 2. Select concrete target resources

Select delegates target resource work to the adapter. The adapter consumes shared advice plus serializable target resource metadata and produces typed, provenance-bearing target selections.

Examples include:

- QE: UPF files, SSSP family/ranking, and wavefunction/charge-density cutoffs;
- VASP: compatible PAW datasets and licensed POTCAR references;
- CASTEP: pseudopotential datasets and cutoff metadata;
- CP2K: coordinated basis-set and potential selections.

Resource parsing remains outside Select. Downloads, licensed file distribution, and runtime staging remain outside Core. Bundle behavior does not start copying resources implicitly.

### 3. Materialize target-specific numerical data

The adapter maps shared physics intent and canonical quantities to explicit target data before generation. It validates units, converts where conversion is physically meaningful, maps supported method labels, and records the result and provenance in typed target-specific selection records.

This is not permission for hidden generator defaults. A target-only numerical choice that cannot be derived mechanically must be made by an explicit target selection policy and recorded before Generate. Semantically different controls must not be presented as unit conversions merely because their names look similar.

### 4. Generate files

Generate consumes the structure, shared advice, and the adapter's completed target selection. It renders one or more `GeneratedFile` records and does not choose resources, infer missing cutoffs, invent convergence settings, or parse resource metadata.

A library writer such as ASE may implement this responsibility for one target. The adapter boundary is still larger than that writer.

## Placement in the fixed graph

The graph remains:

```text
Load -> Analyze -> Advise -> Kmesh -> Select -> Generate -> Bundle
```

Ownership is:

- **Load:** stable structure I/O.
- **Analyze:** code-agnostic structure facts only.
- **Advise:** code-agnostic physics intent, uncertainty, and canonical quantities only.
- **Kmesh:** a concrete numerical mesh; no target syntax.
- **Select:** adapter validation, concrete target resources, target-unit conversion, and target-specific data.
- **Generate:** adapter rendering from completed selections.
- **Bundle:** target-agnostic, path-safe publication of generated files and the manifest.

There is no Adapter stage and no dynamic DAG.

## Target composition invariant

This is a binding design constraint for a future implementation, not an executable adapter API.

A target adapter has one declared target identity: the same identifier requested by `CalculationIntent.code`. Target resource metadata and the typed target selection it produces carry that identity. A target selection may be produced only by an adapter with the same identity.

A **target pipeline factory** is the only composition entry point for a multi-code target. Conceptually, it accepts one target adapter and any independently replaceable shared-stage backends, then constructs a Pipeline whose Select and Generate behavior both come from that one adapter. It must not accept independently supplied target-specific Select and Generate callables. Replacing a target means constructing a new pipeline from a different complete adapter, not swapping one half of an existing target pair.

At job execution, the composed adapter validates that `CalculationIntent.code` matches its declared identity before Select runs. Select receives the complete `CalculationIntent`, or an immutable target-selection context derived from it, together with resource metadata for that identity. It therefore receives the target, task, functional, and other target-relevant intent needed for validation. It rejects metadata with another target identity and emits a typed selection tagged with its own identity. Generate receives that completed tagged selection and rejects an identity mismatch defensively before rendering.

Consequently, the factory and stage contracts enforce this invariant for every run:

```text
request target identity == adapter identity == resource metadata identity == target selection identity == generator identity
```

The current QE-only `Pipeline` still exposes separate `select` and `generate` fields. That is an existing same-target extension seam, not the future multi-code composition mechanism; it must be revised when the first target adapter is implemented. No executable factory, adapter protocol, or contract change is introduced by this document.

## Contract direction

A future implementation should follow these constraints without treating this document as a finished Python API:

- Keep shared analysis, advice, k-point, provenance, generated-file, and bundle records independent of target syntax.
- Replace the universal-looking pseudo fields with typed, target-discriminated resource metadata and target selection records. Do not use an unvalidated `dict[str, Any]` payload as the long-term boundary.
- Keep a shared selection envelope for k-points, warnings, target identity, and the typed target selection.
- Revise the Select boundary so adapter validation receives `CalculationIntent`, or an immutable target-selection context derived from it, and target-tagged serializable resource metadata. The exact callable shape is deferred to implementation, but it must satisfy the target composition invariant.
- Include units in target numerical records where ambiguity is possible.
- Keep all request-side resource metadata serializable. `CoreJobRequest` may carry target resource data, but never an adapter object, callable, writer, or backend name that Core must resolve.
- Keep `CoreResult.to_dict()` JSON-safe and preserve provenance through target selection and generation.

Backend-name resolution remains a composition concern. A CLI or service may map a user-facing target name to a bundled adapter at its boundary, then construct a coherent `Pipeline`. Core should not add a mutable global plugin registry or scatter `if intent.code == ...` branches through unrelated modules.

## Adding a second target

A second-code implementation requires coordinated work:

1. Define the target identifier, supported tasks, and validation rules.
2. Define serializable resource metadata and typed target selection records.
3. Provide resource parsers/loaders outside Select.
4. Implement target resource selection and target numerical materialization for Select.
5. Implement generation from the completed target selection.
6. Compose the target through the target pipeline factory so its Select and Generate behavior cannot be separated.
7. Add CLI/service mapping in one boundary location.
8. Test `recommend`, `generate`, and `bundle` paths, including unsupported combinations and incomplete resources.

Swapping only `Pipeline.generate` is suitable for alternate rendering of the same completed QE selection. It is not sufficient for adding another DFT code.

## Coordination with open work

### Issue #40: ASE Quantum ESPRESSO writer

The ASE rewrite belongs inside the QE adapter's Generate responsibility. It may replace hand-written QE formatting while preserving `GeneratedFile` output, but it must consume completed QE selections and preserve all supported physics mappings. It does not move UPF/SSSP selection into ASE and does not by itself establish a multi-code boundary.

### Issue #42: contract module layout

Issue #42 is a pure file-layout refactor and should remain behavior-neutral. Its stage-aligned split can preserve the current public API while documenting which current selection and resource records are QE-specific. The later adapter implementation should place shared contracts separately from typed target contracts rather than treating `PseudopotentialSelection` as universally shared. Do not fold adapter behavior or a speculative protocol into #42.
