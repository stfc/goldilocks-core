from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pymatgen.core import Lattice, Structure

from goldilocks_core import CalculationHints, CalculationIntent, generate, recommend
from goldilocks_core.advice import METALLIC_SMEARING_WIDTH_RY
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


def test_elemental_metal_uses_modest_cold_smearing_in_qe_rydberg_units(
    pseudo_metadata_factory: Callable[..., PseudoMetadata],
) -> None:
    """Metal heuristics should produce the documented conservative QE starting point."""
    aluminium = Structure(Lattice.cubic(4.05), ["Al"], [[0.0, 0.0, 0.0]])

    result = generate(
        aluminium,
        hints=CalculationHints(k_grid=(8, 8, 8)),
        pseudo_metadata=[pseudo_metadata_factory("Al")],
    )

    assert result.analysis.electronic_character == "likely_metal"
    assert result.advice.smearing.smearing_type == "cold"
    assert result.advice.smearing.width_ry == METALLIC_SMEARING_WIDTH_RY == 0.01
    qe_input = result.generated_files[0].content
    assert "  occupations = 'smearing'" in qe_input
    assert "  smearing = 'cold'" in qe_input
    assert "  degauss = 0.01" in qe_input
    assert "Metallicity is inferred" in " ".join(result.warnings)


def test_heavy_element_prompts_for_soc_without_silently_enabling_it() -> None:
    """Structure-only evidence is insufficient to incur SOC cost automatically."""
    iodine = Structure(Lattice.cubic(7.0), ["I"], [[0.0, 0.0, 0.0]])

    result = recommend(
        iodine,
        hints=CalculationHints(k_grid=(2, 2, 2)),
    )

    assert result.analysis.heavy_elements == ("I",)
    assert result.advice.spin_orbit.consider is True
    assert result.advice.spin_orbit.enabled is False
    assert result.advice.pseudopotentials.relativistic_mode == "scalar"
    assert "SOC is not enabled automatically" in " ".join(result.warnings)


def test_explicit_soc_couples_fully_relativistic_pseudos_to_qe_noncollinear_flags(
    pseudo_metadata_factory: Callable[..., PseudoMetadata],
) -> None:
    """An explicit SOC decision must propagate through selection and generation."""
    iodine = Structure(Lattice.cubic(7.0), ["I"], [[0.0, 0.0, 0.0]])

    result = generate(
        iodine,
        hints=CalculationHints(k_grid=(2, 2, 2), spin_orbit_coupling=True),
        pseudo_metadata=[pseudo_metadata_factory("I", relativistic="full")],
    )

    assert result.advice.spin_orbit.enabled is True
    assert result.advice.spin_orbit.consider is False
    assert result.advice.pseudopotentials.relativistic_mode == "full"
    assert result.selection.pseudopotentials[0].filename == "I.UPF"
    qe_input = result.generated_files[0].content
    assert "  noncolin = .true." in qe_input
    assert "  lspinorb = .true." in qe_input
    assert "  nspin = 2" not in qe_input


def test_pseudopotential_functional_must_match_calculation_functional(
    silicon_structure: Structure,
    pseudo_metadata_factory: Callable[..., PseudoMetadata],
) -> None:
    """Selection must not silently mix PBE and PBEsol datasets."""
    pbe = pseudo_metadata_factory("Si", functional="PBE", root=Path("/pbe"))
    pbesol = pseudo_metadata_factory("Si", functional="PBEsol", root=Path("/pbesol"))

    result = recommend(
        silicon_structure,
        intent=CalculationIntent(functional="PBEsol"),
        hints=CalculationHints(k_grid=(4, 4, 4)),
        pseudo_metadata=[pbe, pbesol],
    )

    assert result.advice.pseudopotentials.functional == "PBEsol"
    assert result.selection.pseudopotentials[0].filepath == pbesol.filepath
    assert result.selection.pseudopotentials[0].filepath != pbe.filepath
