# Goldilocks workflows

Use these canonical patterns before reading implementation files.

## Inspect a Structure Source

```python
from goldilocks_core.inputs.structure import PathStructureSource, normalize_structure

inspection = normalize_structure(PathStructureSource("structure.cif")).inspection

print(inspection["structure"]["reduced_formula"])
print(inspection["canonical_cif"])
```

## Diagnose a structure (advise)

```python
from goldilocks_core.inputs.hpc import load_hpc_profile
from goldilocks_core.inputs.structure import PathStructureSource, normalize_structure
from goldilocks_core.resolution import Resolved
from goldilocks_core.service import advise
from goldilocks_core.set_overrides import build_overrides

normalized = normalize_structure(PathStructureSource("structure.cif"))
structure = normalized.structure
hpc = load_hpc_profile("scarf")
assignments = {"k_grid": (4, 4, 4)}
overrides = build_overrides(assignments, task="scf_single_point")

advice = advise(structure, hpc=hpc, overrides=overrides)

records = advice.records()
print(records["functional"])
k_sampling = advice.step.kpoints.k_sampling
if isinstance(k_sampling, Resolved):
    print(k_sampling.value.mesh)
print(advice.warnings())
```

`build_overrides` routes each setting to the steps of `task` it applies to and
raises `InvalidSetting` for one no step of the task reads (`press` on an scf).

`advise()` always returns -- diagnosis degrades field-by-field
(`Resolved`/`Unavailable`/`Blocked`) rather than raising. `advice.records()`
returns every decision keyed by name, as the advisors' typed values;
`goldilocks_core.resolution.records_document(records)` projects them to the
JSON the CLI, HTTP, MCP and `goldilocks.json` publish. `advice.warnings()`
flattens every record's warnings into one list, each naming the record it came
from in `record`.

## Generate and publish a runnable input

```python
from goldilocks_core.bundle import DirectoryOutput, publish
from goldilocks_core.service import check, generate, render_submission, to_bundle_input
from goldilocks_core.steps import default_shared_context

report = check(advice)
if not report.ok:
    raise SystemExit(
        "blocked: " + "; ".join(finding.message for finding in report.blocking)
    )

ctx = default_shared_context()
steps = generate(advice, report, ctx=ctx)
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

publication = publish(bundle_input, DirectoryOutput("run-dir"))
print(publication["path"])
```

`to_bundle_input`'s keywords are the request the bundle answers, which
`goldilocks.json` records under `request` with the task and the goldilocks-core
version: pass the assignments given to `build_overrides` (the overrides as
submitted) and `normalized.source` (the structure's name, format, sha256 and
size).

`check()` never raises; always inspect `report.ok`/`report.blocking` before
calling `generate()`, which raises `AdviceIncomplete` on an incomplete
report rather than silently degrading (delivery has preconditions that
diagnosis does not). Each entry of `report.blocking` is a `Finding`: a stable
`code`, the settings it concerns (`fields`), a `message` to relay, and
`remedies`, override patches that each resolve it (a `None` value removes
that override from the assignments). Apply one and call `build_overrides`
again rather than guessing a fix from the message.

The destination must not exist. Use `ArchiveOutput("run.zip")` for a ZIP, or
skip `publish` entirely and call `bundle_files(bundle_input)` for a
memory-only preview. Directory and ZIP outputs contain the same logical
files: inputs, selected UPFs, a submission script, licences, citations, and
`goldilocks.json` (the request, records, warnings, citations, checksums).

CLI equivalents:

```bash
uv run goldilocks run structure.cif --hpc scarf --set 'k_grid=[4,4,4]' --out run-dir --json
uv run goldilocks run structure.cif --hpc scarf --set 'k_grid=[4,4,4]' --out run.zip --json
```

## Read only the records you need

`Advice`/`DosAdvice`/`BandAdvice`/`PhononAdvice` always compute every field;
there is no partial-record selection in v2 -- filter the dict
`advice.records()` returns instead:

```python
wanted = {"functional", "k_sampling", "cutoffs"}
subset = {name: state for name, state in advice.records().items() if name in wanted}
print(subset)
```

CLI equivalent (the full record set, since `explain`/`run` do not support
partial selection either):

```bash
uv run goldilocks explain structure.cif --hpc scarf --json
```

## Use a local pseudopotential root

```bash
uv run goldilocks run structure.cif --hpc scarf --set pseudo_table_id=my-local-table --out run-dir
```

The registered table's metadata must identify the real licence file and
citation before Core can publish local UPFs. Never invent missing cutoffs
or redistribution terms. See [Pseudopotentials](../../../../docs/pseudopotentials.md)
for how local tables are registered.

## Generate a multi-step task (DOS)

