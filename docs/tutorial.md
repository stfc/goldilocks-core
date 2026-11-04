# Python API

Use Goldilocks to generate inputs from a script. First complete the
[installation and asset setup](quickstart.md#1-install). Run the examples in
order in the same Python session, or save them in a script and run
`uv run your_script.py`.

## Generate inputs

`advise()` diagnoses a structure against an HPC profile. A decision it
cannot make is marked unavailable or blocked rather than raising, so you can
inspect what is known before deciding whether to generate anything.

```python
from goldilocks_core.examples.structures import structure
from goldilocks_core.inputs.hpc import load_hpc_profile
from goldilocks_core.inputs.structure import PathStructureSource, normalize_structure
from goldilocks_core.service import advise

source = PathStructureSource(structure("Si.cif"))
normalized = normalize_structure(source)
silicon = normalized.structure
hpc = load_hpc_profile("scarf")

advice = advise(silicon, hpc=hpc)
```

Replace `structure("Si.cif")` with a path to your own CIF or POSCAR.
`normalized.source` identifies the file you read (its name, format, sha256
and size), which a published bundle records.
`load_hpc_profile` loads a named profile from `inputs/profiles/`, the same
profiles `--hpc` names on the CLI (see the [CLI reference](cli.md)).
`advise()` runs every analysis/advisor stage (structure facts, functional
and pseudopotential selection, k-point sampling, resource sizing, ...) and
returns one `Advice` holding a `FieldState` per decision.

## Read a recommendation

Each field on `Advice` is a tri-state `Resolved`/`Unavailable`/`Blocked`
value, never a bare number:

```python
from goldilocks_core.resolution import Resolved

functional = advice.system.functional
if isinstance(functional, Resolved):
    print(functional.value, functional.source)

k_sampling = advice.step.kpoints.k_sampling
if isinstance(k_sampling, Resolved):
    print(k_sampling.value.mesh)
```

This prints the selected functional, the source tier that picked it
(`human`/`ml`/`llm`/`heuristic`), and the k-point mesh. Model-dependent
values can change with the installed model, which a model-decided field
names in `provenance.model` (with what it returned); review warnings and
check convergence rather than treating the recommendation as a verified
result.
`advice.records()` returns every decision as a plain `{name: FieldState}`
dict of the advisors' typed values (`resolution.records_document` turns it
into the JSON the CLI, HTTP and `goldilocks.json` publish), and
`advice.warnings()` flattens every record's warnings into one list, each
naming the record it came from in `record`, if you want to inspect
everything at once instead of field by field.

## Choose settings yourself

Pass overrides built by `build_overrides` for the settings you want to
control — the same validation path `--set`/HTTP/MCP use, so an unknown key
or a badly-shaped value fails the same way here as anywhere else. Name the
task: each setting reaches the steps of that task it applies to, and a
setting no step of the task reads (`press` on an scf) is refused:

```python
from goldilocks_core.set_overrides import build_overrides

assignments = {"k_grid": (4, 4, 4)}
overrides = build_overrides(assignments, task="scf_single_point")
advice = advise(silicon, hpc=hpc, overrides=overrides)

k_sampling = advice.step.kpoints.k_sampling
if isinstance(k_sampling, Resolved):
    print(k_sampling.value.mesh, k_sampling.source)
```

The mesh is now `(4, 4, 4)` with `source == "human"`. An explicit grid
bypasses the k-point model; other settings are still recommended. See
`goldilocks settings` (or the [CLI reference](cli.md)) for every overridable
key.

## Generate and check before publishing

`advise()` does not refuse an incomplete request; `check()`/`generate()` do,
if something the run needs is still `unavailable`/`blocked` or the settings
contradict each other. Always call `check()` first and inspect
`report.blocking` rather than relying on `generate()`'s exception alone. It
holds one `Finding` per root cause: a stable `code`, the settings it concerns
(`fields`), a `message` to show and its shorter `summary`, and `remedies`,
override patches that each resolve it (a `None` value clears that override):

```python
from goldilocks_core.service import check, generate
from goldilocks_core.steps import default_shared_context

report = check(advice)
if not report.ok:
    for finding in report.blocking:
        print("blocked:", finding.message)
        for remedy in finding.remedies:
            print("  try overrides:", remedy)
else:
    ctx = default_shared_context()
    steps = generate(advice, report, ctx=ctx)
    print([step.name for step in steps])
```

`generate()` renders the actual Quantum ESPRESSO input file(s) as `Step`
objects, raising `AdviceIncomplete` if called with a non-`ok` report — this
is a hard boundary, not the primary way to learn what is missing.

## Choose an output

Turn generated steps into a submission script and a publishable bundle,
then choose where the result goes:

