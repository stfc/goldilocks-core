# Architecture

This page is for contributors changing Core or its transports. For using the
library, start with the [Python tutorial](tutorial.md); for browser development,
use the [Workbench development guide](https://github.com/stfc/goldilocks-core/blob/main/web/README.md).

## Set up a contribution

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```bash
git clone https://github.com/stfc/goldilocks-core.git
cd goldilocks-core
uv sync --group dev --all-extras
uv run goldilocks assets install all
uv run pre-commit install
uv run poe check
```

`poe check` runs Ruff lint, format, and complexity checks, then pytest. Use
`uv run poe fmt` to apply Python formatting. The commit hooks run the same checks
and pytest with branch coverage. For frontend checks and API-schema refresh, follow the
[Workbench development guide](https://github.com/stfc/goldilocks-core/blob/main/web/README.md).

## Follow a request

There is no `Service`/`Runtime` object. `goldilocks_core.service` is a package
of plain functions that a transport (or a Python caller) calls in order.
Each task has five of them: `advise`, `check`, `generate`,
`render_submission` and `to_bundle_input`. CLI, HTTP and MCP look a task's
up in one table, `service.TASK_PHASES` (`service/_tasks.py`), with one row
per `types.CalcTask`.

A `run` (or `explain`) request follows this path, shown for the
`scf_single_point` row:

1. `inputs.structure.normalize_structure` turns a CIF/POSCAR source into a
   pymatgen `Structure`, recording a sha256 of the source bytes for
   provenance. This is the same normalization CLI's `inspect` and the HTTP
   `/inspect` route use.
2. `service.advise(structure, *, code, hpc, overrides, store, fetch_missing)`
   runs three phases in a fixed order: `_analysis.analyze` (structure facts),
   `_system.system_advice` (system-wide advisors, starting with the simulated
   cell and pseudopotential-table selection), and `_step.steps_advice`
   (per-step k-point/occupation advisors, then the task's job and each step's
   parallelisation).
   `advise()` returns an `Advice` even for an incomplete request: a field it
   cannot decide, because an input is missing, something is not installed or
   configured, or the request leaves it open, is `Unavailable`/`Blocked`. A
   fault raises and fails the request instead: a model that is set up but
   fails to load or predict, an enumeration error that is not the
   enumerator's own answer about the structure, or a worker process that
   dies.
3. `service.check(advice, *, purpose="scf", relax=None)` calls
   `checks.check_all(...)`; `checks.py` is the one place that refuses a
   request whose decisions are incomplete or inconsistent. A phonon task's
   `check_phonon` passes that report through `checks.with_phonon_findings`,
   which adds the phonon steps' blocked records and the phonon tasks' own
   refusals and drops a `check_all` finding a phonon finding replaces. It
   returns a `CheckReport` whose `.ok`/`.blocking` decide whether `generate()`
   may proceed. Each entry of `.blocking` is a `checks.Finding`, one per root
   cause: a code from `checks.FINDING_CATALOGUE`, the settings it concerns
   (`fields`), a user-facing `message` and its `summary` (at most 200
   characters), and `remedies`, override patches that each resolve it (`None`
   clears an override). A decision that could not be
   made reaches it as `advice.blocked`, with its root cause and no remedy.
4. `service.generate(advice, report, *, ctx, purpose, relax)` raises
   `AdviceIncomplete` (an `ExpectedFailure`, see `failures.py`) if
   `report.ok` is false, whose message lists each finding with its remedies
   and whose HTTP error envelope carries the findings in
   `error.details.findings`; otherwise it renders one or more `Step`s by calling
   `generation.quantum_espresso.scf.write_qe_scf`,
   `generation.quantum_espresso.relax.write_qe_relax` or, for a bands step,
   `generation.quantum_espresso.bands.write_qe_bands` directly. There is no
   writer registry. A phonon task's `generate_phonon` writes its first step
   through `generate()`, with the `fft_grid` and `dftd3_threebody` it needs,
   then calls `generation.quantum_espresso.phonon.write_qe_phonon` for the
   d3hess.x, ph.x and q2r.x steps and the two matdyn.x steps, the phonon DOS
   and the dispersion.
5. `service.render_submission(advice, hpc, code, steps)` renders the
   SLURM script via `submission/slurm.py`. Each step is followed by the
   completion check its writer declared (`Step.completion`), and the script
   stops with a `goldilocks:` message when one fails. A job with
   `JobDecision.timer_seconds` also gets a job timer that creates the stop
   file the steps declare (`Step.stop_file`), and steps that declare
   `Step.restart_data` a `GOLDILOCKS_FROM_STEP` resume switch; only the
   phonon tasks have either.
6. `service.to_bundle_input(advice, steps, submission_script, ctx, *, code,
   hpc, assignments, source)` assembles a `bundle.BundleInput`: the rendered
   input file(s), each selected element's UPF and the table's licence
   (`licences/<table-id>.txt`), read through the installation's verified
   inventory (`service._pseudo.pseudo_artifacts`), the submission script,
   every advisor decision as a tri-state record (`advice.records()`), the
   advice's warnings
   (`advice.warnings()`), and the request it answers (`bundle.RequestIdentity`,
   the manifest's `request`): the code, the task (each `to_bundle_input*`
   names its own), the HPC profile, the goldilocks-core version, the
   overrides as submitted (the `assignments` `build_overrides` received) and
   the input structure's name, format, sha256 and size (`source`, a
   `NormalizedStructure.source`). `BundleInput.request` has no default, so no
   bundle is built without it. Records stay typed until
   they are published: `resolution.records_document` projects them once, for
   the HTTP/MCP responses, CLI `--json` and `goldilocks.json` alike, each with
   its whole `Provenance`, and `resolution.collect_citations` reads what the
   bundle cites off the same records.
7. `bundle.publish(bundle_input, output)` / `bundle.bundle_files(bundle_input)`
   / `bundle.archive_bytes(bundle_input)` write a directory (`DirectoryOutput`)
   or ZIP (`ArchiveOutput`), or return an in-memory preview.

`explain` (CLI, HTTP `POST /explain` and the MCP `explain` tool) is the
task's `advise` -> `check` (`advise_dos()` -> `check_dos()` for `dos`,
`advise_band()` -> `check_band()` for `band`, `advise_phonon()` ->
`check_phonon()` for the phonon tasks): every
decision plus `blocking`, the findings `run` would refuse to generate an input
for (as finding documents; the CLI prints each with its remedies' `--set`
flags), without rendering anything. Its `layout`, which `run`'s JSON summary carries too, names
each record's tier -- `analysis` (the structure alone) or `system` (shared by
every step) -- or step. Every advice type's `tiers()` (`service.RecordTiers`)
gives both its flat `records()` and that `layout`, so the two list the same
records. CLI's `run` calls all five of the task's functions, then
`bundle.publish()` or the preview.
Omitting `-o/--out` gives a memory-only preview (file names and byte sizes
only, nothing written); a directory path publishes a directory; a path
ending in `.zip` publishes an archive. HTTP's `POST /run` takes a
`respond_with: "archive"` field to get ZIP bytes back instead of a JSON
summary (`server/http.py`).