```python
from goldilocks_core.service import advise_dos, check_dos, generate_dos

dos_overrides = build_overrides({"steps.nscf.k_grid": (12, 12, 12)}, task="dos")
dos_advice = advise_dos(structure, hpc=hpc, overrides=dos_overrides)
dos_report = check_dos(dos_advice)
if dos_report.ok:
    dos_steps = generate_dos(dos_advice, dos_report, ctx=ctx)
    print([step.name for step in dos_steps])
```

`DosAdvice.records()` keys the shared system-level fields and the task's one
`job` unprefixed, the nscf step's own fields under `nscf_`, and the DOS
decision itself under `"dos"`; `dos_advice.tiers().layout()` names each
record's tier and step (scf, nscf, dos), which `explain`/`run --json` publish
as `layout`. The job splits 95% of `walltime_h` between the
scf and nscf inputs as `max_seconds` (`job.max_seconds_by_step`). Unless the
request sets them, the nscf step's k-point spacing and occupations come from
the dos protocol (aiida-quantumespresso `pdos.yaml`); those records read
`heuristic` with the protocol in `source_note`, never `human`.
`steps.<step>.<key>` sets one step (`scf`, `nscf`, or `dos` for the `dos.x`
settings `delta_e`, `emin`, `emax`, `broadening`, `ngauss`; `dos.x` reads
`ngauss` only with a broadening width, so it needs `broadening` unless the
nscf step uses smearing); a key without a step reaches every step it applies
to, with an `overrides.applies_to_multiple_steps` notice when that is both
`pw.x` steps.
CLI/HTTP/MCP equivalent: pass `task="dos"` (CLI: `--task dos`).

## Generate a band structure (band)

```python
from goldilocks_core.service import advise_band, check_band, generate_band

band_overrides = build_overrides({"k_path_distance": 0.05}, task="band")
band_advice = advise_band(structure, hpc=hpc, overrides=band_overrides)
band_report = check_band(band_advice)
if band_report.ok:
    band_steps = generate_band(band_advice, band_report, ctx=ctx)
    print([step.name for step in band_steps])

k_path = band_advice.records()["k_path"]
if isinstance(k_path, Resolved):
    print(k_path.value.lattice_type, k_path.value.n_kpoints, k_path.value.primitive_cells)
```

The steps are `scf`, `bands` (`pw.x` with `calculation='bands'` on a
`K_POINTS crystal_b` card) and `bands_x` (`bands.x`), or `bands_x_up` and
`bands_x_down` for a collinear spin-polarized run, all in one job.
`BandAdvice.records()` keys the shared system-level fields, the scf step's
own, the task's one `job` and `k_path`, the high-symmetry path of the
written cell (branches of labelled vertices in crystal coordinates of its
reciprocal vectors, with `n_kpoints`, `lattice_type` and `primitive_cells`),
unprefixed, and the bands step's other records under `bands_`:
`bands_occupations`, `bands_nbnd`, `bands_convergence` and
`bands_parallelisation`; `band_advice.tiers().layout()` names the steps scf
and bands, since `bands.x` has no records. Unless the request sets them, the
bands step takes `k_path_distance` 0.025 1/Å (2π included) and three times
the occupied bands from aiida-quantumespresso's `bands.yaml`; those records
read `heuristic` with the protocol in `source_note`. `k_path_distance`
reaches the bands step only, the k-mesh, occupations and SCF-loop keys the
scf step only, and `nbnd`, `extra_bands`, `conv_thr`, `npool` and `ndiag`
without a step both `pw.x` steps, with the
`overrides.applies_to_multiple_steps` notice; `steps.bands.<key>` sets the
bands step alone, and no key reaches `bands_x`. A conventional cell or a
supercell gives folded bands (`primitive_cells` above 1, notice
`k_path.folded_bands`). A molecule in a box is refused, and so is a
`tot_magnetization` on a collinear band task
(`occupations.bands_x_refuses_tot_magnetization`), which bands.x stops on.
CLI/HTTP/MCP equivalent: pass `task="band"` (CLI: `--task band`).

## Generate phonons (phonon, relax-phonon, vc-relax-phonon)