```python
from goldilocks_core.bundle import ArchiveOutput, DirectoryOutput, bundle_files, publish
from goldilocks_core.service import render_submission, to_bundle_input

script = render_submission(advice, hpc, "quantum_espresso", steps)
bundle_input = to_bundle_input(
    advice,
    steps,
    script,
    ctx,
    code="quantum_espresso",
    hpc=hpc,
    assignments=assignments,
    source=normalized.source,
)
```

The keywords name the request the bundle answers, which `goldilocks.json`
records under `request` with the task (`to_bundle_input` is the
`scf_single_point` task's) and the goldilocks-core version: the code, the HPC
profile, the overrides as submitted (the assignments you passed to
`build_overrides`, `steps.<step>.` prefixes kept) and the input structure's
name, format, sha256 and size. A structure you built in memory
(`InMemoryStructureSource`) has no sha256 or size.

| Output                            | Result                             |
| ---------------------------------- | ----------------------------------- |
| `bundle_files(bundle_input)`        | Keep the result in memory           |
| `publish(bundle_input, DirectoryOutput("si-run"))` | Write a new directory  |
| `publish(bundle_input, ArchiveOutput("si-run.zip"))` | Write a ZIP with the same contents |

Choose a destination that does not already exist; `publish` refuses to
overwrite one. `publish` returns a `Publication` with `path`, `kind`, and
the list of published file paths.

## Inspect structures

`normalize_structure` is also the entry point for structure-only
inspection, without running any advisor:

```python
inspection = normalize_structure(source).inspection
print(inspection["structure"]["reduced_formula"])
print(inspection["canonical_cif"])
```

## Generate a multi-step task

Five tasks run more than one Quantum ESPRESSO step: `dos` (an scf, a denser
nscf pass and `dos.x`), `band` (an scf, `pw.x` along a band path and
`bands.x`) and the three phonon tasks (an scf, a relax or a vc-relax, then
`ph.x`, `q2r.x`, and `matdyn.x` for the phonon DOS and for the dispersion).
Each has its own five functions, named after the task
(`advise_dos` ... `to_bundle_input_dos`, `advise_band` ...
`to_bundle_input_band`; the phonon tasks share `advise_phonon` ...
`to_bundle_input_phonon`), which advise the task's steps together, then
generate one input per step. `TASK_PHASES` in `goldilocks_core.service`
holds every task's five functions by task name, as the CLI, HTTP and MCP
look them up.

### Density of states

```python
from goldilocks_core.service import (
    advise_dos,
    check_dos,
    generate_dos,
    render_submission_dos,
    to_bundle_input_dos,
)

dos_assignments = {"steps.nscf.k_grid": (12, 12, 12), "delta_e": 0.05}
dos_overrides = build_overrides(dos_assignments, task="dos")
dos_advice = advise_dos(silicon, hpc=hpc, overrides=dos_overrides)
dos_report = check_dos(dos_advice)
if dos_report.ok:
    dos_steps = generate_dos(dos_advice, dos_report, ctx=ctx)
    dos_script = render_submission_dos(dos_advice, hpc, "quantum_espresso", dos_steps)
    dos_bundle = to_bundle_input_dos(
        dos_advice,
        dos_steps,
        dos_script,
        ctx,
        code="quantum_espresso",
        hpc=hpc,
        assignments=dos_assignments,
        source=normalized.source,
    )
    print([step.name for step in dos_steps])
```

The task's steps are `scf`, `nscf` and `dos`. `steps.nscf.k_grid` sets the
nscf mesh only, and `delta_e`, a `dos.x` setting, reaches the `dos` step. A
setting given without a step reaches every step it applies to: a flat
`k_grid` sets both `pw.x` steps, and `dos_advice.warnings()` then carries an
`overrides.applies_to_multiple_steps` notice naming them.

`dos_advice.records()` keys the shared system-level fields and the task's
one `job` unprefixed, the nscf step's own fields under an `nscf_`-prefixed
name, and the DOS decision itself under `"dos"`. Unless the request sets
them, the nscf step takes its k-point spacing (0.10 Å⁻¹) and occupations
(`tetrahedra_opt`) from the dos protocol, aiida-quantumespresso's `pdos.yaml`
(balanced), ahead of the ML tier: `nscf_k_sampling` and `nscf_occupations`
read `heuristic` and name the protocol in `source_note`. A value you set
replaces the protocol's field by field and reads `human`; a `shift` alone
keeps the protocol's mesh, and a `degauss` alone keeps `tetrahedra_opt`.

The three steps run in one allocation, so there is one job, sized over both
`pw.x` steps. `pw.x` counts `max_seconds` from its own start, so the job
splits 95% of the walltime between the scf and the nscf by estimated
workload (`job.max_seconds_by_step`), and each input gets its own share;
`dos.x` runs in what is left. Both `pw.x` steps run on the whole allocation;
`dos.x` runs on one task of it (`srun --nodes=1 --ntasks=1`), because every
extra task would repeat the whole DOS and `dos.x` aborts when a task owns no
FFT plane.

### Band structure

```python
from goldilocks_core.service import (
    advise_band,
    check_band,
    generate_band,
    render_submission_band,
)

band_overrides = build_overrides({"k_path_distance": 0.05}, task="band")
band_advice = advise_band(silicon, hpc=hpc, overrides=band_overrides)
band_report = check_band(band_advice)
if band_report.ok:
    band_steps = generate_band(band_advice, band_report, ctx=ctx)
    band_script = render_submission_band(
        band_advice, hpc, "quantum_espresso", band_steps
    )
    print([step.name for step in band_steps])

k_path = band_advice.records()["k_path"]
if isinstance(k_path, Resolved):
    print(k_path.value.lattice_type, k_path.value.n_kpoints)
    print(k_path.value.primitive_cells)
```

The task's steps are `scf`, `bands` (`pw.x` with `calculation='bands'`) and
`bands_x` (`bands.x`); a collinear spin-polarized run gets `bands_x_up` and
`bands_x_down` instead, one `bands.x` run per spin channel.
`k_path_distance`, the largest spacing between neighbouring points of the
path in Å⁻¹ (2π included, as for `k_distance`), reaches the bands step only.
The k-mesh, occupations and SCF-loop settings set the scf step only, since
the bands step runs the path with the scf step's occupations and no SCF
loop; `nbnd`, `extra_bands`, `conv_thr`, `npool` and `ndiag` given without a
step reach both `pw.x` steps, with the `overrides.applies_to_multiple_steps`
notice.

`band_advice.records()` keys the shared fields, the scf step's own, the
task's one `job` and the bands step's path, `k_path`, unprefixed, and the
bands step's other records under `bands_`: `bands_occupations`,
`bands_nbnd`, `bands_convergence` and `bands_parallelisation`. Unless the
request sets them, the bands step takes its `k_path_distance` (0.025 Å⁻¹)
and three times the occupied bands from aiida-quantumespresso's `bands.yaml`
protocol, read `heuristic` with the protocol in `source_note`.

The path comes from the symmetry of the cell that is written: here the FCC
path of diamond. The bundled `Si.cif` is diamond's 8-atom conventional
cell, so `primitive_cells` is 4 and `k_path` carries the
`k_path.folded_bands` notice: at each point of the path, the bands of four
points of the primitive cell's zone appear together. Upload a primitive cell
for unfolded bands. See [the band structure path](science.md#check-the-band-structure-path)
for slabs, wires, magnets and what the path does not cover.

### Phonons

`advise_phonon(silicon, task="relax-phonon", hpc=hpc, overrides=...)`
advises a phonon task: `task` is `phonon`, `relax-phonon` or
`vc-relax-phonon`, and the overrides come from `build_overrides(...,
task="relax-phonon")` for the same task. `check_phonon`, `generate_phonon`,
`render_submission_phonon` and `to_bundle_input_phonon` take the
`PhononAdvice` it returns, as the dos functions take a `DosAdvice`, and
`TASK_PHASES["relax-phonon"]` holds all five with the task bound.
`generate_phonon` returns the first `pw.x` step (`scf`, `relax` or
`vc-relax`), `d3hess` under DFT-D3, then `ph`, `q2r`, `phonon_dos` and
`dispersion`, matdyn.x along the band task's path.

The advice's `records()` keys the first step's records and the task's one
`job` unprefixed, as for a single `pw.x` step, with `fft_grid`, the dense FFT
grid ph.x accepts, and, for a relaxation, `relax`; then `q_sampling` and
`phonon` (the ph step), `q2r`, `phonon_dos` and `k_path`, the dispersion
step's path. It is the path a band task would take at the same
`k_path_distance`, except on fixed occupations without `isolation='slab'`,
where matdyn.x adds the non-analytic term: each Γ inside a branch is then
listed twice and each segment into Γ lands on it exactly, which
`source_note` says and `n_kpoints` counts. `PhononAdvice.first` is the
first step's own `Advice`. Its k-mesh is raised against the q-mesh unless the
request sets it, and a relaxation converges to `forc_conv_thr` 1e-4 Ry/Bohr
unless the request sets that. A phonon job splits no walltime between its
steps: `job.max_seconds_by_step` is empty, and `job.timer_seconds`, 95% of the
walltime, is when the submission script's timer stops pw.x or ph.x cleanly.
See [the phonon tasks](science.md#check-the-phonon-tasks) for the q-mesh, the
dispersion, the refusals and how a stopped job resumes.

See [Recommendations](science.md) to interpret other settings, or
[Architecture](architecture.md) to extend the computation workflow.
