# Smearing, SOC, and convergence

This reference covers physics-bearing defaults that often interact with k-points and pseudopotentials.

## Smearing

Metals have a Fermi surface where occupation changes abruptly from occupied to unoccupied states. Small energy changes can cause large occupation changes, which makes self-consistent-field convergence harder. Smearing smooths this transition.

Common choices:

| Choice | Meaning | Notes |
|--------|---------|-------|
| Fixed occupations / no smearing | Occupations are not smeared. | Appropriate for many insulators and semiconductors when band occupations are clear. |
| Gaussian | Simple smooth broadening. | Conservative and useful for testing. |
| Methfessel-Paxton | Polynomial smearing, common for metals. | Higher-order MP can produce negative occupations; first-order MP is common. |
| Cold / Marzari-Vanderbilt | Smearing designed for lower energy bias. | Often a good general-purpose metallic smearing. |

Typical starting guidance:

- Metallic system → cold smearing or first-order Methfessel-Paxton, width roughly `0.01–0.02 Ry` as a starting point for Quantum ESPRESSO.
- Insulating system → fixed occupations, or narrow Gaussian/cold smearing if convergence needs help.

The width matters:

- Too wide → occupations and energies can become unphysical.
- Too narrow → SCF may fail to converge or converge slowly.

Goldilocks should distinguish “likely metal” from “known metal” when the band structure is not known. Use warnings and provenance rather than pretending the structure alone answers everything.

## Spin polarization and magnetism

Magnetic elements or partially filled d/f shells can require spin-polarized calculations. Structure analysis can identify likely magnetic elements, but it cannot always know the correct magnetic ordering or initial moments.

Good advice should:

- flag likely magnetic candidates
- distinguish spin-polarized recommendation from exact magnetic ordering
- allow user hints to override spin assumptions
- avoid inventing detailed magnetic moments unless a source or explicit hint provides them

## Spin-orbit coupling

SOC can matter when electron spin couples strongly to orbital motion. It is especially relevant for heavy elements and for science questions involving band splittings, topology, magnetic anisotropy, or heavy-element chemistry.

First-pass relevance heuristic:

- period 5 and heavier elements are good SOC candidates
- lanthanides and actinides are strong candidates
- even one heavy element can make SOC relevant depending on the property of interest

Do not silently enable SOC just because a structure contains heavy elements. SOC often costs several times more than scalar-relativistic calculations and changes the required pseudopotential and code settings. Advice should usually say “consider SOC” with provenance and warnings.

SOC advice should connect to pseudopotential selection:

- explicit SOC → prefer fully-relativistic pseudopotentials or PAW datasets
- scalar-relativistic baseline → scalar-relativistic datasets are often appropriate
- target-code setup must also enable SOC/noncollinear calculation where required

## Convergence thresholds

DFT calculations are iterative. Convergence parameters control when the self-consistent loop stops.

Common parameters:

- **Energy convergence threshold** — in Quantum ESPRESSO, `conv_thr` is in Ry. `1e-6 Ry` is a common default-level threshold; tighter values are used for precision work.
- **Force convergence threshold** — in Quantum ESPRESSO, `forc_conv_thr` is in Ry/bohr. `1e-3 Ry/bohr` is a common default-level threshold for relaxation.
- **Maximum SCF steps** — larger or harder systems may need more steps.
- **Mixing beta** — controls how strongly new density/potential replaces old density/potential.

Mixing tendencies:

- mixing beta too high → oscillation or divergence
- mixing beta too low → slow convergence
- metals, magnetic systems, low-dimensional systems, and large cells often need gentler mixing

## Advice boundaries

Convergence advice should be conservative and transparent:

- Tight thresholds increase cost; do not apply them silently.
- Relaxation and final single-point calculations may need different thresholds.
- Smearing, k-points, and convergence interact; changing one can expose problems in another.
- If the code cannot infer a property, preserve uncertainty as a warning rather than hiding it in a default.
