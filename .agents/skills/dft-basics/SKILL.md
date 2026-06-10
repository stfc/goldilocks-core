---
name: dft-basics
description: Domain triage and reference for DFT input recommendation in goldilocks-core. Load when touching k-points, pseudopotentials, smearing, convergence, spin-orbit coupling, structure-analysis flags, or scientific default/provenance decisions.
---

# DFT Basics

Goldilocks recommends DFT calculation inputs. This skill keeps the physics decisions separate from code-formatting mechanics.

Use it when you need to decide *why* a parameter should be advised, selected, warned about, or left to the user. Do not use it as a substitute for target-code documentation; always verify syntax and edge cases against the implemented code path.

## Progressive disclosure

Start here, then load the reference file that matches the physics question.

- `references/k-points.md` — Brillouin-zone sampling, Gamma conventions, k-spacing, mesh ranking, and code-specific caveats.
- `references/pseudopotentials.md` — NC/ultrasoft/PAW, functional matching, relativistic treatment, SSSP families, cutoffs, and SOC pseudopotential requirements.
- `references/smearing-soc-convergence.md` — smearing, spin polarization, SOC relevance, convergence thresholds, and mixing.

If a change touches more than one domain, read each matching reference.

## Working pattern

1. **Classify the question** — k-points, pseudopotentials, smearing, SOC, convergence, or cross-cutting advice/provenance.
2. **Read the matching reference** before changing physics-bearing code or docs.
3. **Separate stages**:
   - Analysis reports facts about the structure.
   - Advice chooses scientific or numerical intent.
   - Selection resolves advice into concrete files, grids, cutoffs, or settings.
   - Generation translates completed decisions into target-code syntax.
4. **Record provenance** for scientific choices: user hint, analysis-derived decision, default, lookup, model, or fallback.
5. **Verify code-specific semantics** before encoding assumptions. In particular, k-point shifts, Gamma inclusion, relativistic flags, and SOC settings differ by code.

## Quick principles

- Do not silently enable expensive physics. For example, heavy elements should usually trigger SOC consideration, not automatic SOC.
- Do not let generators invent scientific defaults. Put those choices in advice or selection records.
- Do not assume PAW means fully relativistic or all-electron. PAW is usually still frozen-core, and relativistic treatment is a separate dataset property.
- Do not assume even k-point grids miss Gamma. Gamma inclusion depends on the grid convention and shift.
- Prefer conservative warnings when the code cannot know the science question.

## Target codes

Goldilocks may target multiple DFT codes. Support must be verified in the codebase; do not assume a target is implemented just because it is listed here.

Common target codes:
- **Quantum ESPRESSO** — plane-wave pseudopotential code. Input is Fortran namelists plus cards.
- **VASP** — plane-wave PAW code. Uses POSCAR, INCAR, KPOINTS, and POTCAR. POTCAR files are licensed, so tools should not ship them.
- **CASTEP** — plane-wave pseudopotential code. Input is `.cell` and `.param` files.
- **ONETEP** — linear-scaling DFT code, common in UK materials modelling.
