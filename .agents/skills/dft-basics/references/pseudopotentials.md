# Pseudopotentials

Atoms contain tightly bound core electrons and chemically active valence electrons. Pseudopotentials replace the all-electron potential near the nucleus with an effective potential acting on the valence electrons, reducing computational cost.

## Pseudopotential and PAW types

Common dataset types:

| Type | Meaning | Typical consequence |
|------|---------|---------------------|
| NC / norm-conserving | Conserves valence norm outside the core region. | Often transferable and conceptually simpler, but usually needs higher wavefunction cutoffs. |
| Ultrasoft | Relaxes norm conservation and uses augmentation charges. | Often lower wavefunction cutoffs, but requires charge-density augmentation and separate charge-density cutoffs. |
| PAW | Projector augmented-wave dataset with information for reconstructing all-electron-like quantities near the core. | Often efficient and accurate, but dataset details and licensing matter. |

PAW retaining all-electron reconstruction information does **not** mean the calculation explicitly solves every core electron. In most practical PAW calculations, core electrons are still treated as frozen core. PAW is better understood as retaining more core-region/all-electron information than standard NC or ultrasoft pseudopotentials, not as a full all-electron calculation.

## Relativistic treatment is separate from pseudo type

NC, ultrasoft, and PAW datasets can each be generated with different relativistic treatments.

| Treatment | Meaning | Use |
|-----------|---------|-----|
| Non-relativistic | Does not include relativistic effects. | Less common in modern libraries; may be acceptable for some light-element cases. |
| Scalar-relativistic | Includes scalar relativistic effects such as mass-velocity and Darwin terms, but not explicit spin-orbit coupling. | Common default for many routine calculations. |
| Fully-relativistic | Includes ingredients needed for explicit spin-orbit coupling and noncollinear calculations. | Needed when doing SOC explicitly. |

Do not assume PAW automatically means fully-relativistic. Do not assume fully-relativistic automatically means PAW. They are different axes.

## Functional consistency

The exchange-correlation functional used to generate the pseudopotential should normally match the functional used in the DFT calculation:

- PBE pseudo with PBE calculation
- PBEsol pseudo with PBEsol calculation
- LDA pseudo with LDA calculation

Mixing functionals can sometimes be done deliberately, but Goldilocks should not recommend it silently.

## SSSP families

SSSP provides curated pseudopotential families for Quantum ESPRESSO workflows:

- **Efficiency** — selected to reduce cost while maintaining acceptable accuracy for screening and high-throughput work.
- **Precision** — selected for stricter accuracy, usually with higher cutoffs and greater computational cost.

When a user asks for speed, screening, or exploratory runs, Efficiency may be appropriate. When they ask for production accuracy, final energies, forces, or benchmark-quality work, Precision is usually safer.

## Cutoffs

Plane-wave pseudopotential calculations need cutoffs, usually:

- wavefunction cutoff, often `ecutwfc` in Quantum ESPRESSO
- charge-density cutoff, often `ecutrho` in Quantum ESPRESSO

Cutoffs should come from reliable metadata when possible. If metadata is missing, selection should emit a structured warning instead of letting a generator invent a quiet fallback.

Ultrasoft and PAW datasets often need a higher charge-density cutoff relative to wavefunction cutoff than norm-conserving datasets.

## Selection chain

Keep pseudopotential work in stages:

1. **Analyse** the structure and calculation target: elements, heavy elements, magnetic candidates, possible semicore needs, oxidation/valence concerns when known.
2. **Advise** on family, functional, and relativistic treatment.
3. **Select** concrete files for each element and derive cutoffs from metadata.
4. **Generate** target-code syntax from the selected files and cutoffs.

Generators should not choose pseudopotential families, relativistic treatment, or cutoffs. Those are scientific/numerical decisions.

## SOC gotchas

Spin-orbit calculations generally require fully-relativistic pseudopotentials or PAW datasets. A fully-relativistic file is not enough by itself: the target code must also be configured for SOC/noncollinear calculation.

For Quantum ESPRESSO, explicit SOC calculations usually require settings such as:

```text
noncolin = .true.
lspinorb = .true.
```

Whether scalar-relativistic and fully-relativistic pseudopotentials can be mixed is code- and setup-dependent. A conservative workflow selects a consistent relativistic treatment across all elements and validates the setup against the target code.

## Warnings worth preserving

Selection should warn when:

- no pseudopotential exists for an element in the requested family
- the requested functional is unavailable
- SOC is requested but fully-relativistic data is unavailable
- cutoff metadata is missing or incomplete
- a fallback family, functional, or relativistic treatment is used
- selected pseudopotentials mix treatments in a way the target code may not support
