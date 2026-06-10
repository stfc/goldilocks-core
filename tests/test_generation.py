import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    ParameterAdvice,
)
from goldilocks_core.generation import generate_inputs
from goldilocks_core.kmesh import resolve_kpoints_from_advice
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.selection import select_parameters


def make_structure() -> Structure:
    """Build a simple silicon structure."""
    return Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def make_metadata() -> PseudoMetadata:
    """Build synthetic pseudopotential metadata with cutoffs."""
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        library="SSSP",
        element="Si",
        pseudo_type="NC",
        functional="PBE",
        relativistic="scalar",
        sssp_recommended_cutoff={"ecutwfc_ry": 35, "ecutrho_ry": 140},
    )


def select_from_advice(
    structure: Structure,
    advice: ParameterAdvice,
    *,
    hints: CalculationHints,
    metadata_list: list[PseudoMetadata],
):
    """Resolve k-points through Kmesh before running Select."""
    return select_parameters(
        structure,
        advice,
        resolve_kpoints_from_advice(structure, hints, advice.k_points),
        metadata_list=metadata_list,
    )


def test_generate_inputs_writes_qe_values_from_advice_and_selection() -> None:
    """Generate QE input text from completed advice and selection records."""
    structure = make_structure()
    hints = CalculationHints(
        k_grid=(3, 3, 2),
        pseudo_type="NC",
        smearing_type="cold",
        smearing_width_ry=0.02,
        conv_thr=1e-8,
        mixing_beta=0.25,
        electron_maxstep=120,
    )
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    files = generate_inputs(
        structure,
        advice=advice,
        intent=advice_context(),
        selection=selection,
    )

    assert len(files) == 1
    assert files[0].path == "inputs/qe.in"
    content = files[0].content
    assert "ecutwfc = 35" in content
    assert "ecutrho = 140" in content
    assert "smearing = 'cold'" in content
    assert "degauss = 0.02" in content
    assert "conv_thr = 1.0000000000e-08" in content
    assert "mixing_beta = 0.25" in content
    assert "electron_maxstep = 120" in content
    assert "Si.UPF" in content
    assert "3  3  2  0  0  0" in content


def test_generate_inputs_uses_noncollinear_soc_without_nspin() -> None:
    """Write QE SOC flags without collinear nspin syntax."""
    structure = make_structure()
    metadata = make_metadata()
    metadata.relativistic = "full"
    hints = CalculationHints(
        k_grid=(3, 3, 3),
        pseudo_type="NC",
        spin_polarized=True,
        spin_orbit_coupling=True,
    )
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[metadata],
    )

    files = generate_inputs(structure, advice_context(), advice, selection)

    content = files[0].content
    assert "noncolin = .true." in content
    assert "lspinorb = .true." in content
    assert "nspin = 2" not in content


def test_generate_inputs_rejects_missing_pseudopotential_selection() -> None:
    """Do not let generators invent missing pseudopotentials or cutoffs."""
    structure = make_structure()
    hints = CalculationHints()
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[],
    )

    with pytest.raises(ValueError, match="complete pseudo and cutoff"):
        generate_inputs(structure, advice_context(), advice, selection)


def advice_context() -> CalculationIntent:
    """Return the default intent without obscuring test expectations."""
    return CalculationIntent()
