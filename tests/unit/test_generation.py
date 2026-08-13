from dataclasses import replace
from typing import get_args

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    KPointSelection,
    ParameterAdvice,
    Provenance,
    PseudoMetadata,
    SmearingType,
    VdwMethod,
)
from goldilocks_core.generation import generate_inputs
from goldilocks_core.generation.qe.scf import _QE_SMEARING, _QE_VDW_CORR
from goldilocks_core.kmesh import resolve_kpoints
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
        functional="PBEsol",
        relativistic="scalar",
        sssp_recommended_cutoff={"ecutwfc_ry": 35, "ecutrho_ry": 140},
    )


def _stub_backend(structure: Structure) -> KPointSelection:
    """Deterministic k-point backend for selection/generation unit tests."""
    return KPointSelection(
        grid=(4, 4, 4),
        shift=(0, 0, 0),
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="model", reason="stub"),
    )


def select_from_advice(
    structure: Structure,
    advice: ParameterAdvice,
    *,
    hints: CalculationHints,
    metadata_list: list[PseudoMetadata],
):
    """Resolve k-points through Kmesh and run Select; return (selection, k_points)."""
    k_points = resolve_kpoints(structure, hints.kmesh, _stub_backend)
    selection = select_parameters(structure, advice, metadata_list=metadata_list)
    return selection, k_points


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
    selection, k_points = select_from_advice(
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
        k_points=k_points,
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


def test_generate_inputs_writes_each_k_points_component_in_order() -> None:
    """Non-uniform K_POINTS grids and shifts render each component in position."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, _ = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )
    k_points = KPointSelection(
        grid=(2, 3, 4),
        shift=(1, 2, 3),
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="user_hint", reason="distinct components"),
    )

    files = generate_inputs(
        structure,
        advice=advice,
        intent=advice_context(),
        selection=selection,
        k_points=k_points,
    )

    assert "  2  3  4  1  2  3" in files[0].content


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
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[metadata],
    )

    files = generate_inputs(structure, advice_context(), advice, selection, k_points)

    content = files[0].content
    assert "noncolin = .true." in content
    assert "lspinorb = .true." in content
    assert "nspin = 2" not in content


def test_qe_smearing_translation_map_exactly_covers_enabled_methods() -> None:
    """Keep every non-fixed occupation scheme mapped explicitly."""
    assert set(_QE_SMEARING) == set(get_args(SmearingType)) - {"fixed"}


def test_qe_vdw_translation_map_exactly_covers_supported_methods() -> None:
    """Keep every domain method translated by the supported QE target."""
    assert set(_QE_VDW_CORR) == set(get_args(VdwMethod))


def test_generate_inputs_writes_vdw_corr_when_enabled() -> None:
    """Emit the QE vdw_corr keyword when vdW is enabled via hints."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC", use_vdw=True)
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection, k_points)[
        0
    ].content

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
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection, k_points)[
        0
    ].content

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
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection, k_points)[
        0
    ].content

    assert f"vdw_corr = '{qe_vdw_corr}'" in content
    assert "dftd3_version" not in content


def test_generate_inputs_omits_vdw_corr_by_default() -> None:
    """Do not write vdw_corr for 3D bulk without an explicit vdW hint."""
    structure = make_bulk_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection, k_points)[
        0
    ].content

    assert "vdw_corr" not in content


def test_generate_inputs_produces_full_expected_qe_input() -> None:
    """The complete QE SCF input matches the expected deterministic layout."""
    structure = make_bulk_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection, k_points)[
        0
    ].content

    expected = r"""&CONTROL
  calculation = 'scf'
  pseudo_dir = './pseudo'
  outdir = './out'
  tprnfor = .true.
  tstress = .true.
/

&SYSTEM
  ibrav = 0
  nat = 2
  ntyp = 1
  ecutwfc = 35
  ecutrho = 140
  occupations = 'fixed'
/

&ELECTRONS
  conv_thr = 1.0000000000e-06
  mixing_beta = 0.4
  electron_maxstep = 80
/

CELL_PARAMETERS angstrom
  0  2.715  2.715
  2.715  0  2.715
  2.715  2.715  0

ATOMIC_SPECIES
  Si  28.0855  Si.UPF

ATOMIC_POSITIONS crystal
  Si  0  0  0
  Si  0.25  0.25  0.25

K_POINTS automatic
  2  2  2  0  0  0
"""
    assert content == expected


def test_generate_inputs_rejects_unsupported_target_code() -> None:
    """Unregistered target codes are rejected at the dispatch table."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )
    intent = CalculationIntent(code="vasp")

    with pytest.raises(ValueError, match="No input writer registered for code='vasp'"):
        generate_inputs(structure, intent, advice, selection, k_points)


def test_generate_inputs_rejects_unsupported_task() -> None:
    """Unregistered tasks are rejected at the dispatch table."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )
    intent = CalculationIntent(task="relax")

    with pytest.raises(
        ValueError, match="No input writer registered for .*task='relax'"
    ):
        generate_inputs(structure, intent, advice, selection, k_points)


