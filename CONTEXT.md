# Goldilocks

Goldilocks helps materials scientists turn crystal structures into trustworthy, inspectable calculation inputs while retaining access to the scientific reasoning behind each recommendation.

## Language

**Goldilocks Core**:
The authority for scientific interpretation, recommendations, calculation-input generation, and the provenance of those decisions.
_Avoid_: Backend, API

**Goldilocks Workbench**:
The browser application through which a scientist prepares, reviews, and inspects a calculation.
_Avoid_: GUI prototype, frontend shell, dashboard

**Scientist**:
A person who understands crystal structures and the intended calculation but may rely on Goldilocks for specialist DFT parameter choices.
_Avoid_: User, novice, operator

**Guided workflow**:
The primary path from a structure and calculation goal to reviewed, downloadable calculation input.
_Avoid_: Pipeline view, wizard

**Expert inspection**:
Contextual access to detailed scientific decisions, provenance, dependencies, and overrides without replacing the guided workflow.
_Avoid_: Expert mode, advanced workflow, developer mode

**Graph view**:
An expert-inspection representation of the dependencies among Core-owned scientific records. It is not the scientist's workflow and is not editable.
_Avoid_: Workflow graph, graph editor

**Calculation Draft**:
The mutable structure, calculation goal, and scientist-provided overrides that describe the calculation currently being prepared.
_Avoid_: Request, form state

**Computation**:
One immutable submission of a Calculation Draft to Goldilocks Core.
_Avoid_: Job, run, request

**Recommendation**:
The immutable scientific records produced by a Computation for review before input generation.
_Avoid_: Settings, defaults, response

**Workspace**:
The tab-lifetime working state that holds the current Calculation Draft and results from its Computations. It is not a saved project or scientific record.
_Avoid_: Session, project, computation

**Out-of-date result**:
A valid result from an earlier Computation whose input snapshot differs from the current Calculation Draft.
_Avoid_: Stale record, invalid result

**Scientific Decision**:
A scientifically meaningful concern for which Goldilocks presents an outcome, its reasoning, and any supported scientist override.
_Avoid_: Stage, parameter group, settings card

**Decision Review**:
The guided-workflow view of every Scientific Decision, including its outcome, warnings, and override state.
_Avoid_: Expert panel, pipeline

**Structure Source**:
The original CIF or POSCAR content provided by the Scientist and retained for reproducibility.
_Avoid_: Upload, structure file

**Canonical Structure**:
Goldilocks Core's validated and normalized representation of a Structure Source, used by every subsequent Computation.
_Avoid_: Parsed file, structure result

**Generated Input Set**:
The named calculation-input files produced from a Recommendation, available individually and together as a reproducibility archive.
_Avoid_: Bundle, output response