`advise_phonon(structure, task="relax-phonon", hpc=hpc, overrides=...)`, with
overrides built by `build_overrides(..., task="relax-phonon")`, advises a
phonon task; `check_phonon`, `generate_phonon`, `render_submission_phonon`
and `to_bundle_input_phonon` take its `PhononAdvice`, and
`TASK_PHASES[task]` holds all five with the task bound. The steps are the
first `pw.x` step (`scf` for `phonon`, `relax` for `relax-phonon`,
`vc-relax` for `vc-relax-phonon`), `d3hess` (`d3hess.x`) under DFT-D3, `ph`
(`ph.x` on a q-point mesh), `q2r` (`q2r.x`), `phonon_dos` (`matdyn.x`, the
phonon DOS) and `dispersion` (`matdyn.x` along the band task's path), all in
one job on one prefix and outdir.

`PhononAdvice.records()` keys the first step's records and the task's one
`job` unprefixed, with `fft_grid` (the dense FFT grid ph.x accepts; `written`
is the `nr1`-`nr3` the first step writes, or `null`) and, for a relaxation,
`relax`, then `q_sampling` (`mesh`, `n_irr_q`, `work`) and `phonon` for the
ph step, `q2r`, `phonon_dos` and `k_path`, the dispersion step's path: the
band task's path, except that on fixed occupations without
`isolation='slab'` each Γ inside a branch is listed twice and each segment
into Γ lands on it exactly, which its `source_note` says and `n_kpoints`
counts. Unless the request sets them, the q-mesh takes `q_distance` 0.3
1/Å, the ph.x settings `tr2_ph` 1e-18, `alpha_mix` 0.4 and `nmix_ph` 8, the
relaxation `forc_conv_thr` 1e-4 Ry/Bohr and the dispersion
`k_path_distance` 0.025 1/Å, from aiida-quantumespresso's protocols; those
records read `heuristic` with the protocol in `source_note`. The first
step's k-mesh is raised against the q-mesh (notice `phonon.k_mesh_raised`)
unless the request sets `k_grid`, `k_index` or `k_distance`. The job splits
no walltime: `job.max_seconds_by_step` is empty and `job.timer_seconds`, 95%
of `walltime_h`, is when `submit.sh` creates `<prefix>.EXIT`, where pw.x or
ph.x stops cleanly. The pw.x settings reach the first step only, `q_grid`,
`q_distance`, `tr2_ph`, `alpha_mix` and `nmix_ph` the `ph` step, `asr` the
`q2r` step, `dos_q_distance` the `phonon_dos` step and `k_path_distance` the
`dispersion` step; `steps.scf.<key>` is an unknown step in the relaxation
tasks. The gate refuses, with remedies,
+U without `hubbard_projectors=atomic`, spin-orbit coupling with +U,
`tot_magnetization` with smearing, a `q_grid` that breaks symmetry, a q-mesh
beyond q2r.x's limits, `fix_bottom_layers` and smearing or tetrahedra on a
composition that is not all-metallic unless `is_metal=metal` is set (a
requested `occupations=fixed` the run cannot take is refused under the same
code, and for a metal needs `is_metal=metal` with `occupations=smearing`), and,
with no remedy, a molecule or cluster in a box, whatever `isolation`, and
`vc-relax-phonon` on a fragile cell, where the FFT grid the vc-relax rebuilds
can fail ph.x's symmetry test (`relax-phonon` runs there). The metallicity refusal
(`phonon.metallicity_unconfirmed`) is the user's call: the classifier calls
many insulators metals, and ph.x treats a run on smearing as a metal, so ask
whether the material is a metal (`is_metal=metal`) or an insulator rather than
picking a remedy. An insulator needs fixed occupations, which
`is_metal=non_metal` alone does not always give: the message says why the run
is not on them, and every remedy it offers resolves it. Where it says the run
is collinear spin-polarized, ask for the insulator's integer moment
(`tot_magnetization`, which no remedy guesses) or whether it has no magnetic
moments (`is_magnetic=non_magnetic`, offered where that resolves it); where it
names an odd electron count, the material is a metal unless it is magnetic;
where the request sets smearing or tetrahedra, an insulator needs
`occupations=fixed`.

```bash
uv run goldilocks explain structure.cif --hpc scarf --task relax-phonon --json
uv run goldilocks run structure.cif --hpc scarf --task relax-phonon --set q_distance=0.2 --out run-dir
```

A stopped job prints `goldilocks:` lines naming why, and resumes at the ph
step, without repeating the relaxation, with
`sbatch --export=ALL,GOLDILOCKS_FROM_STEP=ph submit.sh`;
`GOLDILOCKS_FROM_STEP=dispersion` reruns only the dispersion, from the
`pwscf.fc` the job wrote. d3hess.x, q2r.x and matdyn.x stop the job
without a `goldilocks:` line when they fail: read their output
(`dispersion.out` for the dispersion) and `CRASH`.

## Optional transports

```bash
uv sync --all-extras
uv run goldilocks serve http --host 127.0.0.1 --port 8000
uv run goldilocks serve mcp
```

The CLI's `run`/`explain` commands and HTTP and MCP, which share
`server/_handlers.py`, look each task's functions up in
`service.TASK_PHASES` -- same `RunOverrides`/`CalcTask` validation, same
tri-state records and warnings shape, same eight tasks. HTTP and MCP accept
inline structure content; neither accepts filesystem paths, since a server
process should not read from the caller's local disk.