`advise()` is the one-step case of `service/_pipeline.py`'s internal
`advise_steps`, which diagnoses every `pw.x` step of a task together. The
`dos` task asks it for an `scf` and an `nscf` step via
`service.advise_dos`/`check_dos`/`generate_dos` (`service/_dos.py`), rather
than any generic graph: nothing about resolving one step's own settings
changes between an scf task and dos's scf/nscf steps, so both steps get the
same per-step advisors and the same request overrides. The nscf step also gets
the dos task's protocol (`StepProtocol`, `service/_step_protocol.py`): a tier
of its own, below the request and above the ML tier for that step only, whose
values read `heuristic` with the protocol in `source_note`. Analysis and
system advice run once, and the steps share one job, because they run one
after another in one allocation: it is sized over both steps, and each
`pw.x` step gets its own `max_seconds` share of the walltime, since `pw.x`
counts `max_seconds` from its own start. `dos.x` runs in what is left.
The `band` task asks it for an `scf` and a `bands` step
(`service.advise_band`/`check_band`/`generate_band`, `service/_band.py`).
The bands step's advice is a `PathStepAdvice` (`service/_step_kpath.py`),
which holds the band path of the written cell (`advisors/k_path.py`) in
place of a k-mesh, the scf step's occupations, and its own band count and
convergence. The band task's protocols withhold the moment a compensated
ordering would pin on the scf step and ask for three times the occupied
bands on the bands step. `generate_band` then appends one `bands.x` step per
spin channel, which has no advisor or settings and runs in what is left.
`relax`/`vc-relax` similarly get `advise_relax`/`check_relax`/
`generate_relax` (`service/_relax.py`), asking `advise_steps` for their one
step and adding one more resolved decision (`relax`) on top.

The three phonon tasks share `service/_phonon.py`, whose `TASK_PHASES` rows
bind `advise_phonon`'s `task` with `functools.partial`. `advise_phonon` asks
`advise_steps` for the task's first step alone -- `scf`, `relax` or
`vc-relax`, which keeps its pw.x purpose, so everything keyed on that
purpose applies unchanged -- under `phonon_step_protocol`, then
`service/_phonon_steps.py`'s `phonon_steps_advice` decides the rest on that
step's `Advice`: the `relax` record of a relaxation, the dense FFT grid ph.x
accepts (`advisors/fft_grid.py`), the q-point mesh
(`advisors/q_sampling.py`), the ph, q2r and phonon_dos steps' records, and
the dispersion step's path (`advisors/phonon.py`): `dispersion_path` takes
the band path of the written cell (`advisors/k_path.py`) and, where the
first step's occupations are fixed and the q2r record has no `loto_2d`,
lists each Γ inside a branch twice and makes each segment into Γ land on it
exactly. `PhononAdvice.tiers()` puts `relax` and `fft_grid` with the first
step and the others under the `ph`, `q2r`, `phonon_dos` and `dispersion`
steps, the dispersion's path as `k_path`, the name of the band task's bands
step's path. The phonon protocol uses three `StepProtocol` fields.
`phonon_k` is not a tier: it carries the ph step's q request and constrains
the first step's k-mesh after every tier (`advisors/k_sampling.py`).
`job_timer` is task-level: `_step.steps_advice` reads it from whichever
step's protocol declares it, and the job then sets `timer_seconds` in place
of every step's `max_seconds` share. `relax` is the relaxation's
`forc_conv_thr`, a tier above Quantum ESPRESSO's default; `advise_steps`
does not read it, so `_phonon_steps.py` passes it to `relax_settings`
itself. d3hess.x, ph.x, q2r.x and matdyn.x have no `advise_steps` advice;
`generate_phonon` writes them after the first step
(`generation/quantum_espresso/phonon.py`), d3hess.x exactly when the first
step writes DFT-D3, on one `SharedContext`.

