from typing import get_args

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    ParameterAdvice,
    VdwMethod,
)
from goldilocks_core.generation import _QE_VDW_CORR, generate_inputs
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


def make_bulk_structure() -> Structure:
    """Build a fully bonded 3D diamond-silicon cell (no vacuum)."""
    a = 5.43
    return Structure(
        lattice=Lattice([[0, a / 2, a / 2], [a / 2, 0, a / 2], [a / 2, a / 2, 0]]),
        species=["Si", "Si"],
        coords=[[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
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


def test_qe_vdw_translation_map_exactly_covers_supported_methods() -> None:
    """Keep every domain method translated by the supported QE target."""
    assert set(_QE_VDW_CORR) == set(get_args(VdwMethod))


def test_generate_inputs_writes_vdw_corr_when_enabled() -> None:
    """Emit the QE vdw_corr keyword when vdW is enabled via hints."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC", use_vdw=True)
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection)[0].content

    # D3BJ is the default method: QE uses grimme-d3 with BJ damping (version 4).
    assert "vdw_corr = 'grimme-d3'" in content
    assert "dftd3_version = 4" in content


def test_generate_inputs_writes_d3_zero_damping_version() -> None:
    """Select D3 zero damping (version 3) for the plain d3 method."""
    structure = make_structure()
    hints = CalculationHints(
        k_grid=(2, 2, 2), pseudo_type="NC", use_vdw=True, vdw_method="d3"
    )
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection)[0].content

    assert "vdw_corr = 'grimme-d3'" in content
    assert "dftd3_version = 3" in content


@pytest.mark.parametrize(
    ("vdw_method", "qe_vdw_corr"),
    [("ts", "ts-vdw"), ("mbd", "many-body-dispersion")],
)
def test_generate_inputs_writes_non_d3_vdw_methods(
    vdw_method: str,
    qe_vdw_corr: str,
) -> None:
    """Map TS and MBD advice without emitting a D3 damping version."""
    structure = make_structure()
    hints = CalculationHints(
        k_grid=(2, 2, 2),
        pseudo_type="NC",
        use_vdw=True,
        vdw_method=vdw_method,
    )
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection)[0].content

    assert f"vdw_corr = '{qe_vdw_corr}'" in content
    assert "dftd3_version" not in content


@pytest.mark.parametrize(
    ("use_vdw", "method"),
    [
        (True, None),
        (True, []),
        (True, {}),
        (True, True),
        (True, "unknown"),
        (False, "d3"),
    ],
    ids=["enabled-none", "list", "mapping", "boolean", "unknown", "disabled"],
)
def test_generate_inputs_rejects_malformed_injected_vdw_advice(
    use_vdw: bool,
    method: object,
) -> None:
    """Report malformed injected vdW advice with a QE-specific error."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC", use_vdw=True)
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )
    object.__setattr__(advice.vdw, "use_vdw", use_vdw)
    object.__setattr__(advice.vdw, "method", method)

    with pytest.raises(ValueError, match="Quantum ESPRESSO vdW advice is invalid"):
        generate_inputs(structure, advice_context(), advice, selection)


def test_generate_inputs_omits_vdw_corr_by_default() -> None:
    """Do not write vdw_corr for 3D bulk without an explicit vdW hint."""
    structure = make_bulk_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection)[0].content

    assert "vdw_corr" not in content


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


@pytest.mark.parametrize("field", ["ecutwfc_ry", "ecutrho_ry"])
@pytest.mark.parametrize(
    "invalid_value",
    ["not-a-number", float("nan"), float("inf"), -float("inf"), 0, -1, True],
)
def test_generate_inputs_defensively_rejects_invalid_cutoffs(
    field: str,
    invalid_value: object,
) -> None:
    """Refuse malformed selection records even if contract validation is bypassed."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )
    object.__setattr__(selection.pseudopotentials[0], field, invalid_value)

    with pytest.raises(ValueError, match="invalid cutoff selections"):
        generate_inputs(structure, advice_context(), advice, selection)


def advice_context() -> CalculationIntent:
    """Return the default intent without obscuring test expectations."""
    return CalculationIntent()
