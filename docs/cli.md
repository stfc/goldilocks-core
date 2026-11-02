# CLI reference

For installation and a first calculation, follow the
[quickstart](quickstart.md).

## Common commands

Replace `structure.cif` with your CIF or POSCAR:

```bash
uv run goldilocks inspect structure.cif --json
uv run goldilocks explain structure.cif --json
uv run goldilocks run structure.cif --out silicon-run
```

`inspect` reports structure metadata, including the site labels a
`starting_magnetization` takes. `explain` runs analysis and every
advisor, printing each decision and its source (`human`, `ml`, `llm`, or
`heuristic`), then a `notice: <message>` line for each setting given without a
step that reached several steps, then the checks `run` applies, printing one
`blocked: <message>` line for each finding `run` would refuse to generate an
input for, followed by a `try:` line per remedy that resolves it: the `--set`
flags to use, each in place of any `--set` of the same key, then
`remove --set KEY` for each override to drop, since `--set` cannot clear a
key. `run` prints the same `blocked:` and `try:` lines on stderr
when it refuses. `explain` never writes anything, even without `--json`, and
exits 0 whether or not it is blocked.
`run` generates a complete runnable input (Quantum ESPRESSO by default) and
publishes it to `silicon-run` because `-o/--out` was given; omit `-o/--out`
for a memory-only preview instead. Use `uv run goldilocks --help` or a
subcommand's `--help` for full syntax.

`run` and `explain` share the same seven flags: the `structure` path,
`--code`,
`--task {scf_single_point,dos,band,relax,vc-relax,phonon,relax-phonon,vc-relax-phonon}`,
`--hpc`, `--set KEY=VALUE` (repeatable), `--config FILE.toml`, and `--json`;
both also accept `--fetch-missing`, and only `run` additionally accepts
`-o/--out`. `--task` is validated against the eight listed choices; `--code`
is passed through unchecked — only `quantum_espresso` is a registered code
today, so an unrecognised `--code` silently produces a Quantum-ESPRESSO-shaped
bundle instead of failing.

`uv run goldilocks capabilities --json` dumps the same full payload HTTP's
`GET /capabilities` and the MCP `capabilities` tool return: `codes`, `tasks`
(with descriptions, step counts, and executables), `facts`, `settings`,
`pseudopotential_tables`, `hpc_profiles`, `models`, `warnings`, and `sources`.
Narrower slices are also available directly:

- `uv run goldilocks settings --json` — every `--set`-able key, its type,
  default, and sources: `{"settings": [...], "facts": [...]}`, the same
  objects as `capabilities`'s `settings[]` and its overridable `facts[]`
  (`is_metal`, `is_magnetic`, ...); run this command for the current key
  count rather than trusting a number in these docs.