## Understand the pipeline phases

Every task runs the same fixed order — `advise` -> `check` -> `generate` ->
`render_submission` -> `to_bundle_input` -> `publish` — described above.
Inside `advise()` itself, the three phases are:

- **Analyze** (`service/_analysis.py`, backed by `analysis/`: `composition.py`,
  `geometry.py`, `is_magnetic.py`, `is_metal.py`, `local_moments.py`,
  `needs_correlation.py`, `needs_soc.py`, `symmetry.py`) reports structure
  facts. `local_moments.py` is the open-shell model behind `is_magnetic`'s
  heuristic tier, and `is_metal.py`'s composition rule, `all_metallic`, also
  decides which compositions the phonon tasks' metallicity refusal spares.
- **System advice** (`service/_system.py`, backed by system-scoped advisors in
  `advisors/` such as `functional.py`, `hubbard_u.py`, `vdw_method.py`,
  `boundary.py`, `magnetic_config.py`) recommends system-wide parameters,
  including pseudopotential-table selection via `advisors/pseudo_selection.py`
  and `service/_pseudo.py`. It starts with the simulated cell
  (`service/_magnetic.py`): `magnetic_config.magnetic_cell` resolves spin
  polarization, spin-orbit coupling and a magnetic spin-orbit run's moment
  direction, and applies the requested magnetic ordering, the only enumlib
  call, which can replace the input with a different cell;
  `magnetic_config.framed_cell` then writes that cell in the frame where pw.x
  keeps the most of its point group (`pw_symmetry.pw_frame`). Table selection
  then reads the cell's spin-orbit switch, and
  `magnetic_config.magnetic_config` seeds the cell's moments from the
  selected z_valence. Everything after that -- the electron count, the step
  advice, the gate and the writer -- reads that one cell object, so no count
  describes a cell other than the one written.
