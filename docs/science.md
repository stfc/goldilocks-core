# How recommendations are made

This page explains what happens between "here is a structure" and "here is a
runnable input": which stage decides each parameter, what model or rule it
uses, and how to tell a measured choice from a guess. Every recommendation
also carries its own provenance at runtime; this page is the map of those
sources.

The pipeline is a dependency graph of stages:

```text
Load -> Analyze -> Advise
Load -> Kmesh
Load + Advice -> Select
Load + Advice + Select + Kmesh -> Generate
Analysis + Advice + Kmesh + Select + Generate -> DFT Input Data
```

Each stage produces a record. `recommend` collects analysis, advice, k-points,
and selection; `generate` additionally renders input files and binds the
complete bundle.

## Structure analysis

The analysis stage reports what the structure *is*: formula, lattice, sites,
space group, dimensionality, and electronic character. Facts first — no
parameter decisions happen here.

Dimensionality comes from pymatgen's CrystalNN/Larsen analysis. Electronic
character — `metal` or `insulator` — comes from the metallicity model, or
from a conservative composition heuristic when the model is absent or the
structure is disordered. See the [scientific conventions](conventions.md) for
the exact fallback behavior.

## K-points: the QRF model

Without an explicit `k_grid` or `k_spacing` hint, the k-mesh stage consults
the installed quantile-random-forest model (`qrf-kpoints@QRF95`). The model
predicts a k-point distance — an effective spacing — from structural and
composition features (site-connected SOAP descriptors, lattice, and the
metallicity classification), and the mesh follows from the VASP `KSPACING`
convention described in the [conventions page](conventions.md).

Two rules bound the model:

- an explicit `k_grid` wins over `k_spacing`, and either hint bypasses the
  model completely — no model load, fully deterministic;
- the recommendation carries provenance naming the model and its prediction,
  so it is always distinguishable from a fixed default or your own hint.

## Smearing from electronic character

The smearing advice reads the electronic character from analysis:

- **metal** → `cold` smearing with a width of 0.01 Ry;
- **unknown character** → fixed occupations, and a warning asking you to
  verify.

The default model classifies silicon as metallic (confidence ≈ 0.5), so the
quickstart example gets cold smearing. Provenance makes that visible; the
confidence, the fallback warnings, and `--smearing-type` or
`CalculationHints(smearing_type=...)` exist so you can check and override any
classification you disagree with.

## Convergence defaults

Convergence settings are package defaults, not model predictions:
`conv_thr = 1e-6` Ry, `mixing_beta = 0.4`, `electron_maxstep = 80`. They are
recorded in the advice document with `source: default`, and every one can be
overridden by hint.

## Dispersion

Dimensionality drives the vdW policy: a 3D bulk structure gets no dispersion
correction by default; a low-dimensional structure enables D3BJ, because
layered and molecular systems need it and it is cheap. Both decisions are
visible in the advice document, and `use_vdw` / `vdw_method` override them.

## Spin-orbit coupling

SOC is never enabled automatically. Structures containing period-5-and-heavier
elements get `spin_orbit.consider = True`; enabling it is always your
decision, because SOC multiplies cost and changes the required
pseudopotentials. When you do enable it, the pseudopotential requirements
demand fully relativistic files — see the
[conventions page](conventions.md#spin-orbit-coupling).

## Pseudopotentials

Selection is deterministic: given the requested functional, accuracy tier,
relativistic treatment, and the structure's elements, the core resolves a
compatible registered table and picks each element's file and cutoffs from
it. PseudoDojo is preferred for ordinary elements; lanthanides and actinides
require SSSP tables, because PseudoDojo's lanthanide table freezes 4f
electrons in a trivalent ion and no PseudoDojo table covers actinides. The
cutoffs come from the table — the core does not tune them. The full policy,
table list, and licensing model are in
[Pseudopotential tables](pseudopotentials.md).

## Reading provenance

Every recommendation sub-document carries a `provenance` block:

```text
"provenance": {
    "source": "analysis",
    "reason": "Model-classified metallic systems benefit from modest smearing.",
    "confidence": null,
    "data_source": null,
    "warnings": []
}
```

| `source` | Meaning |
| --- | --- |
| `default` | package default, no model or structure input involved |
| `analysis` | derived from structure analysis (including model classification) |
| `model` | predicted directly by a model asset |
| `lookup` | read from a registered table or manifest |
| `user_hint` | you set it; the stage only echoed the decision |

`confidence` is populated when a model produced the value. `data_source`
names the exact asset (for example, which pseudopotential table supplied a
cutoff). If you disagree with any recommendation, the override and its
provenance both land in the published `goldilocks.json`, so the decision
trail survives into your archive.

## Known limitations

- The metallicity model is a trained classifier. Verify surprising calls —
  the confidence and the `likely_metal` fallback warnings exist for exactly
  this reason. Composition-only heuristics are also a documented stand-in for
  future models; see issue #175 for the inventory.
- Dimensionality classification uses CrystalNN, which fails on some ordered
  structures; the failure is reported as a warning with the analysis.
- Cutoffs are table values, not per-system optimized values. Use a
  `precision` table when you need tighter converged cutoffs.
- Only Quantum ESPRESSO SCF generation exists today.