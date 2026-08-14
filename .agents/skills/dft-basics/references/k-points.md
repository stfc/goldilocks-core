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

Goldilocks uses three k-mesh representations:

- **k-distance / k-spacing** in Å⁻¹: the maximum reciprocal-space spacing.
- **mesh** `(nk1, nk2, nk3)`: the selected grid dimensions.
- **k-index**: a 1-based rank in an ordered table of distinct meshes. A local
  k-index model predicts this value.

Keep these representations separate. Convert a spacing or model prediction to a
mesh in the Kmesh stage. User-facing output should report the selected mesh and
its provenance.

## Related measure: k-line density

Some external k-mesh datasets use k-line density instead of reciprocal-space
spacing. Goldilocks does not expose k-line density in its current interface, but
an importer can need the conversion.

For one reciprocal axis, a grid size `n` admits this line-density interval:

```text
[(n - 0.5) / |b*|, (n + 0.5) / |b*|]
```

For a three-dimensional mesh, intersect the intervals for all three axes. If
the intervals do not overlap, one scalar k-line density cannot represent the
mesh.

## Trade-offs

- Metals usually need denser k-point meshes than insulators because the Fermi surface is sharp.
- Small primitive cells usually need denser meshes than large supercells.
- 2D and 1D systems need fewer k-points in non-periodic directions, but the code must know which directions are non-periodic before making that choice.
- Symmetry can reduce the number of irreducible k-points and cost, but the full mesh still controls sampling density.

## Hints, Kmesh, and generation

- **Analysis** reports structure facts such as dimensionality and symmetry.
- **Hints** can supply an explicit grid or spacing.
- **Kmesh** gives an explicit grid priority over spacing. If neither is set, it
  uses the configured model.
- **Generation** writes the selected grid and shift in the target-code syntax.

Generation does not choose k-point density.

## Tests to protect

When changing k-point code, prefer tests that assert behaviours rather than implementation trivia:

- spacing-to-mesh conversion uses the documented reciprocal lattice convention
- anisotropic cells produce anisotropic meshes
- Gamma/shift handling matches the target code convention
- model-predicted k-index maps to the expected mesh entry
- explicit hints bypass model loading
