import pytest

from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.result import Records
from goldilocks_core.serialization import to_portable


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
    assert to_portable(records) == {
        "analysis": to_portable(analysis),
    }


def test_calculation_intent_validates_pseudo_accuracy() -> None:
    assert CalculationIntent(pseudo_accuracy="precision").pseudo_accuracy == "precision"
    with pytest.raises(ValueError, match="pseudo_accuracy"):
        CalculationIntent(pseudo_accuracy="fast")


def test_hints_serialize_explicit_grid_as_list() -> None:
    data = to_portable(CalculationHints(k_grid=(2, 2, 1)))

    assert data["k_grid"] == [2, 2, 1]


def test_calculation_intent_defaults_to_pbesol() -> None:
    assert CalculationIntent().functional == "PBEsol"