- `uv run goldilocks models --json` — every model `ml/registry.toml`
  registers, whether or not it is actually installed (see [Scientific
  controls](#scientific-controls)).
- `uv run goldilocks assets status --json` — installed pseudopotential-table
  and model assets.

See [Serve HTTP](#serve-http) and [Serve local MCP](#serve-local-mcp) for the
HTTP/MCP equivalents. `uv run goldilocks examples path` locates the bundled
example structures.

## Save output or print JSON

`explain` never writes anything, regardless of flags — it has no `-o/--out`.
`run` writes only when you pass it:

| Flag                  | Output                                                        |
| --------------------- | -------------------------------------------------------------- |
| `-o/--out DIRECTORY`  | Publish a new calculation directory (must not already exist)   |
| `-o/--out FILE.zip`   | Publish the same contents as a ZIP archive                     |
| (omit `-o`/`--out`)   | Memory-only preview to stdout; nothing is written to disk      |

Explicit destinations must not already exist; `run` raises an error rather
than overwrite one. Without `-o/--out`, `run` always builds the full bundle in
memory and prints a preview listing each file's path and byte size — there is
no auto-picked output directory (v1's `goldilocks_out`, `goldilocks_out_1`, …
naming no longer exists in any form).

A bundle's `goldilocks.json` records the request it answers under `request`:
`--code`, `--task`, the HPC profile used, the goldilocks-core version, the
overrides as submitted (`--config` then `--set`, typed, with any
`steps.<step>.` prefix) and the structure file's name, format, sha256 and size.
HTTP and MCP `run` record the same block for the same structure and overrides.

`--json` changes the shape of `run`'s output rather than being combined with
an output flag: without `-o/--out` it prints `{"files": [...], "records":
{...}, "warnings": [...], "layout": {...}}`; with `-o/--out` it prints
`{"files": [...], "kind": "directory"|"archive", "path": "..."}`. `explain
--json` prints `{"records": {...}, "warnings": [...], "blocking": [...],
"layout": {...}}`, where `blocking` lists the findings `run` would refuse to
generate an input for, one per root cause, and is empty when its checks pass.
Each finding is `{"code", "fields", "message", "remedies", "summary"}`: a
stable `code` (`advice.blocked` for a decision that could not be made, whose
`message` is the root cause), the settings it concerns, the full text to show,
the override patches that each resolve it, where `null` clears that override,
and a summary of the decision it asks for in at most 200 characters. `layout` names
each record's tier and step: `analysis` (what the structure alone decides),
`system` (what every step shares), then `steps`, one `{"name", "records"}`
per step of the task in run order -- the task's one `job` with its first step,
a `dos` task's nscf decisions under their `nscf_` names, a `band` task's
bands-step path as `k_path` and its other decisions under their `bands_`
names, and a phonon task's `fft_grid` (and, for a relaxation, `relax`) with
its first step, then `q_sampling` and `phonon` under `ph`, `q2r` under `q2r`,
`phonon_dos` under `phonon_dos` and the dispersion path as `k_path` under
`dispersion`. Every record is in exactly one list.
`warnings` holds every record's warnings, for every task, each as `{"code",
"level", "category", "message", "record"}`, where `record` names the record
it came from (`nscf_parallelisation` for a `dos` task's nscf step,
`bands_parallelisation` for a `band` task's bands step), then the request's
routing notices under the `record` `overrides` (below); `goldilocks.json`
carries the same list.

`--json` output and the published `goldilocks.json` are strict JSON: a value
with no finite number is `null`, never `Infinity` or `NaN`. For example, the
Gamma-only mesh (`k_index` 1) holds for every k-distance above its lower
bound, so its `k_distance_interval` is `[low, null]`.

A command writes only its own output to stdout: the `--json` document, or the
plain-text report without `--json`. Anything else printed while it runs, such
as the notice `mace` prints when it loads, output from a C extension, or a
child process's output, goes to stderr, so `--json` output always parses as
one JSON document. `serve` is the exception: `serve mcp` speaks JSON-RPC on
stdout itself.

## Scientific controls

Defaults are Quantum ESPRESSO single-point SCF, PBEsol, and efficiency-tier
pseudopotentials. See [scientific conventions](conventions.md) for numerical
defaults and override rules.

Every scientific parameter is reached through `--set KEY=VALUE` (repeatable)
or `--config FILE.toml` (same `KEY=VALUE` pairs, TOML-format, merged the same
way) — there are no dedicated per-parameter flags. `uv run goldilocks
settings` (or `--json`) is the single source of truth for every override key,
its type, default, and description; a selection of commonly used keys:

| Setting                             | Meaning                                                              |
| ------------------------------------ | --------------------------------------------------------------------- |
| `functional`                        | Exchange-correlation functional (default `PBEsol`)                    |
| `pseudo_table_id`                   | Pin a registered pseudopotential table id instead of automatic selection |
| `is_metal`, `is_magnetic`           | Correct a classification: `metal`/`non_metal`, `magnetic`/`non_magnetic` (the record's own values, not `true`/`false`) |
| `k_grid`                            | Explicit Monkhorst-Pack mesh, e.g. `--set 'k_grid=[8,8,8]'`            |
| `k_distance`                        | Target k-point spacing along each periodic axis; axes the point group mixes share the larger count, and a vacuum axis always gets one k-point (heuristic default 0.15 for metals or when metallicity is unknown, 0.30 for a confirmed non-metal) |
| `smearing_type`                     | Smearing function when `occupations=smearing`: `gaussian`, `mp` (Methfessel-Paxton), `cold` (Marzari-Vanderbilt) or `fd` (Fermi-Dirac); default `cold` |
| `degauss`                           | Smearing width in Ry (default 0.01)                                   |
| `spin_polarized`, `spin_orbit_coupling` | Force spin polarization / spin-orbit coupling; `spin_orbit_coupling` is the only SOC switch (the `needs_soc` fact is read-only advice) |
| `moment_direction`                  | Lattice direction of the uploaded cell the moments of a magnetic spin-orbit run start along, e.g. `--set 'moment_direction=[1,1,0]'` (default `[0,0,1]`) |
| `use_vdw`, `method`                 | Force a dispersion correction; only `d3bj` is implemented, for PBE and PBEsol |
| `isolation`                         | Electrostatic boundary: `periodic`, `slab` (Quantum ESPRESSO's 2D truncation, `assume_isolated='2D'`) or `isolated` (Martyna-Tuckerman); see [boundary conditions](science.md#check-boundary-conditions-and-vacuum) |
| `conv_thr`, `mixing_beta`, `electron_maxstep` | SCF energy-convergence threshold, density-mixing factor, max SCF iterations |
| `u_by_element`                      | Hubbard U_eff per element in eV, replacing the built-in table, e.g. `--set 'u_by_element={"Ti": 4.0}'` |
| `hubbard_needs_correlation`         | `false` runs without Hubbard +U; `true` applies the built-in U table  |
| `hubbard_projectors`                | Projectors of the HUBBARD card when an element gets +U: `ortho-atomic` (default) or `atomic`, the only type the phonon tasks run +U with; see [Hubbard +U](science.md#check-hubbard-u) |
| `forc_conv_thr`                     | Force threshold of a relaxation in Ry/Bohr: Quantum ESPRESSO's 1e-3 for `relax` and `vc-relax`, 1e-4 for the relaxation of `relax-phonon` and `vc-relax-phonon`, where a looser value gets a warning |
| `delta_e`, `emin`, `emax`, `broadening`, `ngauss` | `dos.x` settings of the `dos` task: energy step and window in eV, broadening in Ry, broadening function (`-99`, `-1`, `0`..`10`; `dos.x` reads it only with a broadening width, so it needs `broadening` unless the nscf step uses smearing) |
| `k_path_distance`                   | Largest spacing between neighbouring points of the high-symmetry path of a `band` task's bands step and a phonon task's dispersion step, in 1/Å with 2π included (default 0.025); see [the band structure path](science.md#check-the-band-structure-path) |
| `q_grid`, `q_distance`              | A phonon task's ph.x q-point mesh: an explicit Γ-centred mesh, e.g. `--set 'q_grid=[4,4,4]'`, or a spacing in 1/Å with 2π included (default 0.3); see [the phonon tasks](science.md#check-the-phonon-tasks) |
| `tr2_ph`, `alpha_mix`, `nmix_ph`    | ph.x's linear-response threshold, mixing factor and number of mixed iterations (defaults 1e-18, 0.4 and 8) |
| `asr`                               | Acoustic sum rule of q2r.x and matdyn.x: `simple` (default) or `crystal`; see [the phonon tasks](science.md#check-the-phonon-tasks) |
| `dos_q_distance`                    | Spacing of the mesh matdyn.x interpolates a phonon task's phonon DOS on, in 1/Å with 2π included (default 0.10) |

Each setting applies to the steps that read it, and `goldilocks settings
--json` lists them (`tasks`, `steps`, `scope`). A task's steps are named by
purpose: `scf` (`scf_single_point`); `relax`; `vc-relax`; `scf`, `nscf`,
`dos` (`--task dos`); `scf`, `bands`, `bands_x` (`--task band`: pw.x
with `calculation='bands'`, then `bands.x`); and `scf`, `relax` or
`vc-relax`, then `ph`, `q2r`, `phonon_dos`, `dispersion` (`--task phonon`,
`relax-phonon` and `vc-relax-phonon`: the first pw.x step, then ph.x,
q2r.x, and matdyn.x for the phonon DOS and for the dispersion, with
`d3hess.x` before ph.x under DFT-D3).

- A step setting given as `KEY=VALUE` reaches every step of the task it
  applies to. On a `dos` task, `k_grid` sets both the scf and the nscf step,
  with an `overrides.applies_to_multiple_steps` notice naming them: a
  `notice:` line in `explain`'s text output, and a `warnings` entry with
  `record` `overrides` in `--json` output and `goldilocks.json`. The SCF-loop
  settings (`mixing_beta`, `mixing_mode`, `mixing_fixed_ns`,
  `electron_maxstep`) set the scf step only: the nscf step runs no SCF loop,
  so pw.x does not use them there.
- A `band` task's bands step runs its band path with the scf step's
  occupations and no SCF loop, so the k-mesh settings (`k_grid`,
  `k_distance`, `k_index`, `shift`), `occupations`,
  `smearing_type`, `degauss` and the SCF-loop settings set its scf step
  only, without a notice, and `k_path_distance` sets its bands step only.
  `nbnd`, `extra_bands`, `conv_thr`, `npool` and `ndiag` reach both pw.x
  steps, with the notice.
- A phonon task's first step is its only pw.x step, so the pw.x settings
  (the k-mesh, occupations, SCF-loop, `conv_thr`, `nbnd`, `npool` and
  `ndiag` settings) set it without a notice, and ph.x runs with its
  `npool` and `ndiag`. The relaxation settings reach the first step of
  `relax-phonon` and `vc-relax-phonon`. `q_grid`, `q_distance`, `tr2_ph`,
  `alpha_mix` and `nmix_ph` set the `ph` step, `asr` the `q2r` step,
  `dos_q_distance` the `phonon_dos` step and `k_path_distance` the
  `dispersion` step, each without a notice. `d3hess.x` takes no setting and
  is not a step a key can name.
- `steps.<step>.KEY=VALUE` sets one step only and wins over the plain key for
  that step: `--task dos --set 'k_grid=[10,10,10]' --set
  'steps.nscf.k_grid=[30,30,30]'` gives the scf 10×10×10 and the nscf
  30×30×30, and `--task band --set steps.bands.nbnd=40` gives the bands step
  40 bands and leaves the scf step's default. In `--config`, a `[steps.nscf]`
  or `[steps.bands]` table does the same. A plain key that every step it
  applies to also sets this way would reach no step, and is refused.
- System settings (functional, cutoffs, magnetism, ...) describe the system
  every step runs on, and the job settings (`partition`, `nodes`, `ntasks`,
  `walltime_h`, `account`) the one allocation all of a task's steps run in:
  both are set once per task, and `steps.<step>.` is refused for them.
- A setting no step of the task reads is refused (exit 2, HTTP 422): `press`
  and `cell_dofree` apply to a `vc-relax` step only (the `vc-relax` and
  `vc-relax-phonon` tasks), `nstep`, `etot_conv_thr` and `forc_conv_thr` to
  `relax` and `vc-relax` steps, the `dos.x` settings to `dos`,
  `k_path_distance` to `band` and the phonon tasks, and the other ph.x, q2r.x
  and matdyn.x settings to the phonon tasks. So is `steps.<step>.KEY` for a
  step that does not read it, such as `steps.nscf.mixing_beta`,
  `steps.bands.k_grid`, `steps.bands.occupations`, `steps.ph.k_grid` or
  `steps.phonon_dos.k_path_distance`, and any `steps.bands_x.KEY`:
  `bands.x` takes no setting. A step the task does not have is refused too:
  `steps.scf.KEY` on `relax-phonon`, whose first step is `relax`.

Each setting's `structure_specific` says whether its value is a judgement
about the structure it was set for — its elements, magnetism, geometry, size
or k-mesh, such as `k_grid`, `u_by_element`, `starting_magnetization` or
`spin_orbit_coupling` — rather than a method, accuracy or job choice, such as
`functional`, `conv_thr` or `account`. When another structure is opened, the
Workbench keeps the values of the settings that are not structure-specific
and clears the others and every fact override (`is_metal`, ...).

Each setting's `resolved_in` says where `explain` and `run` publish its
resolved value: `record`, the record of the decision it feeds, and `path`,
the keys of its value inside that record's `value`. Most settings resolve in
their group's record under their own name (`conv_thr` in
`convergence.conv_thr`, and `k_path_distance` in `k_path.k_path_distance`,
the path of a `band` task's bands step or of a phonon task's dispersion
step); `functional` is the `functional` record itself
(`path` `[]`), `pseudo_table_id` resolves in `pseudo_table.id`,
`spin_orbit_coupling` in `magnetic.spin_orbit_enabled`, `magnetic_ordering`
in `magnetic.ordering.applied` (`null` for a run without spin polarization,
which applies no ordering), `moment_direction` in
`magnetic.moment_direction.uvw`, `k_grid` in `k_sampling.mesh`,
`hubbard_projectors` in `hubbard.projectors` (`null` without +U) and
`q_grid` in `q_sampling.mesh`. `path` is `null` where the record holds no
value of the setting: `extra_bands` only shifts `nbnd`, and
`hubbard_needs_correlation` and `u_by_element` decide which U values the
`hubbard` record lists.

Quote `--set` values that contain brackets or braces (e.g. `--set
'k_grid=[8,8,8]'`) so the shell does not glob-expand them; array and object
values must be valid JSON. Numbers must be finite: `inf`, `nan` and values
that overflow, such as `1e999`, are rejected as invalid settings. See
[Pseudopotentials](pseudopotentials.md) for how tables are chosen, pinned, and
checked for compatibility.

`is_metal`, `is_magnetic`, and `k_distance` (v2 epic 11) each resolve through
a `human > ml > llm > heuristic` priority: `explain --json`'s
`records[...].source` says which tier actually produced a value, and
`records[...].field_sources` which tier produced each setting of a compound
record (a `--set shift=...` reads `human` beside QRF95's `ml` `k_distance`).
When a model decided the value or one of its settings, `records[...].model`
names the model (`model_id`, and `asset`, the
installed release as `<id>@<version>`) and keeps what it returned
(`details`, such as a classifier's `score` and `threshold` or QRF95's
`interval`, and `warnings`), and `records[...].citations` says what to cite.
`is_metal`/`k_distance` become ML-backed once their PSDI-hosted asset is
installed (`uv run goldilocks assets install <id>` — see [Install and check
assets](#install-and-check-assets)); `is_magnetic` additionally needs `mace`,
`e3nn`, `sphericart`, and `ase`, none of which install via a `pip`/`uv`
extra of this project or of goldilocks-ml -- see [mMACE setup](mmace-setup.md)
for a complete, copy-pasteable walkthrough (also covered in [goldilocks-ml's
own README](https://github.com/stfc/goldilocks-ml#use-the-is_magnetic-classifier))
for the manual install (the `mace` fork it needs has no PyPI release, and
PyPI's own upload validation rejects a package that declares a direct git
dependency regardless, so this can never become an automatic extra). It
also needs the same `GOLDILOCKS_MACE_BACKBONE` checkpoint the [magnetic
orderings](#magnetic-orderings) `--rank-with-mmace` flag uses below --
confirmed empirically (2026-09-21): the published record declares no
automatic download for its mMACE backbone, so `is_magnetic` reuses
whichever checkpoint that variable already points at rather than fetching
a second copy. A model that is not set up (its asset not installed or
failing verification, or for `is_magnetic` the packages or checkpoint
missing) leaves the value to the next tier. Once a model is set up, an error
loading or running it fails the command instead of being replaced by the
heuristic answer. `is_magnetic` runs in a separate worker process, so mMACE
never changes the torch settings of the command or server that asked for
it. There is still no flag to point `run`/`explain` at a custom
model file of your own. `uv run goldilocks models --json` reports every
model, installed or not, so it also confirms whether one you expect to
be usable actually is.

## Submit and resume a phonon job

A phonon task's `submit.sh` runs all its steps in one job: the first pw.x
step, `d3hess.x` under DFT-D3, `ph.x`, `q2r.x`, and `matdyn.x` for the
phonon DOS and again for the dispersion. No input carries `max_seconds`.
Instead the script starts a timer that creates `pwscf.EXIT`
(`<prefix>.EXIT`) in the working directory at `job.timer_seconds`, 95% of
`walltime_h`, and pw.x or ph.x, whichever is running, stops cleanly there.
The script deletes a leftover `pwscf.EXIT` before the first step and stops
the timer when it ends. The other tasks' scripts have no timer: their pw.x
inputs keep their `max_seconds` share of the walltime
(`job.max_seconds_by_step`).

The script checks every step and stops with a `goldilocks:` line on stderr
when one did not finish. The ph step passes only when ph.x exited with 0 and
wrote a complete dynamical matrix for every q-point `pwscf.dyn0` lists.
Otherwise the message names why ph.x stopped (the job timer, a linear system
that did not converge, or its exit code) and the q-points still without a
matrix, and the next line gives the command that resumes the job at the ph
step:

```bash
sbatch --export=ALL,GOLDILOCKS_FROM_STEP=ph submit.sh
```

`d3hess.x`, `q2r.x` and both `matdyn.x` steps pass when their output says
`JOB DONE`. These programs exit non-zero on an error, so the script's
`set -e` ends the job at that step's launch, before its check, and no
`goldilocks:` line is printed: the error is in the step's output, such as
`dispersion.out`, and in `CRASH`, or, for a Fortran runtime error such as a
missing `pwscf.fc`, in the job's own output file.

`GOLDILOCKS_FROM_STEP` names the step the job starts at, the first when it
is unset. It must be one of the job's step names, which the script lists in
`goldilocks_steps` (`relax d3hess ph q2r phonon_dos dispersion` for a
`relax-phonon` task under DFT-D3); any other value, an empty one too, stops
the script before a step runs.
The steps before it are skipped, so a resumed job never repeats the
relaxation, and ph.x continues from the data its earlier run saved in
`out/_ph0` and the dynamical matrices it wrote.
`GOLDILOCKS_FROM_STEP=dispersion` reruns the dispersion alone, on one task,
from the `pwscf.fc` the earlier job wrote: after a `dispersion.in` written
again for another `k_path_distance`, for instance. A job that starts at the
first step, as a plain `sbatch submit.sh` does, deletes `out/_ph0` and
`pwscf.dyn*` before it runs anything, since they belong to the save that
step rewrites. A resumed job starts a new timer on its own walltime. A pw.x
step the timer stopped cannot resume: its message says to raise
`walltime_h`. Only the phonon tasks' scripts read `GOLDILOCKS_FROM_STEP`;
the other tasks ignore it. See
[running and resuming phonons](science.md#check-the-phonon-tasks) for why.

## Magnetic orderings

```bash
uv run goldilocks magnetic-orderings structure.cif --json
uv run goldilocks magnetic-orderings structure.cif --rank-with-mmace
```

Lists a ferromagnetic guess plus any antiferromagnetic
candidates `enumlib` finds (see [Check magnetism and spin-orbit
coupling](science.md#check-magnetism-and-spin-orbit-coupling)) for a
human or agent to choose among before generating any input file. Each
candidate is named by its label (`fm`, `afm-1`, `afm-2`, ...), and its
`--json` `overrides` generate it, spin-polarized, from the same structure
file:

```bash
uv run goldilocks run structure.cif --hpc scarf --set magnetic_ordering=afm-2
```

The run enumerates again, applies the candidate of that label through the
same steps as `magnetic_ordering=afm` (which applies `afm-1`, the smallest
and most symmetric), and records the label in `records.magnetic` next to the
cell's formula and atom count, with why it was written (`criterion`) and
the other candidates of its size (`alternatives`). For a slab, wire or
molecule in a box, only candidates that keep its vacuum vectors are listed
and applied, so every label writes one slab with the uploaded vacuum.

`--rank-with-mmace` relaxes every candidate's magnetic moments on a frozen
mMACE potential energy surface and recommends the lowest energy-per-atom
one -- needs both a `GOLDILOCKS_MACE_BACKBONE` environment variable
pointing at a downloaded mMACE checkpoint file, and the same manual
`mace`/`e3nn`/`sphericart`/`ase` install described above. Missing either,
or an error inside the relaxation itself, degrades to an unranked listing
with a warning. Each ranking runs in its own process, one ranking at a time,
so a long ranking never holds up `explain` or `run`; a ranking process that
dies fails the request.

## Install and check assets

```bash
uv run goldilocks assets install default
uv run goldilocks assets status default
uv run goldilocks assets verify default
```

Use a profile, asset ID, or table ID. `default` installs the four prediction
models (`qrf-kpoints`, `metallicity-cgcnn`, `is-metal-classifier`,
`is-magnetic-classifier`) and a PBEsol efficiency PseudoDojo table;
`workbench` installs all registered models and tables. `install` also
repairs corrupt installations.

`run --fetch-missing` (or `explain --fetch-missing`) installs a missing
pseudopotential table instead of failing, then retries; it does not apply to
any other kind of missing dependency. See
[asset storage](pseudopotentials.md#find-stored-assets) for locations.

## Serve HTTP

```bash
uv run goldilocks assets install workbench
uv run --extra http goldilocks serve http
```

The server defaults to **http://127.0.0.1:8000**. `--host` and `--port` change
the address. `--static-root DIRECTORY` also serves a built Workbench; a relative
`DIRECTORY` is resolved against the launch directory once, at startup.

| Endpoint            | Purpose                                                                          |
| ------------------- | --------------------------------------------------------------------------------- |
| `GET /capabilities` | Codes, tasks, facts, settings, pseudopotential tables, HPC profiles, models, warnings |
| `POST /inspect`     | Structure inspection (inline `structure_content`, not a path)                     |
| `POST /explain`     | Analysis and advisor decisions with their `layout`, plus `blocking`: the findings `/run` would refuse with; never writes anything |
| `POST /run`         | Generate a runnable input; `respond_with: "json"` (default) returns a JSON summary, `respond_with: "archive"` returns ZIP bytes; a refusal is a 422 `advice_incomplete` with the findings in `error.details.findings` |
| `GET /health`       | Process health                                                                     |
| `GET /ready`        | Asset readiness; 503 for missing or corrupt assets                                |
| `GET /openapi.json` | Request and response schemas                                                      |

Interactive API documentation is at `/docs`.

### HTTP security

Keep the default localhost binding for local use. The server has no built-in
authentication; restrict network access with a firewall or authenticated reverse
proxy before exposing it. Configure TLS and request limits there.

HTTP and MCP accept inline structures and registered table IDs, not local
structure paths or publication paths. Server operators control installed
assets. `/run` never writes to the server's disk: on request it can return
ZIP bytes directly (`respond_with: "archive"`) or a JSON summary (the
default), but it always builds and serves the bundle in memory.

## Serve local MCP

Configure your MCP client to launch this command from the repository root:

```bash
uv run --extra mcp goldilocks serve mcp
```

The stdio tools are `capabilities`, `inspect_structure`, `explain`, and `run`.
MCP's `explain` tool returns the same `records`, `warnings`, `blocking` and
`layout` as `POST /explain`; when `run` refuses, its error lists the same
findings, each followed by its remedies as JSON override patches. MCP's `run`
tool never writes to the server's
filesystem — it always returns only the published file list, every resolved
decision (with its source) and their `layout`, and a warnings array the caller
must relay verbatim. To obtain actual file bytes, use the CLI (`goldilocks run
... -o/--out`) or the HTTP transport's `/run` endpoint with `respond_with:
"archive"`.
