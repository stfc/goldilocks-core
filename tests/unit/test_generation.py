from dataclasses import replace
from typing import get_args

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advice.parameters import ParameterAdvice, advise_parameters
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.qe.scf import _QE_SMEARING, _QE_VDW_CORR
from goldilocks_core.generation.registry import generate_inputs
from goldilocks_core.kmesh.resolve import KPointSelection, resolve_kpoints
from goldilocks_core.provenance import Provenance
from goldilocks_core.pseudo.metadata import PseudoCutoffs, PseudoMetadata
from goldilocks_core.selection import select_pseudopotentials
from goldilocks_core.types import SmearingType, VdwMethod


def make_structure() -> Structure:
    return Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


def make_bulk_structure() -> Structure:
    a = 5.43
    return Structure(
        lattice=Lattice([[0, a / 2, a / 2], [a / 2, 0, a / 2], [a / 2, a / 2, 0]]),
        species=["Si", "Si"],
        coords=[[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
    )


def make_metadata() -> PseudoMetadata:
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        provider="sssp",
        accuracy="efficiency",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        cutoffs=PseudoCutoffs(
            ecutwfc_ry=35,
            ecutrho_ry=140,
        ),
        source_identifier="synthetic/Si.UPF",
    )


def _stub_backend(structure: Structure) -> KPointSelection:
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
    k_points = resolve_kpoints(structure, hints, _stub_backend)
    selection = select_pseudopotentials(
        structure, advice.pseudopotential_requirements, metadata_list
    )
    return selection, k_points


def test_generate_inputs_writes_qe_values_from_advice_and_selection() -> None:
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


def test_generate_inputs_rejects_selected_functional_disagreement() -> None:
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection, k_points = select_from_advice(
        structure,
        advice,
        hints=hints,
        metadata_list=[make_metadata()],
    )
    selected = replace(selection.pseudopotentials[0], functional="PBE")
    mismatched = replace(selection, pseudopotentials=(selected,))

    with pytest.raises(GenerationError, match="functional mismatch for Si"):
        generate_inputs(
            structure,
            advice_context(),
            advice,
            mismatched,
            k_points,
        )


@pytest.mark.parametrize("shift", [(1, 0, 0), (0, 1, 0), (0, 0, 1)])
def test_generate_inputs_writes_each_k_points_component_in_order(shift) -> None:
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
        shift=shift,
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

    assert f"  2  3  4  {shift[0]}  {shift[1]}  {shift[2]}" in files[0].content


def test_generate_inputs_uses_noncollinear_soc_without_nspin() -> None:
    structure = make_structure()
    metadata = replace(make_metadata(), relativistic="full")
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
    assert set(_QE_SMEARING) == set(get_args(SmearingType)) - {"fixed"}


def test_qe_vdw_translation_map_exactly_covers_supported_methods() -> None:
    assert set(_QE_VDW_CORR) == set(get_args(VdwMethod))


def test_generate_inputs_writes_vdw_corr_when_enabled() -> None:
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
    return CalculationIntent()


@pytest.mark.parametrize(
    ("smearing_type", "qe_smearing"),
    [("gaussian", "gaussian"), ("mp", "mp"), ("cold", "cold")],
)
def test_generate_inputs_writes_smearing_lines(
    smearing_type: str,
    qe_smearing: str,
) -> None:
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
    structure = make_structure()
    hints = CalculationHints(k_grid=(2, 2, 2), pseudo_type="NC")
    advice = advise_parameters(analyze_structure(structure), hints=hints)
    selection = select_pseudopotentials(
        structure, advice.pseudopotential_requirements, ()
    )
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
