# Quickstart

This page takes you from a CIF file to a runnable Quantum ESPRESSO SCF
calculation, showing the real output at every step. It uses the CLI; the
[tutorial](tutorial.md) does the same through the Python API.

## Install the package and assets

```bash
uv sync
uv run goldilocks assets install default
uv run goldilocks assets verify default
```

`default` installs two models (a k-point model and a metallicity classifier)
and one PseudoDojo pseudopotential table:

```text
models/qrf-kpoints@QRF95: installed
models/metallicity-cgcnn@1: installed
pseudopotentials/pseudodojo-pbesol-efficiency-sr@0.4: installed
```

## Generate inputs for silicon

```bash
uv run goldilocks compute "$(uv run goldilocks examples path)/Si.cif" --preset generate --out run
```

The command prints what it produced:

```text
generated files:
  inputs/qe.in
published directory: /tmp/work/run
```

and writes a directory you can run immediately:

```text
run/
checksums.sha256
CITATIONS.md
goldilocks.json
inputs/qe.in
licences/models_metallicity-cgcnn-1.md
licences/models_qrf-kpoints-QRF95.md
licences/pseudodojo-pbesol-efficiency-sr.txt
pseudo/Si.upf
README.md
source/Si.cif
structure/canonical.cif
```

Everything `pw.x` needs is in there. The generated `run/inputs/qe.in` sets
`pseudo_dir = './pseudo'`, so run it from the publication root:

```bash
pw.x < run/inputs/qe.in
```

## What the input contains

The interesting part of `run/inputs/qe.in`:

```text
&SYSTEM
  ibrav = 0
  nat = 8
  ntyp = 1
  ecutwfc = 48
  ecutrho = 192
  occupations = 'smearing'
  smearing = 'cold'
  degauss = 0.01
/

&ELECTRONS
  conv_thr = 1.0000000000e-06
  mixing_beta = 0.4
  electron_maxstep = 80
/
```

None of these values were chosen arbitrarily, and none of them were chosen by
you. Each one comes from a stage that explains itself:

- `ecutwfc = 48` and `ecutrho = 192` come from the PseudoDojo
  `pbesol-efficiency-sr` table, selected per element;
- `smearing = 'cold'` with `degauss = 0.01` Ry because the installed
  metallicity model classified Si as metallic;
- `conv_thr`, `mixing_beta`, and `electron_maxstep` are package defaults for
  SCF convergence.

Every value also appears in `run/goldilocks.json` with provenance: which stage
decided it, from what source, and why. Override any of it with hints — see the
[CLI reference](cli.md) for the flags and
[How recommendations are made](science.md) for the reasoning behind each
default.

## See the recommendations without generating anything

`--preset recommend` runs analysis, advice, k-points, and pseudopotential
selection, and keeps the result in memory:

```bash
uv run goldilocks compute "$(uv run goldilocks examples path)/Si.cif" --preset recommend --no-out --json
```

With `--json`, the result is one document whose `records` map is keyed by
stable record IDs. The k-point recommendation for Si is a 6×6×6 grid:

```text
"k_points": { "grid": [6, 6, 6], ... }
```

and the pseudopotential selection names its source:

```text
"ecutwfc_ry": 48.0, "ecutrho_ry": 192.0,
"provenance": { "source": "lookup",
                "data_source": "pseudopotentials/pseudodojo-pbesol-efficiency-sr", ... }
```

## Where to next

- [Tutorial](tutorial.md) — the same workflow through the Python API, plus
  record selection and output targets
- [How recommendations are made](science.md) — what the models do and when to
  distrust them
- [Pseudopotential tables](pseudopotentials.md) — other functionals, SOC,
  lanthanides, and your own UPF files
- [CLI reference](cli.md) — every flag