import numpy as np
import pytest

from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.ml.models import StructureFeatureVector
from goldilocks_core.result import Records


def _make_analysis() -> StructureAnalysisRecord:
    return StructureAnalysisRecord(
        formula="Si1",
        reduced_formula="Si",
        site_count=1,
        elements=("Si",),
        contains_transition_metals=False,
        contains_lanthanides=False,
        contains_actinides=False,
        contains_heavy_elements=False,
        magnetic_elements=(),
        heavy_elements=(),
    )


def test_core_records_maps_requested_types_and_serializes_record_names() -> None:
    analysis = _make_analysis()
    records = Records({StructureAnalysisRecord: analysis})

    assert records[StructureAnalysisRecord] is analysis
    assert tuple(records) == (StructureAnalysisRecord,)
    assert records.to_dict() == {
        "analysis": analysis.to_dict(),
    }


def test_calculation_intent_validates_pseudo_accuracy() -> None:
    assert CalculationIntent(pseudo_accuracy="precision").pseudo_accuracy == "precision"
    with pytest.raises(ValueError, match="pseudo_accuracy"):
        CalculationIntent(pseudo_accuracy="fast")


def test_hints_serialize_explicit_grid_as_list() -> None:
    data = CalculationHints(k_grid=(2, 2, 1)).to_dict()

    assert data["k_grid"] == [2, 2, 1]


def test_calculation_hints_expose_per_stage_views() -> None:
    hints = CalculationHints(
        k_grid=(2, 2, 1),
        k_spacing=0.25,
        smearing_type="cold",
        smearing_width_ry=0.01,
        spin_polarized=True,
        spin_orbit_coupling=False,
        pseudo_accuracy="precision",
        pseudo_type="NC",
        relativistic_mode="full",
        conv_thr=1e-8,
        mixing_beta=0.2,
        electron_maxstep=120,
        use_vdw=True,
        vdw_method="ts",
    )

    assert hints.kmesh.k_grid == (2, 2, 1)
    assert hints.kmesh.k_spacing == 0.25
    assert hints.smearing.smearing_type == "cold"
    assert hints.smearing.smearing_width_ry == 0.01
    assert hints.spin.spin_polarized is True
    assert hints.spin.spin_orbit_coupling is False
    assert hints.pseudo.accuracy == "precision"
    assert hints.pseudo.pseudo_type == "NC"
    assert hints.pseudo.relativistic_mode == "full"
    assert hints.convergence.conv_thr == 1e-8
    assert hints.convergence.mixing_beta == 0.2
    assert hints.convergence.electron_maxstep == 120
    assert hints.vdw.use_vdw is True
    assert hints.vdw.vdw_method == "ts"


def test_feature_vectors_serialize_numpy_values_as_json_lists() -> None:
    data = StructureFeatureVector(
        values=np.array([1.0, 2.0]),
        feature_names=["a", "b"],
    ).to_dict()

    assert data["values"] == [1.0, 2.0]


def test_calculation_intent_defaults_to_pbesol() -> None:
    assert CalculationIntent().functional == "PBEsol"