- **Step advice** (`service/_step.py`, split into `service/_step_kpoints.py`
  for occupations/k-mesh/bands/convergence, `service/_step_kpath.py` for a
  bands step's band path in place of the k-mesh, and
  `service/_step_resources.py` for the job/parallelisation, backed by
  per-step advisors such as `advisors/k_sampling.py`, `advisors/k_path.py`,
  `advisors/nbnd.py`, `advisors/occupations.py`, `advisors/convergence.py`,
  `advisors/cutoffs.py`, `advisors/job_resources.py`,
  `advisors/parallelisation.py`, `advisors/n_irr_k.py`, `advisors/relax.py`)
  recommends per-step parameters. Resources are task-level: one job
  (`advisors/job_resources.py`) takes the fewest nodes on which pw.x's
  estimated memory per process fits for the layout every step will run
  (`advisors/size.py`, a port of pw.x's own memory report), splits the
  walltime into per-step `max_seconds` shares (`max_seconds_by_step`), or,
  when a step's protocol declares a job timer, sets `timer_seconds` instead,
  and publishes that memory in its record; each step's `npool`/`ndiag` then
  follow from that job's `ntasks`. A phonon task decides its other steps'
  records after these phases (`service/_phonon_steps.py`, above).

There is no generic "stage" or "graph executor" abstraction. Each phase is a
plain typed function call; `Advice` composes the three phases' own
dataclasses (`analysis`, `system`, `step`) rather than one flat dataclass, so
no single module needs to import every advisor's types directly. Every
advisor degrades independently (`Resolved`/`Unavailable`/`Blocked`, see
`resolution.py`) when it cannot decide its field, and lets a fault
propagate; only `checks.py` decides whether a request may proceed to
`generate()`.

## Find the code to change

Paths below are relative to `src/goldilocks_core/` unless stated otherwise.

| Area                | Files and responsibility                                                                                                                                                                                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Core types          | `resolution.py`: the `Resolved`/`Unavailable`/`Blocked` tri-state and `Provenance`/`Source`, used everywhere; `steps.py`: `Step`/`SharedContext`, with each step's completion check, stop file and restart data; `step_settings.py`/`system_settings.py`: the settings dataclasses `generate()` builds (`PwSettings`, whose `dfpt_system_keywords` hold a phonon first step's `nr1`-`nr3` and `dftd3_threebody`; `PhSettings`, `Q2rSettings`, `MatdynSettings` and `DispersionSettings` for the phonon steps); `plan.py`: `PlannedStep`/`expand_task`, multi-step task planning. There is no centralized `contracts` package any more — importing `goldilocks_core.contracts` is a ruff-banned API; import from the module that defines the name instead. |
| Orchestration       | `service/_pipeline.py`: `advise()`/`check()`, and `advise_steps`, which advises every `pw.x` step of a task with one shared job; `service/_generate.py`: `generate()`, the hard-fail boundary; `service/_dos.py` / `service/_band.py` / `service/_relax.py` / `service/_phonon.py`: the dos, band, relax and phonon task variants; `service/_phonon_steps.py`: what a phonon task decides on its first step's advice; `service/_step_protocol.py`: each task's protocols for its steps; `service/_tasks.py`: `TASK_PHASES`, each task's service functions, which every transport dispatches through; `service/_bundle.py`: submission rendering and bundle assembly; `checks.py`: the sole cross-parameter hard-fail gateway. |
| Input and discovery | `inputs/structure.py`: structure normalization and inspection; `capabilities.py`: available codes, tasks, settings, pseudopotential tables, HPC profiles, and warnings — reflected from the override dataclasses and advisor warning catalogues, not hand-listed.                                                        |
| Scientific behavior | `analysis/`: structure facts (`composition.py`, `geometry.py`, `is_magnetic.py`, `is_metal.py`, `local_moments.py`, `needs_correlation.py`, `needs_soc.py`, `symmetry.py`); `advisors/`: the recommendation layer (`boundary.py`, `convergence.py`, `cutoffs.py`, `electron_count.py`, `fft_grid.py`, `functional.py`, `hubbard_u.py`, `job_resources.py`, `k_path.py`, `k_sampling.py`, `magnetic_config.py`, `n_irr_k.py`, `nbnd.py`, `occupations.py`, `parallelisation.py`, `phonon.py`, `pseudo_selection.py`, `q_sampling.py`, `relax.py`, `size.py`, `species_split.py`, `vdw_method.py`, `dos.py`, `warning_catalogue.py`); top-level `kmesh.py`: k-point mesh ladder math, which also meshes a phonon task's q-points and phonon DOS; top-level `pw_symmetry.py`: the symmetry operations pw.x keeps in a cell as written (with which `advisors/n_irr_k.py` counts k-points and `irreducible_kpoints` reduces the q-point mesh) and the frame the cell is written in; top-level `pw_fft.py`: pw.x's dense FFT grid, ph.x's test of it, the grid ph.x accepts and the cells on which pw.x's own grid can fail ph.x. |
| Assets              | `assets/`: installation and integrity (`AssetStore`); `ml/models.py`: model declarations (loading plumbing only — no advisor calls it yet, see below); `assets/pseudopotentials/registry.py` and `assets/pseudopotentials/importers.py`: table declarations and provider normalization; `service/_pseudo.py`: the one place in the pipeline that touches the asset store/filesystem, resolving the installed asset, loading its manifest, narrowing it to a structure's elements, and reading the selected UPF headers' projector counts for the memory estimate. |
| Output              | `generation/`: target-code writers (`generation/quantum_espresso/scf.py`, `relax.py`, `dos.py`, `bands.py`, `phonon.py`, `namelists.py`); `submission/slurm.py`: the submission script, with each step's completion check, the job timer and the resume switch; top-level `bundle.py`: manifest assembly and directory/ZIP publication, replacing v1's separate `input_data.py`/`publication.py`/`serialization.py` roles.                                                                                                                        |
| Transports          | `cli/core.py`: local commands; `server/documents.py`: request/response pydantic models; `server/_handlers.py`: the one shared request-validation/dispatch implementation both `server/http.py` and `server/mcp.py` call; `server/readiness.py`: cached asset checks.                                                     |
| Browser             | Repository `web/src/api/`: HTTP client and generated types; `web/src/workspace/`: draft, request, result, and download state.                                                                                                                                                                                              |

## Extend a workflow

### Add a task

There is no generic task-registration API or graph to define. Multi-step
ordering is described by `plan.py`'s `PlannedStep`/`expand_task`, and each
task's functions by one row of `service/_tasks.py`'s `TASK_PHASES`. To add
a task:

1. Add it to `types.CalcTask`, the one task list: the CLI's `--task`
   choices, the request documents, `capabilities.py` and
   `set_overrides.build_overrides` read it.
2. Give it a row of steps in `plan.py`'s `expand_task` table. Their
   purposes are also the step names `set_overrides.build_overrides` routes
   settings to (`steps.<step>.<key>`), and `capabilities.py` derives each
   setting's `tasks` from them. A new `pw.x` step purpose joins
   `capabilities.py`'s `_PW_STEPS`; when its run has its own SCF loop, also
   `plan.SCF_LIKE_PURPOSES` and `capabilities.py`'s `_SCF_LOOP_STEPS`, and
   when it runs on a k-mesh, `_MESH_STEPS`. A new group of step settings is
   a `StepOverrides` field (`service/_step.py`) whose class
   `capabilities._leaves()` walks, with its steps in
   `capabilities._BRANCH_STEPS` and its class in `set_overrides._STEP_CLASSES`,
   as `KPathOverrides` is for the band task's bands step and the phonon
   tasks' dispersion step, and `PhOverrides`, `Q2rOverrides` and
   `PhononDosOverrides` for the phonon tasks' ph, q2r and phonon_dos steps.
