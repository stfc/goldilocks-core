# k-points

DFT integrates over the Brillouin zone. k-points sample that integration. Too few k-points can make energies, forces, stresses, and electronic properties inaccurate. Too many k-points waste compute.

## Grids and Gamma conventions

Monkhorst-Pack-style grids are standard for periodic systems. They are usually expressed as explicit dimensions:

```text
(nk1, nk2, nk3)
```

Gamma-centered means the grid includes Γ, but the details are convention- and code-dependent.

For Quantum ESPRESSO `K_POINTS automatic`, the three trailing shift flags use this convention:

- `0 0 0` — unshifted grid; Gamma is included.
- `1 1 1` — half-grid shift in each direction.

Do not assume that “even grid = misses Gamma”. Gamma inclusion depends on both the grid and the shift convention. Odd grids are often convenient for symmetric unshifted meshes, but they are not a universal rule.

## k-spacing and reciprocal lattice convention

K-point density can be represented as a reciprocal-space spacing in Å⁻¹. The package converts spacing to a mesh using reciprocal lattice vector lengths.

The current k-mesh code uses pymatgen's solid-state reciprocal lattice convention, which includes the `2π` factor. That matches VASP-style `KSPACING` semantics:

```text
N_i = max(1, ceil(|b_i| / spacing))
```

where `|b_i|` is the reciprocal lattice vector length for direction `i`.

When touching this code, be explicit about whether a spacing is crystallographic reciprocal length or solid-state reciprocal length including `2π`.

## Representations used in this package

Goldilocks may encounter several related k-mesh representations:

- **k-distance / k-spacing** in Å⁻¹ — target maximum reciprocal-space spacing.
- **mesh** `(nk1, nk2, nk3)` — explicit grid dimensions.
- **k-distance interval** — range of spacing values that map to the same mesh.
- **k-line density interval** — range of line-density values that map to the same mesh. For one axis, the admissible range is `[(n_k - 0.5) / |b*|, (n_k + 0.5) / |b*|]`, where `n_k` is the grid dimension and `|b*|` is the reciprocal vector length. For a full mesh, intersect the three per-axis ranges; if they do not overlap, the scalar interval is undefined.
- **k-index** — integer rank for distinct meshes; the ML model predicts this kind of rank.
- **k-pra** — k-points per reciprocal atom, typically `n_atoms × nk1 × nk2 × nk3`.
- **n_reduced_kpoints** — number of symmetry-irreducible k-points after symmetry reduction.

Do not stuff all of these into user-facing advice unless the interface actually needs them. They are useful for ranking, provenance, diagnostics, and compatibility tests.

## Trade-offs

- Metals usually need denser k-point meshes than insulators because the Fermi surface is sharp.
- Small primitive cells usually need denser meshes than large supercells.
- 2D and 1D systems need fewer k-points in non-periodic directions, but the code must know which directions are non-periodic before making that choice.
- Symmetry can reduce the number of irreducible k-points and cost, but the full mesh still controls sampling density.

## Advice vs selection

Keep these stages separate:

- **Analysis** may report dimensionality, cell lengths, reciprocal lengths, and symmetry facts.
- **Advice** may recommend a target spacing, accuracy level, or whether metallic systems need denser sampling.
- **Selection** converts advice into a concrete mesh and shift.
- **Generation** writes the selected mesh in the target code's syntax.

Generators should not silently decide k-point density. If they need a value, it should already exist in advice or selection.

## Tests to protect

When changing k-point code, prefer tests that assert behaviours rather than implementation trivia:

- spacing-to-mesh conversion uses the documented reciprocal lattice convention
- anisotropic cells produce anisotropic meshes
- Gamma/shift handling matches the target code convention
- model-predicted k-index maps to the expected mesh entry
- old public fields remain available if compatibility requires them