def test_generate_inputs_rejects_unsafe_pseudopotential_filename() -> None:
    """Reject pseudopotential filenames that are unsafe to render verbatim."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )
    pseudo = replace(selection.pseudopotentials[0], filename="Si.UPF\n/")

    with pytest.raises(ValueError, match="Unsafe pseudopotential filename"):
        generate_inputs(
            structure,
            advice_context(),
            advice,
            replace(selection, pseudopotentials=(pseudo,)),
            k_points=k_points,
        )


def advice_context() -> CalculationIntent:
    """Return the default intent without obscuring test expectations."""
    return CalculationIntent()


@pytest.mark.parametrize(
    ("smearing_type", "qe_smearing"),
    [("gaussian", "gaussian"), ("mp", "mp"), ("cold", "cold")],
)
def test_generate_inputs_writes_smearing_lines(
    smearing_type: str,
    qe_smearing: str,
) -> None:
    """Emit the exact QE smearing keyword for every enabled method."""
    structure = make_structure()
    hints = CalculationHints(
        k_grid=(2, 2, 2),
        pseudo_type="NC",
        smearing_type=smearing_type,
        smearing_width_ry=0.02,
    )
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection, k_points)[
        0
    ].content

    assert "  occupations = 'smearing'" in content
    assert f"  smearing = '{qe_smearing}'" in content
    assert "  degauss = 0.02" in content


def test_generate_inputs_writes_nspin_2_when_spin_polarized() -> None:
    """Emit collinear nspin=2 without SOC flags for a spin-polarized run."""
    structure = make_structure()
    hints = CalculationHints(
        k_grid=(2, 2, 2),
        pseudo_type="NC",
        spin_polarized=True,
    )
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection, k_points)[
        0
    ].content

    assert "  nspin = 2" in content
    assert "noncolin" not in content
    assert "lspinorb" not in content


def test_generate_inputs_system_block_orders_smearing_spin_vdw() -> None:
    """The SYSTEM namelist orders smearing, spin, then vdW lines exactly."""
    structure = make_structure()
    hints = CalculationHints(
        k_grid=(2, 2, 2),
        pseudo_type="NC",
        smearing_type="mp",
        smearing_width_ry=0.01,
        spin_polarized=True,
        use_vdw=True,
        vdw_method="d3bj",
    )
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    content = generate_inputs(structure, advice_context(), advice, selection, k_points)[
        0
    ].content

    system = content.split("&SYSTEM")[1].split("/")[0]
    assert system == (
        "\n  ibrav = 0\n  nat = 1\n  ntyp = 1\n"
        "  ecutwfc = 35\n  ecutrho = 140\n"
        "  occupations = 'smearing'\n  smearing = 'mp'\n  degauss = 0.01\n"
        "  nspin = 2\n"
        "  vdw_corr = 'grimme-d3'\n  dftd3_version = 4\n"
    )


def test_generate_inputs_rejects_unsupported_smearing_method() -> None:
    """Reject a smearing method the QE target cannot translate."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    advice = replace(
        advice,
        smearing=replace(
            advice.smearing,
            smearing_type="bogus",
            width_ry=0.02,
        ),
    )
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    with pytest.raises(ValueError, match="unsupported method 'bogus'"):
        generate_inputs(structure, advice_context(), advice, selection, k_points)


def test_generate_inputs_rejects_missing_smearing_width() -> None:
    """Require a smearing width whenever smearing is enabled."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    advice = replace(
        advice,
        smearing=replace(
            advice.smearing,
            smearing_type="gaussian",
            width_ry=None,
        ),
    )
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    with pytest.raises(
        ValueError, match="Smearing width is required when smearing is enabled"
    ):
        generate_inputs(structure, advice_context(), advice, selection, k_points)


def test_generate_inputs_rejects_unsupported_vdw_method() -> None:
    """Reject an enabled vdW method the QE target cannot translate."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    advice = replace(
        advice,
        vdw=replace(advice.vdw, use_vdw=True, method="bogus"),
    )
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    with pytest.raises(
        ValueError, match="enabled vdW requires a supported method; got 'bogus'"
    ):
        generate_inputs(structure, advice_context(), advice, selection, k_points)


def test_generate_inputs_rejects_disabled_vdw_with_method() -> None:
    """Reject a method label when vdW is disabled."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    advice = replace(
        advice,
        vdw=replace(advice.vdw, use_vdw=False, method="d3"),
    )
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    with pytest.raises(ValueError, match="disabled vdW requires method=None; got 'd3'"):
        generate_inputs(structure, advice_context(), advice, selection, k_points)


def test_generate_inputs_rejects_disordered_structure() -> None:
    """Reject disordered structures before rendering any QE text."""
    structure = Structure(
        lattice=Lattice.cubic(4.0),
        species=[{"Si": 0.5, "Ge": 0.5}],
        coords=[[0.0, 0.0, 0.0]],
    )
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    with pytest.raises(
        ValueError,
        match="Cannot generate Quantum ESPRESSO input for disordered structures",
    ):
        generate_inputs(structure, advice_context(), advice, selection, k_points)


def test_generate_inputs_rejects_incomplete_pseudopotential_selection() -> None:
    """Reject a valid fallback selection that cannot produce QE syntax."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_parameters(structure, advice, metadata_list=[])
    k_points = KPointSelection(
        grid=(2, 2, 2),
        shift=(0, 0, 0),
        mesh_type="monkhorst-pack",
        provenance=Provenance(source="model", reason="stub"),
    )

    with pytest.raises(
        ValueError,
        match="Pseudopotential selection for Si is incomplete",
    ):
        generate_inputs(structure, advice_context(), advice, selection, k_points)


def test_write_qe_scf_returns_single_input_file_record() -> None:
    """The QE writer returns exactly one input file with the canonical path."""
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )

    files = generate_inputs(structure, advice_context(), advice, selection, k_points)

    assert len(files) == 1
    assert files[0].path == "inputs/qe.in"
    assert files[0].role == "input"
    assert files[0].content.endswith("\n")