3. Add a `service/_<task>.py` module. Its `advise_<task>` calls
   `_pipeline.advise_steps` with one entry per `pw.x` step (purpose -> that
   step's `StepOverrides`, from `RunOverrides.for_steps`, in run order) -- one
   for a single-step task, like `service/_relax.py`, or several, like
   `service/_dos.py`'s `scf` and `nscf` and `service/_band.py`'s `scf` and
   `bands` -- and a `StepProtocol` (`service/_step_protocol.py`) for each step
   whose defaults the task sets itself. A step of another program gets its
   records from its own advisors on that advice, as `service/_dos.py` decides
   the `dos.x` settings and `service/_phonon_steps.py` a phonon task's q-point
   mesh, ph.x, q2r.x and matdyn.x settings and dispersion path.
   `advise_steps` returns one `Advice` per step, all sharing the same
   analysis, system advice and job, so the submission script is rendered
   from that one job, which holds every step's `max_seconds` share, or the
   timer of a protocol's `job_timer` (`JobDecision.timer_seconds`).
   `_step.steps_advice` picks each step's
   advice by its purpose: a k-mesh (`service/_step_kpoints.py`), or a band
   path for a `bands` step (`service/_step_kpath.py`). Its `check_<task>`
   checks each step with that step's purpose, which `checks.py`'s
   step-specific rules read, and its `generate_<task>` calls
   `_generate.generate` once per `pw.x` step with that step's purpose, then
   appends the steps of any program without settings, as `generate_band`
   appends `bands.x`'s, or calls the writer of its other steps, as
   `generate_phonon` calls `write_qe_phonon`.
4. Give the task its row in `service/_tasks.py`'s `TASK_PHASES`: its
   `advise_<task>`/`check_<task>`/`generate_<task>`/
   `render_submission_<task>`/`to_bundle_input_<task>` functions, which
   `explain` and `run` on every transport look up there (`cli/_explain.py`,
   `cli/_run.py`, `server/_handlers.py`). Tasks that differ only in a
   parameter share functions, bound with `functools.partial`, as the three
   phonon rows bind `advise_phonon`'s `task`. A task without a row in either
   table raises `KeyError` rather than running another task's steps or
   functions, and unit tests hold both tables to `types.CalcTask`. Export
   the functions from `service/__init__.py`'s `__all__`, describe the task
   in `capabilities.py`'s `_tasks()`, and name it in the descriptions of the
   MCP `explain` and `run` tools (`server/mcp.py`).

### Add an input writer

Implement the writer as a function in `generation/quantum_espresso/` (or a
new `generation/<code>/` package for a new code) taking the resolved
`SystemSettings`/`PwSettings` and a `SharedContext`, and returning `Step`s
(see `steps.py`). There is no `(code, task, writer)` registry — dispatch is a
direct Python reference in `service/_generate.py` (`write_qe_bands` for a
`bands` step, otherwise
`write_qe_relax if purpose in ("relax", "vc-relax") else write_qe_scf`), or
in a task's module, as `service/_phonon.py` calls `write_qe_phonon`.
Wire a new writer into `service/_generate.py` or the relevant
`service/_<task>.py` module the same way. Writers should reject unsupported
combinations before rendering, rather than inventing scientific choices —
per `generation/quantum_espresso/scf.py`'s own governing invariant,
"generation never makes a scientific choice, only translation and
formatting." The writers today cover all eight tasks: `write_qe_scf`,
`write_qe_relax`, a DOS writer (`generation/quantum_espresso/dos.py`), the
band task's `write_qe_bands` and `write_qe_bands_x`
(`generation/quantum_espresso/bands.py`), and the phonon tasks'
`write_qe_phonon` (`generation/quantum_espresso/phonon.py`: d3hess.x, ph.x,
q2r.x, and matdyn.x for the phonon DOS and the dispersion, whose path rows
`bands.py`'s `path_rows` renders, as it does the bands step's
`K_POINTS crystal_b` card). `write_qe_relax` and `write_qe_bands` render
their namelists and cards with `scf.py`'s helpers, so `bands.in`, written
from the same `SystemSettings` as `scf.in`, repeats every keyword of it that
defines the Hamiltonian. The phonon tasks' first step adds `nr1`-`nr3` and
`dftd3_threebody` through `PwSettings.dfpt_system_keywords`, which
`scf.py`'s `system_keywords` unpacks into `&SYSTEM`, so `relax.in` and
`vc-relax.in` get them too.
A writer sets `Step.ntasks` when its program cannot use the whole allocation
(the DOS, `bands.x`, `d3hess.x`, `q2r.x` and `matdyn.x` steps set 1);
`submission/slurm.py` then launches that step on that many tasks instead of
every task the job allocates. Every
`Step` also declares how the script decides it finished (`Step.completion`,
from `steps.py`): `pw.x` steps use `ExitStatusCheck`, which passes only if
`<outdir>/<prefix>.save/data-file-schema.xml` was rewritten during the step
with `exit_status` 0; `dos.x`, `bands.x`, `d3hess.x`, `q2r.x` and
`matdyn.x`, which write no status file, use `StdoutMarkerCheck` (`JOB DONE`
in their stdout); and `ph.x` uses `DynamicalMatricesCheck`, which passes
only on exit code 0 and a complete dynamical matrix for every q-point
`<fildyn>0` lists, since ph.x's exit code alone says nothing. A `Step` can
also declare `stop_file`, the file that stops its program cleanly when a
job timer creates it (the ph.x writer declares `<prefix>.EXIT`, which pw.x
reads too), and `restart_data`, what its program resumes from when rerun
(ph.x's `<outdir>/_ph0` and `<prefix>.dyn*`); `submission/slurm.py` renders
the job timer and the `GOLDILOCKS_FROM_STEP` resume switch from them.

### Add a model or pseudopotential table

Keep scientific metadata and provider-specific preparation in the
pseudopotential registry (`assets/pseudopotentials/registry.py`). Table
selection and requirements-building live in `advisors/pseudo_selection.py`
(`select_pseudopotential_table`, `pseudo_requirements`,
`select_metadata_for_elements`); `service/_pseudo.py` is the one place that
combines table selection with `AssetStore` acquisition, manifest loading, and
per-element narrowing behind one function, keeping asset-store-shaped types
out of `_system.py`'s own import surface. The per-request result lives on
`Advice.system.pseudo` (a `PseudoAdvice`) as an ordinary `FieldState`.

`AssetStore` (`assets/store.py`) handles acquisition, integrity, on-disk
staging, and verified path resolution for any installable asset — table
pinning today is only via `--set pseudo_table_id=...` against the registry's
15 built-in tables; there is no user-supplied local UPF directory feature.
Installation is explicit through `goldilocks assets install`/`status`/
`verify` or the CLI's `--fetch-missing` retry; scientific operations never
install assets themselves.

The `default` asset profile also installs four ML models
(`models/qrf-kpoints`, `models/metallicity-cgcnn`,
`models/is-metal-classifier`, `models/is-magnetic-classifier`) alongside the
pseudopotential table. `analysis/is_metal.py`, `analysis/is_magnetic.py`, and
`advisors/k_sampling.py` all call through `ml.predict` (`predict()` for the
two classifiers, `predict_k_distance()` for `qrf-kpoints`), which resolves
the registered asset via `AssetStore` and loads it once per process through
`goldilocks_ml.inference.load_model()`. Each caller falls back to its next
tier only when the model is not set up: its asset is not installed or fails
checksum verification, or, for `is_magnetic`, the mMACE backbone (installed
with its asset, or named by `GOLDILOCKS_MACE_BACKBONE`) is missing or `mace`,
`e3nn` or `sphericart` is not installed. Any other error loading or running a model
fails the request (see `ml/predict.py`).

Independent assets install concurrently with at most eight workers. Results
retain profile order; each asset retains its own lock, checksum verification,
staging directory, and atomic publication. See
[pseudopotential tables](pseudopotentials.md) for layout and licensing
requirements.

## Preserve the boundaries

- **Validate at entry and side effects.** Input constructors validate domain
  controls; transport models (`server/documents.py`) reject unknown fields
  and incorrect types; provider adapters validate imported data. Internal
  advisor/generation functions are trusted to return coherent values.
- **Keep pipeline state request-local.** There is no long-lived service
  object whose lifecycle needs managing: each HTTP/MCP request calls plain
  functions from `service/`, building whatever `AssetStore`/`HpcProfile` it
  needs from configuration for that call. `server/_handlers.py` holds the one
  shared request-validation/dispatch implementation both `http.py` and
  `mcp.py` call; `server/readiness.py`'s `AssetReadiness` caches
  asset-availability checks (used by `GET /ready`) across requests.
- **Publish through one implementation.** `service/_bundle.py`'s
  `assemble_bundle_input` takes the pseudopotential files from
  `service/_pseudo.py`'s `pseudo_artifacts`, the only producer of
  `pseudopotential` artifacts: each selected UPF and, beside them, the table's
  `LICENSE.txt` as `licences/<table-id>.txt` (role `licence`), so no bundle
  ships a UPF without its licence. It reads each file once through the
  installation's verified inventory (`InstalledAsset.read_bytes`) and raises
  `AssetCorrupt` for one that no longer matches it, so a UPF's bytes are those
  its `pseudopotentials` record hashes. `bundle.py` hashes every artifact while
  assembling the `goldilocks.json` manifest, and writes the same in-memory
  bytes it hashed — never rereading a source after hashing. `README.md` and
  `CITATIONS.md` describe the manifest key by key from the keys it is written
  with (`bundle._MANIFEST_KEYS`), so neither claims one it lacks; a new
  manifest key needs a description there and a `schema_version` bump. Publication uses a
  completion-marker protocol, not v1's staging-directory-plus-atomic-rename:
  `target.mkdir()` (directories) or an exclusive `open(path, "xb")` (archives)
  claims the destination, raising `FileExistsError` if it already exists;
  every byte is written; a `.complete` marker file is written strictly last.
  Any consumer must call `bundle.is_complete(target)` before trusting a
  directory/archive — a killed process (SIGKILL/OOM) can leave a
  real-but-incomplete directory behind with no exception ever raised, an
  explicitly accepted trade-off versus v1's staging approach, which made that
  physically impossible.
- **Cite what the records cite.** Every `Provenance` field is published
  (`ResolvedField` forbids keys it does not declare, so a new one cannot be
  dropped silently). A record an ML model decided carries the model's
  evidence (`ml.predict.MlPrediction`: goldilocks-ml id, registry asset,
  details and warnings as returned) and its `ml/registry.toml` citation; the
  `pseudo_table` record carries the selected table's. A bundle's
  `CITATIONS.md` and manifest `citations` are every record's citations;
  `CITATIONS.md` also names each `licence` file, which carries per-family
  references the records do not. ML model licence material is not shipped:
  bundles do not contain the models.
- **Label each record from what its advisor consumed.** The `magnetic`,
  `occupations`, `k_sampling`, `hubbard`, `convergence`, `relax` and `dos`
  decisions, the `k_path` of a band task and of a phonon task's dispersion,
  and a phonon task's `q_sampling`, `phonon`, `q2r` and
  `phonon_dos`, build their `Provenance` with `resolution.field_sources_from` and
  `Provenance.from_field_sources`, from the settings they applied and the
  inputs they read, so a setting reads `human` exactly when the request set
  it and the decision kept it, and `source` is the highest tier among them.
  The other decisions that apply several settings (`cutoffs`, `job`, `nbnd`,
  `parallelisation`, `vdw`) still stamp one record-level `source` and
  publish no `field_sources`, so their `human` means only that the request
  set at least one of their settings. A rule that follows another record
  keeps `heuristic` and names that record in `derived_from` rather than
  copying its tier.
- **Say where each value is published.** `/capabilities` gives every setting
  a `resolved_in`: the record of the decision it feeds and the path of its
  value in that record, or no path where the record holds none (an
  input-only knob such as `extra_bands`). A response's `layout` gives each
  record's tier and step. Clients read a setting's value, its tier and a
  record's place from these, never by matching setting names to record
  names.
- **Keep remote callers away from local paths.** HTTP and MCP accept inline
  structures and registered table IDs, not filesystem sources, model
  locations, or publication paths. Published records name no local path
  either: a field annotated `Portable()` (`PseudoMetadata.filepath`,
  `ModelSpec.location`) never reaches them, and a `pseudopotentials` record
  names each UPF by `table_id`, `asset_path` and `content_sha256`, so two
  machines with the same assets publish the same records. Keep authentication
  and deployment controls explicit; see
  [CLI transport security](cli.md#http-security).
- **Keep imports direct.** Package code imports from the module defining a
  name. The top-level `goldilocks_core` package deliberately exports
  nothing; library users import directly from `goldilocks_core.service`
  (`advise`/`check`/`generate`, the `dos`/`band`/`relax`/`phonon` task
  variants and `TASK_PHASES`),
  `goldilocks_core.cli`, or `goldilocks_core.server`.
- **Classify expected failures once.** Domain exceptions implement
  `ExpectedFailure` from `failures.py` with a category and safe public
  description (e.g. `AdviceIncomplete` in `service/_generate.py`,
  `AssetNotInstalled`/`AssetCorrupt` in `assets/store.py`). Adapters classify
  failures for remote callers from this vocabulary; unexpected execution
  defects propagate.

## Complexity gates

`scripts/check_complexity.py` runs in contributor checks, hooks, and CI. Its AST
import ceiling applies to every production owner: 12 project origin modules and
24 imported symbols by default, with tighter limits for the thin transports
`cli.core`, `server.http` and `server.mcp`, and raised ones for `checks`,
`service._system`, `service._dos`, `service._phonon`,
`service._phonon_steps`, `service._step`, `service._tasks` and
`advisors.warning_catalogue` (the modules whose own orchestration or
aggregation role needs more imports than the default ceiling allows).
It counts local and type-only imports, resolves re-exports, and counts accessed
module-alias members. Pure export packages are transparent to consumer counts.
The same gate runs Ruff's McCabe check: at most 10 per production function,
ignoring `noqa` suppressions. Reduce decisions and duplication; moving import
blocks or extracting shallow helper fleets does not deepen an interface.

## Change the HTTP or browser contract

`server/documents.py` converts strict request models directly into native Core
inputs and derives response schemas from domain-owned shapes and `Portable`
annotations. `server/_handlers.py` serializes trusted Core results without
reconstructing response models — both `server/http.py` and `server/mcp.py`
call the same handler functions. HTTP's `POST /run` returns a JSON summary by
default, or ZIP bytes when the request body sets `respond_with: "archive"`.
Workbench reads file hashes and sizes from the ZIP's `goldilocks.json`.

Documents are strict JSON. HTTP's `/explain`, `/magnetic-orderings` and `/run`
bodies, CLI `--json` output and `goldilocks.json` raise on a non-finite float
instead of writing `Infinity`, `NaN` or a silent `null`. Records therefore
never hold one: a bound or value with no finite number is `None` (for example
the upper end of the Gamma-only mesh's `k_distance_interval`), and the
override models reject `inf` and `nan`. MCP's text content, which pydantic
serializes and would write as `Infinity`, depends on the same rule.

There is no per-transport service object to own. `server/readiness.py`'s
`AssetReadiness` caches asset-availability checks (used by `GET /ready`)
across requests within one running process.

Requests run concurrently on threads (FastAPI's threadpool, MCP's
`asyncio.to_thread`), so no request may change process-wide state such as the
working directory. pymatgen's enumlib caller `chdir`s the whole process, so
magnetic-ordering enumeration runs on one long-lived worker process
(`worker_process.py`), one call at a time, in a private temporary directory
(`advisors/magnetic_enumeration.py`). mace sets torch's default dtype for the
whole process, which breaks float32 models built on other threads, so the
server and CLI processes never import it: `is_magnetic` predictions run on a
second long-lived worker (`ml/mace_process.py`), which is replaced by a fresh,
warmed one once it has been idle for 30 s after a structure of more than 16
atoms, since only its exit releases the memory a prediction leaves behind
(`WorkerProcess.replace_when_idle`, #260). Each mMACE ordering
ranking relaxes its candidates on a process of its own, one call per candidate
and one ranking at a time (`advisors/magnetic_ordering_ml.py`). Over HTTP a
ranking is a job: `server/ranking_jobs.py` queues them in order on one runner
thread, reports each job's queue position and progress, and kills a cancelled
job's process. The Workbench static root is resolved to
an absolute path once, when the app is created.

Workbench keeps the editable draft and reviewed response in its browser store.
The Analysis card offers an override control for a fact only when
`/capabilities` marks it `overridable`, and shows the others, such as
`needs_soc`, read-only.
It places records by the response's `layout`: the Analysis card shows the
analysis tier; the Advisors card shows every other record with the settings
whose `resolved_in` names it, or read-only after them, a multi-step task's
per-step records (a `dos` task's `nscf_` records, a `band` task's `bands_`
records and `k_path`, a phonon task's records of each step, such as its
first step's `fft_grid` and its dispersion step's `k_path`) under their
step. Each
setting control shows the value its `resolved_in` path leads to, captioned
with the tier that produced that value: the record's per-setting source, or
its own source -- except a record-level `human`, which another of the
record's settings caused. A setting without a recorded value has no caption.
Opening another structure keeps the draft's code, task, HPC profile and the
overrides of settings that `/capabilities` does not mark `structure_specific`;
it clears the structure-specific overrides and every fact override, and the
Advisors card lists what it cleared until dismissed.
Opening a structure or editing the draft starts a new revision, and each
`/explain` and preview `/run` outcome, result or failure, is stored with the
structure and revision it was sent for; only the current revision's outcomes
decide what is shown, sent or saved. Workbench sends the current draft's
`/explain` automatically. Once its recommendation has arrived with an empty
`blocking` verdict, Workbench fetches that draft's archive from `/run` as the
generated-inputs preview; a draft whose verdict blocks gets no `/run`, and the
Bundle card lists the findings, each its `summary` with its full `message`
behind a details toggle, and every remedy as a button that applies its
override patch to the draft. Its title asks the user to confirm one setting
per finding when every finding has a remedy, and says that no input files can
be generated otherwise. The findings of the current draft, from its `/explain`
verdict or its refused `/run`, also put one line under each control their
`fields` name, pointing to the Bundle card, and that control's Advisors group
then reads blocked (#223). A failure is the outcome of its draft: nothing
is sent again until the draft or the structure changes or the user presses
Retry, which every failure offers. Dismiss only hides the banner; the Bundle
card still shows the failure. Download saves the previewed archive of the
current draft and sends no request of its own: it stays disabled, and says why,
until that archive has arrived, and retrying a failed preview refreshes the
preview without saving a file.
A magnetic-ordering listing is stored with the structure it was requested for
and shown only while that structure is open. Opening another structure aborts
a listing still in flight, and Download selected builds and names each
candidate bundle from the listing's own structure. A failed listing keeps its
error on the card and is sent again only by its Retry listing button.

After changing the wire contract, run these from the repository root with the
HTTP extra installed:

```bash
npm --prefix web run generate:api
```

`web/openapi.json` and `web/src/api/schema.d.ts` are ignored build products.
Frontend lifecycle commands regenerate them from the local Python package;
generation needs neither a running server nor installed model assets. Commit
the domain declarations, not generated copies. Docker exports OpenAPI in its
Python stage and generates TypeScript in its Node stage.

## Run browser tests

Start the [built Workbench](https://github.com/stfc/goldilocks-core/blob/main/web/README.md#run-locally) in another terminal,
then run:

```bash
npm --prefix web exec -- playwright install chromium
npm --prefix web run test:e2e
```

Tests use `http://127.0.0.1:8000`; they do not start a server.
`WORKBENCH_BASE_URL` selects another address.
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` selects an existing Chromium installation.
